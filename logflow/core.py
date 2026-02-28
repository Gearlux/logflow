import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

from loguru import logger

from logflow.discovery import determine_script_name, get_rank
from logflow.intercept import setup_interception

# Global state to prevent redundant configuration
_configured = False
_log_file: Optional[Path] = None


def configure_logging(
    log_dir: Optional[Union[str, Path]] = None,
    script_name: Optional[str] = None,
    file_level: str = "DEBUG",
    console_level: str = "INFO",
    rotation_on_startup: bool = True,
    retention: int = 5,
    enqueue: bool = True,
) -> None:
    """
    Configure the global LogFlow system.

    Args:
        log_dir: Directory for log files. Defaults to './logs'.
        script_name: Base name for log files. Auto-detected if None.
        file_level: Minimum level for file logging.
        console_level: Minimum level for console logging.
        rotation_on_startup: If True, archives existing logs on startup.
        retention: Number of archived logs to keep.
        enqueue: If True, uses a background process for logging (recommended for MP).
    """
    global _configured, _log_file

    # Basic setup
    log_dir_path = Path(log_dir) if log_dir else Path(os.getenv("LOGFLOW_DIR", "./logs"))
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
            level=console_level.upper(),
            format=console_format,
            colorize=True,
            enqueue=enqueue,
        )

    # 2. File Handler
    _log_file = log_dir_path / f"{script_name}.log"

    # Handle Startup Rotation (Only on absolute Main Process at Rank 0)
    if rotation_on_startup and is_main_process and is_rank_zero and not has_rotated and _log_file.exists():
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
            for old in archives[retention:]:
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
        level=file_level.upper(),
        format=file_format,
        enqueue=enqueue,
        rotation="10 MB",  # Built-in size rotation
        retention=retention,
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
