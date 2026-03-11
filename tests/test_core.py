import os
import time
from pathlib import Path
from typing import Any

from logflow.core import configure_logging, get_logger, shutdown_logging


def test_configure_default(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    script_name = "test_app"

    configure_logging(log_dir=log_dir, script_name=script_name)

    test_logger = get_logger("test")
    test_logger.info("Test message")
    shutdown_logging()

    log_file = log_dir / f"{script_name}.log"
    assert log_file.exists()
    assert "Test message" in log_file.read_text()


def test_configure_env_overrides_file(tmp_path: Path) -> None:
    log_dir = tmp_path / "env_test"
    # Create config file
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[tool.logflow]\nfile_level = 'INFO'")

    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    os.environ["LOGFLOW_FILE_LEVEL"] = "TRACE"
    try:
        configure_logging(log_dir=log_dir, script_name="env_over")
        test_logger = get_logger("env_test")
        test_logger.trace("Trace message")
        shutdown_logging()

        # Check the actual file created
        log_file = log_dir / "env_over.log"
        assert log_file.exists()
        assert "Trace message" in log_file.read_text()
    finally:
        os.chdir(old_cwd)
        del os.environ["LOGFLOW_FILE_LEVEL"]


def test_configure_args_overrides_env(tmp_path: Path) -> None:
    log_dir = tmp_path / "arg_test"
    os.environ["LOGFLOW_FILE_LEVEL"] = "INFO"
    try:
        # Pass TRACE via argument
        configure_logging(log_dir=log_dir, script_name="arg_over", file_level="TRACE")
        test_logger = get_logger("arg_test")
        test_logger.trace("Trace message from arg")
        shutdown_logging()

        log_file = log_dir / "arg_over.log"
        assert log_file.exists()
        assert "Trace message from arg" in log_file.read_text()
    finally:
        del os.environ["LOGFLOW_FILE_LEVEL"]


def test_configure_rank_non_zero(tmp_path: Path) -> None:
    log_dir = tmp_path / "rank_test"
    os.environ["RANK"] = "1"
    try:
        configure_logging(log_dir=log_dir, script_name="rank_app")
        test_logger = get_logger("rank")
        test_logger.info("Rank 1 message")
        shutdown_logging()

        log_file = log_dir / "rank_app.log"
        assert log_file.exists()
        content = log_file.read_text()
        assert "Rank 1 message" in content
        assert "[rank 1]" in content
    finally:
        del os.environ["RANK"]


def test_configure_rank_mocked(tmp_path: Path, monkeypatch: Any) -> None:
    log_dir = tmp_path / "mock_rank"
    # Mock get_rank to return 2
    import logflow.discovery

    monkeypatch.setattr(logflow.discovery, "get_rank", lambda: 2)

    configure_logging(log_dir=log_dir, script_name="mocked")
    test_logger = get_logger("test")
    test_logger.info("Mocked rank message")
    shutdown_logging()

    log_file = log_dir / "mocked.log"
    assert log_file.exists()
    content = log_file.read_text()
    assert "Mocked rank message" in content
    assert "[rank 2]" in content


def test_configure_no_rotation(tmp_path: Path) -> None:
    log_dir = tmp_path / "no_rotate"
    log_dir.mkdir()
    log_file = log_dir / "app.log"
    log_file.write_text("old\n")

    # Wait a bit so mtime is different if needed
    time.sleep(0.1)

    # Initial config (this will clobber or append depending on mode)
    # Since it's the first config in this process, it might rotate if rotation_on_startup is True
    configure_logging(log_dir=log_dir, script_name="app", rotation_on_startup=False)
    test_logger = get_logger("no_rotate")
    test_logger.info("new")
    shutdown_logging()

    content = log_file.read_text()
    assert "old" in content
    assert "new" in content


def test_startup_rotation(tmp_path: Path) -> None:
    log_dir = tmp_path / "rotation_test"
    log_dir.mkdir()
    log_file = log_dir / "rotate.log"
    log_file.write_text("old content")

    # Small sleep to ensure mtime is distinct
    time.sleep(0.1)

    # First configuration: should rotate the existing file
    configure_logging(log_dir=log_dir, script_name="rotate", rotation_on_startup=True)
    get_logger().info("new content")
    shutdown_logging()

    # Check that a rotated file exists
    rotated_files = list(log_dir.glob("rotate.*.log"))
    assert len(rotated_files) == 1
    assert "old content" in rotated_files[0].read_text()
    assert "new content" in (log_dir / "rotate.log").read_text()
