import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

from loguru import logger

from logflow.config import load_config
from logflow.discovery import determine_script_name, get_rank
from logflow.intercept import setup_interception

# Global state to prevent redundant configuration
_configured = False
_log_file: Optional[Path] = None


def configure_logging(
    log_dir: Optional[Union[str, Path]] = None,
    script_name: Optional[str] = None,
    file_level: Optional[str] = None,
    console_level: Optional[str] = None,
    rotation_on_startup: Optional[bool] = None,
    retention: Optional[int] = None,
    enqueue: Optional[bool] = None,
) -> None:
    """
    Configure the global LogFlow system.
    Configuration priority: function args > env vars > file config > defaults.
    """
    global _configured, _log_file

    # 1. Load configuration from files (lowest priority)
    file_cfg = load_config()

    # 2. Merge with defaults and environment variables
    # Values are resolved in order: Args -> Env -> Config File -> Default
    log_dir_val = log_dir or os.getenv("LOGFLOW_DIR") or file_cfg.get("log_dir") or "./logs"

    script_name = script_name or os.getenv("LOGFLOW_SCRIPT_NAME") or file_cfg.get("script_name")

    file_level_val = file_level or os.getenv("LOGFLOW_FILE_LEVEL") or file_cfg.get("file_level") or "DEBUG"

    console_level_val = console_level or os.getenv("LOGFLOW_CONSOLE_LEVEL") or file_cfg.get("console_level") or "INFO"

    rotation_on_startup_val = (
        rotation_on_startup
        if rotation_on_startup is not None
        else (
            os.getenv("LOGFLOW_STARTUP_ROTATION", "").lower() == "true"
            if os.getenv("LOGFLOW_STARTUP_ROTATION")
            else file_cfg.get("rotation_on_startup", True)
        )
    )

    retention_val = (
        retention
        or (int(os.getenv("LOGFLOW_RETENTION")) if os.getenv("LOGFLOW_RETENTION") else None)
        or file_cfg.get("retention")
        or 5
    )

    enqueue_val = (
        enqueue
        if enqueue is not None
        else (
            os.getenv("LOGFLOW_ENQUEUE", "").lower() == "true"
            if os.getenv("LOGFLOW_ENQUEUE")
            else file_cfg.get("enqueue", True)
        )
    )

    # Basic setup
    log_dir_path = Path(log_dir_val)
    log_dir_path.mkdir(parents=True, exist_ok=True)

    # Determine script name and rank
    script_name = determine_script_name(script_name)
    rank = get_rank()
    is_rank_zero = rank is None or rank == 0

    # Multiprocessing awareness
    from multiprocessing import current_process

    is_main_process = current_process().name == "MainProcess"
    has_rotated = os.getenv("_LOGFLOW_ROTATED") == "1"

    # Remove default Loguru handler
    logger.remove()

    # 1. Console Handler (Filtered to Rank 0 by default)
    if is_rank_zero:
        rank_fmt = "" if rank is None else f"<yellow>[rank {rank}]</yellow> | "
        console_format = (
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            f"{rank_fmt}"
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        )
        logger.add(
            sys.stderr,
            level=console_level_val.upper(),
            format=console_format,
            colorize=True,
            enqueue=enqueue_val,
        )

    # 2. File Handler
    _log_file = log_dir_path / f"{script_name}.log"

    # Handle Startup Rotation (Only on absolute Main Process at Rank 0)
    if rotation_on_startup_val and is_main_process and is_rank_zero and not has_rotated and _log_file.exists():
        try:
            mtime = _log_file.stat().st_mtime
            ts = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d_%H-%M-%S")
            archive_path = _log_file.parent / f"{_log_file.stem}.{ts}{_log_file.suffix}"
            _log_file.rename(archive_path)

            # Retention cleanup
            archives = sorted(
                _log_file.parent.glob(f"{_log_file.stem}.*.*{_log_file.suffix}"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for old in archives[retention_val:]:
                old.unlink()

            # Signal to all future children that rotation is done
            os.environ["_LOGFLOW_ROTATED"] = "1"
        except Exception as e:
            logger.warning(f"Startup rotation failed: {e}")

    # If we are a child and rotation was already done, ensure we don't do it again
    if not is_main_process:
        os.environ["_LOGFLOW_ROTATED"] = "1"

    rank_seg = "" if rank is None else f"[rank {rank}] | "
    file_format = (
        "{time:YYYY-MM-DD HH:mm:ss.SSS} | " "{level: <8} | " f"{rank_seg}" "{name}:{function}:{line} | " "{message}"
    )

    logger.add(
        str(_log_file),
        level=file_level_val.upper(),
        format=file_format,
        enqueue=enqueue_val,
        rotation="10 MB",  # Built-in size rotation
        retention=retention_val,
        backtrace=True,
        diagnose=True,
    )

    # 3. Intercept framework logs
    setup_interception()

    _configured = True
    if is_rank_zero:
        logger.info(f"LogFlow initialized (Rank: {rank if rank is not None else 'N/A'})")


def shutdown_logging() -> None:
    """
    Ensure all queued log messages are processed and all sinks are closed.
    Call this before the main script exits to ensure no logs are lost.
    """
    try:
        logger.complete()
    except Exception:
        pass


def get_logger(name: Optional[str] = None) -> Any:
    """
    Get a logger instance bound to the given name.
    """
    if not _configured:
        # Auto-configure with defaults if not explicitly called
        configure_logging()

    return logger.bind(name=name) if name else logger
