import os
import re
import shutil
import sys
from datetime import datetime
from multiprocessing import current_process
from pathlib import Path
from typing import Any, List, Optional, Union

from loguru import logger

from logflow import discovery
from logflow.config import load_config
from logflow.intercept import setup_interception

_configured: bool = False
_log_file: Optional[Path] = None


def _reset_state() -> None:
    """Nuclear reset for tests."""
    global _configured, _log_file
    _configured = False
    _log_file = None
    logger.remove()
    if hasattr(discovery.get_rank, "cache_clear"):
        discovery.get_rank.cache_clear()


def _rank_filter(record: Any) -> bool:
    """Tag log records with rank information."""
    r = discovery.get_rank()
    record["extra"]["rank_tag"] = f"[rank {r}] | " if r and r > 0 else ""
    return True


def _purge_old_files(candidates: List[Path], keep: int) -> None:
    """Keep the `keep` most recent files by mtime, delete the rest."""
    by_age = sorted(candidates, key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
    for old in by_age[keep:]:
        try:
            old.unlink()
        except Exception:
            pass


def _rotate(path: Path, retention: int = 5) -> None:
    """Manual rotation of an existing log file. Caller must ensure main-process authority."""
    try:
        st = path.stat()
    except (OSError, ValueError):
        return
    if st.st_size == 0:
        return

    timestamp = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d_%H-%M-%S")
    rotated_path = path.parent / f"{path.stem}.{timestamp}{path.suffix}"

    try:
        path.rename(rotated_path)
        pattern = re.escape(path.stem) + r"\.\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}" + re.escape(path.suffix)
        candidates = [p for p in path.parent.iterdir() if p.is_file() and re.fullmatch(pattern, p.name)]
        _purge_old_files(candidates, retention)
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
    """Configure the global LogFlow system with Atomic Pivot support."""
    global _configured, _log_file

    is_main_proc = current_process().name == "MainProcess" and discovery.get_rank() in (None, 0)

    if _configured and not force:
        return

    # Resolve parameters
    file_cfg = load_config()

    def resolve_level(arg: Optional[str], env: str, key: str, default: str) -> str:
        return (arg or os.getenv(env) or file_cfg.get(key) or default).upper()

    log_dir_val = log_dir or os.getenv("LOGFLOW_DIR") or file_cfg.get("log_dir") or "./logs"
    log_dir_path = Path(log_dir_val).expanduser().resolve()
    log_dir_path.mkdir(parents=True, exist_ok=True)

    file_level_val = resolve_level(file_level, "LOGFLOW_FILE_LEVEL", "file_level", "DEBUG")
    console_level_val = resolve_level(console_level, "LOGFLOW_CONSOLE_LEVEL", "console_level", "INFO")
    retention_val = retention if retention is not None else file_cfg.get("retention", 5)
    do_rotation = rotation_on_startup if rotation_on_startup is not None else file_cfg.get("rotation_on_startup", True)

    target_name = discovery.determine_script_name(script_name or file_cfg.get("script_name"))
    new_log_file = log_dir_path / f"{target_name}.log"

    # PIVOT & ROTATION (Authority: Main Process Only)
    if is_main_proc:
        current_abs = _log_file.resolve() if _log_file else None
        new_abs = new_log_file.resolve()

        if current_abs and new_abs != current_abs:
            logger.remove()
            try:
                logger.complete()
            except Exception:
                pass

            if do_rotation:
                _rotate(new_log_file, retention_val)
            if _log_file and _log_file.exists():
                try:
                    shutil.copy2(_log_file, new_log_file)
                    _log_file.unlink()
                except Exception:
                    pass
            _configured = False
        elif do_rotation and not _configured and new_log_file.exists():
            _rotate(new_log_file, retention_val)

    # Sink Setup
    if not _configured or force:
        logger.remove()

        if is_main_proc:
            console_format = (
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                "<level>{level: <8}</level> | "
                "{extra[rank_tag]}<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
                "<level>{message}</level>"
            )
            logger.add(sys.stderr, level=console_level_val, format=console_format, filter=_rank_filter, colorize=True)

        file_format = (
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | " "{extra[rank_tag]}{name}:{function}:{line} | {message}"
        )
        logger.add(
            str(new_log_file),
            level=file_level_val,
            format=file_format,
            filter=_rank_filter,
            enqueue=enqueue if enqueue is not None else False,
            rotation=None,
            retention=None,
            mode="a",
        )

    was_cfg = _configured
    _log_file = new_log_file
    _configured = True
    setup_interception()

    if is_main_proc:
        os.environ["LOGFLOW_SCRIPT_NAME"] = target_name

        all_logs = [f for f in log_dir_path.glob("*.log") if f.is_file() and f.resolve() != new_log_file.resolve()]
        _purge_old_files(all_logs, max(retention_val - 1, 0))

        logger.info(f"LogFlow {'Re-' if was_cfg else ''}initialized: {new_log_file.name}")


def shutdown_logging() -> None:
    try:
        logger.complete()
    except Exception:
        pass


def get_logger(name: Optional[str] = None) -> Any:
    if not _configured:
        configure_logging()
    return logger.bind(name=name) if name else logger
