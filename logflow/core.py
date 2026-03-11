import os
import re
import shutil
import sys
import time
from datetime import datetime
from multiprocessing import current_process
from pathlib import Path
from typing import Any, Optional, TypedDict, Union

from loguru import logger

from logflow import discovery
from logflow.config import load_config
from logflow.intercept import setup_interception


class State(TypedDict):
    configured: bool
    log_file: Optional[Path]


# Authority state (SHARED dictionary to survive reloads if possible)
_STATE: State = {
    "configured": False,
    "log_file": None,
}


def _reset_state() -> None:
    """Nuclear reset for tests."""
    _STATE["configured"] = False
    _STATE["log_file"] = None
    logger.remove()


def _rotate(path: Path, retention: int = 5) -> None:
    """Manual rotation of an existing log file (Rank 0 only)."""
    if not path.exists() or path.stat().st_size == 0:
        return
    if discovery.get_rank() not in (None, 0):
        return

    timestamp = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d_%H-%M-%S")
    rotated_path = path.parent / f"{path.stem}.{timestamp}{path.suffix}"

    try:
        path.rename(rotated_path)
        # Directory-wide cleanup for THIS script
        pattern = re.escape(path.stem) + r"\.\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}" + re.escape(path.suffix)
        candidates = sorted(
            [p for p in path.parent.iterdir() if p.is_file() and re.fullmatch(pattern, p.name)],
            key=lambda p: (p.stat().st_mtime, p.name),
            reverse=True,
        )
        for old in candidates[retention:]:
            try:
                old.unlink()
            except Exception:
                pass
    except Exception:
        pass


def configure_logging(
    log_dir: Optional[Union[str, Path]] = None,
    script_name: Optional[str] = None,
    file_level: Optional[str] = None,
    console_level: Optional[str] = None,
    rotation_on_startup: Optional[bool] = None,
    retention: Optional[int] = None,
    enqueue: Optional[bool] = None,
    force: bool = False,
) -> None:
    """
    Configure the global LogFlow system with Atomic Pivot support.
    """

    # 1. Identity Check
    is_child = current_process().name != "MainProcess"
    rank = discovery.get_rank()
    is_main_rank = rank is None or rank == 0
    is_main_proc = not is_child and is_main_rank

    if _STATE["configured"] and not force:
        return

    # 2. Resolve Parameters
    file_cfg = load_config()
    log_dir_val = log_dir or os.getenv("LOGFLOW_DIR") or file_cfg.get("log_dir") or "./logs"
    log_dir_path = Path(log_dir_val).expanduser().resolve()
    log_dir_path.mkdir(parents=True, exist_ok=True)

    def resolve_level(arg: Optional[str], env: str, key: str, default: str) -> str:
        return (arg or os.getenv(env) or file_cfg.get(key) or default).upper()

    file_level_val = resolve_level(file_level, "LOGFLOW_FILE_LEVEL", "file_level", "DEBUG")
    console_level_val = resolve_level(console_level, "LOGFLOW_CONSOLE_LEVEL", "console_level", "INFO")
    retention_val = retention if retention is not None else file_cfg.get("retention", 5)
    do_rotation = rotation_on_startup if rotation_on_startup is not None else file_cfg.get("rotation_on_startup", True)

    target_name = discovery.determine_script_name(
        script_name or os.getenv("LOGFLOW_SCRIPT_NAME") or file_cfg.get("script_name")
    )
    new_log_file = log_dir_path / f"{target_name}.log"

    # 3. PIVOT & ROTATION (Authority: Main Process Only)
    if is_main_proc:
        log_file_val = _STATE["log_file"]
        current_abs = log_file_val.resolve() if log_file_val else None
        new_abs = new_log_file.resolve()

        if current_abs and new_abs != current_abs:
            # Pivot: Consolidate interim -> target
            logger.remove()  # Close current sink
            try:
                logger.complete()
            except Exception:
                pass

            if do_rotation:
                _rotate(new_log_file, retention_val)
            if log_file_val and log_file_val.exists():
                try:
                    shutil.copy2(log_file_val, new_log_file)
                    time.sleep(0.05)  # Release OS Lock
                    log_file_val.unlink()
                except Exception:
                    pass
            _STATE["configured"] = False
        elif do_rotation and not _STATE["configured"] and new_log_file.exists():
            # STARTUP: Rotate existing log of same name
            _rotate(new_log_file, retention_val)

    # 4. Standard Setup (Authority: Main Process Only)
    def rank_filter(record: Any) -> bool:
        r = discovery.get_rank()
        record["extra"]["rank_tag"] = f"[rank {r}] | " if r and r > 0 else ""
        return True

    if not _STATE["configured"] and is_main_proc:
        logger.remove()
        console_format = (
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "{extra[rank_tag]}<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        )
        logger.add(sys.stderr, level=console_level_val, format=console_format, filter=rank_filter, colorize=True)

    # 5. File Sink management
    file_format = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {extra[rank_tag]}{name}:{function}:{line} | {message}"

    logger.add(
        str(new_log_file),
        level=file_level_val,
        format=file_format,
        filter=rank_filter,
        enqueue=enqueue if enqueue is not None else False,
        rotation=None,
        retention=None,
        mode="a",
    )

    was_cfg = _STATE["configured"]
    _STATE["log_file"] = new_log_file
    _STATE["configured"] = True
    setup_interception()

    if is_main_proc:
        os.environ["_LOGFLOW_CONFIGURED"] = "1"
        os.environ["LOGFLOW_SCRIPT_NAME"] = target_name

        # Directory-wide global retention
        time.sleep(0.05)
        lfs = sorted(
            [f for f in log_dir_path.glob("*.log") if f.is_file()],
            key=lambda x: (x.stat().st_mtime, x.name),
            reverse=True,
        )
        # EXCLUDE the current log file from purging
        to_purge = [f for f in lfs if f.resolve() != new_log_file.resolve()]
        if len(to_purge) >= retention_val:
            for f in to_purge[retention_val - 1 :]:
                try:
                    f.unlink()
                except Exception:
                    pass

        logger.info(f"LogFlow {'Re-' if was_cfg else ''}initialized: {new_log_file.name}")


def shutdown_logging() -> None:
    try:
        logger.complete()
    except Exception:
        pass


def get_logger(name: Optional[str] = None) -> Any:
    if not _STATE["configured"]:
        configure_logging()
    return logger.bind(name=name) if name else logger
