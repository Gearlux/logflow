import logging
import warnings
from pathlib import Path

from logflow import configure_logging, shutdown_logging


def test_intercept_logging(tmp_path: Path) -> None:
    log_dir = tmp_path / "intercept_logs"
    configure_logging(log_dir=log_dir, script_name="intercept")

    # Use standard logging
    std_logger = logging.getLogger("standard_lib")
    std_logger.error("Standard logging message")

    shutdown_logging()

    log_file = log_dir / "intercept.log"
    content = log_file.read_text()
    assert "Standard logging message" in content


def test_intercept_exception(tmp_path: Path) -> None:
    log_dir = tmp_path / "exception_logs"
    configure_logging(log_dir=log_dir, script_name="exception")

    std_logger = logging.getLogger("exception_lib")
    try:
        raise ValueError("Intercepted error")
    except ValueError:
        std_logger.exception("An error occurred")

    shutdown_logging()

    log_file = log_dir / "exception.log"
    content = log_file.read_text()
    assert "An error occurred" in content
    assert "ValueError: Intercepted error" in content


def test_intercept_unknown_level(tmp_path: Path) -> None:
    log_dir = tmp_path / "unknown_level_logs"
    configure_logging(log_dir=log_dir, script_name="unknown")

    # Manually emit a record with an unknown level
    record = logging.LogRecord(
        name="test",
        level=99,  # Unknown level
        pathname="test.py",
        lineno=1,
        msg="Unknown level message",
        args=None,
        exc_info=None,
    )
    from logflow.intercept import InterceptHandler

    handler = InterceptHandler()
    handler.emit(record)

    shutdown_logging()

    log_file = log_dir / "unknown.log"
    content = log_file.read_text()
    assert "Unknown level message" in content


def test_intercept_warnings(tmp_path: Path) -> None:
    log_dir = tmp_path / "warning_logs"
    configure_logging(log_dir=log_dir, script_name="warnings")

    # Trigger a python warning
    warnings.warn("Custom warning message", UserWarning)

    shutdown_logging()

    log_file = log_dir / "warnings.log"
    content = log_file.read_text()
    assert "Custom warning message" in content
    assert "UserWarning" in content
