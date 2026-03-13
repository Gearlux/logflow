import os
import re
import shutil
import sys
import warnings
from datetime import datetime
from multiprocessing import current_process
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Optional, Union

from loguru import logger

if TYPE_CHECKING:
    from loguru import Logger

from logflow import discovery
from logflow.config import load_config
from logflow.intercept import setup_interception


class LoggingState:
    """Singleton state management for LogFlow."""

    configured: bool = False
    log_file: Optional[Path] = None

    @classmethod
    def reset(cls) -> None:
        cls.configured = False
        cls.log_file = None
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
        except Exception as e:
            warnings.warn(f"LogFlow: Failed to purge old log file {old}: {e}")


def _rotate(path: Path, retention: int = 5) -> None:
    """Manual rotation of an existing log file (Main process only)."""
    if not path.exists() or path.stat().st_size == 0 or discovery.get_rank() not in (None, 0):
        return

    timestamp = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d_%H-%M-%S")
    rotated_path = path.parent / f"{path.stem}.{timestamp}{path.suffix}"

    try:
        path.rename(rotated_path)
        pattern = re.escape(path.stem) + r"\.\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}" + re.escape(path.suffix)
        candidates = [p for p in path.parent.iterdir() if p.is_file() and re.fullmatch(pattern, p.name)]
        _purge_old_files(candidates, retention)
    except Exception as e:
        warnings.warn(f"LogFlow: Failed to rotate log file {path}: {e}")


def _perform_pivot(current_log: Path, new_log: Path, do_rotation: bool, retention: int) -> None:
    """Transition from an interim log file to a final target file."""
    logger.remove()
    try:
        logger.complete()
    except Exception as e:
        warnings.warn(f"LogFlow: Failed to complete logger during pivot: {e}")

    if do_rotation:
        _rotate(new_log, retention)

    if current_log.exists():
        try:
            shutil.copy2(current_log, new_log)
            current_log.unlink()
        except Exception as e:
            warnings.warn(f"LogFlow: Failed to pivot logs from {current_log} to {new_log}: {e}")
    LoggingState.configured = False


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
    is_main_proc = current_process().name == "MainProcess" and discovery.get_rank() in (None, 0)

    if LoggingState.configured and not force:
        return

    # 1. Resolve Parameters
    cfg = load_config()

    def str_to_bool(v: Any) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.lower() in ("true", "1", "t", "y", "yes")
        return bool(v)

    def resolve(val: Any, env: str, key: str, default: Any) -> Any:
        return val if val is not None else (os.getenv(env) or cfg.get(key) or default)

    log_dir_val = resolve(log_dir, "LOGFLOW_DIR", "log_dir", "./logs")
    log_dir_path = Path(log_dir_val).expanduser().resolve()
    log_dir_path.mkdir(parents=True, exist_ok=True)

    f_level = str(resolve(file_level, "LOGFLOW_FILE_LEVEL", "file_level", "DEBUG")).upper()
    c_level = str(resolve(console_level, "LOGFLOW_CONSOLE_LEVEL", "console_level", "INFO")).upper()
    retention_val = int(resolve(retention, "LOGFLOW_RETENTION", "retention", 5))
    do_rotation = str_to_bool(resolve(rotation_on_startup, "LOGFLOW_ROTATION_ON_STARTUP", "rotation_on_startup", True))
    enqueue_val = str_to_bool(resolve(enqueue, "LOGFLOW_ENQUEUE", "enqueue", False))

    target_name = discovery.determine_script_name(resolve(script_name, "LOGFLOW_SCRIPT_NAME", "script_name", None))
    new_log_file = log_dir_path / f"{target_name}.log"

    # 2. PIVOT & ROTATION
    if is_main_proc:
        curr = LoggingState.log_file
        if curr and new_log_file.resolve() != curr.resolve():
            _perform_pivot(curr, new_log_file, do_rotation, retention_val)
        elif do_rotation and not LoggingState.configured and new_log_file.exists():
            _rotate(new_log_file, retention_val)

    # 3. Setup Sinks
    if not LoggingState.configured or force:
        logger.remove()

        if is_main_proc:
            fmt = (
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                "<level>{level: <8}</level> | "
                "{extra[rank_tag]}<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
                "<level>{message}</level>"
            )
            logger.add(sys.stderr, level=c_level, format=fmt, filter=_rank_filter, colorize=True)

        file_fmt = (
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | " "{extra[rank_tag]}{name}:{function}:{line} | {message}"
        )
        logger.add(
            str(new_log_file),
            level=f_level,
            format=file_fmt,
            filter=_rank_filter,
            enqueue=enqueue_val,
            mode="a",
        )

    was_cfg = LoggingState.configured
    LoggingState.log_file = new_log_file
    LoggingState.configured = True
    setup_interception()

    if is_main_proc:
        os.environ["LOGFLOW_SCRIPT_NAME"] = target_name

        all_logs = [f for f in log_dir_path.glob("*.log") if f.is_file() and f.resolve() != new_log_file.resolve()]
        _purge_old_files(all_logs, max(retention_val - 1, 0))

        logger.info(f"LogFlow {'Re-' if was_cfg else ''}initialized: {new_log_file.name}")


def shutdown_logging() -> None:
    try:
        logger.complete()
    except Exception as e:
        warnings.warn(f"LogFlow: Failed to complete logger during shutdown: {e}")


def get_logger(name: Optional[str] = None) -> "Logger":
    if not LoggingState.configured:
        configure_logging()
    return logger.bind(name=name) if name else logger
