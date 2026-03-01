import os
from pathlib import Path

from logflow import configure_logging, get_logger, shutdown_logging


def test_configure_and_log(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    configure_logging(log_dir=log_dir, script_name="test_run")

    logger = get_logger("test_module")
    logger.info("Test message")

    # Ensure file is created
    log_file = log_dir / "test_run.log"
    assert log_file.exists()

    shutdown_logging()

    content = log_file.read_text()
    assert "test_core" in content
    assert "Test message" in content


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
        # In a real test we'd check the internal state, but here we verify it runs
        # and create logs with correct params.
        logger = get_logger("env_test")
        logger.trace("Trace message")
        shutdown_logging()

        content = (log_dir / "env_over.log").read_text()
        assert "Trace message" in content
    finally:
        os.chdir(old_cwd)
        del os.environ["LOGFLOW_FILE_LEVEL"]


def test_configure_args_overrides_env(tmp_path: Path) -> None:
    log_dir = tmp_path / "arg_test"
    os.environ["LOGFLOW_FILE_LEVEL"] = "ERROR"
    try:
        # Args 'DEBUG' should win over Env 'ERROR'
        configure_logging(log_dir=log_dir, script_name="arg_over", file_level="DEBUG")
        logger = get_logger("arg_test")
        logger.debug("Debug message")
        shutdown_logging()

        content = (log_dir / "arg_over.log").read_text()
        assert "Debug message" in content
    finally:
        del os.environ["LOGFLOW_FILE_LEVEL"]


def test_configure_rank_non_zero(tmp_path: Path) -> None:
    log_dir = tmp_path / "rank_test"
    os.environ["RANK"] = "1"
    try:
        configure_logging(log_dir=log_dir, script_name="rank_one")
        logger = get_logger("rank_test")
        logger.info("Non-zero rank message")
        shutdown_logging()

        # Should still exist in file
        log_file = log_dir / "rank_one.log"
        assert "Non-zero rank message" in log_file.read_text()
        assert "[rank 1]" in log_file.read_text()
    finally:
        del os.environ["RANK"]


def test_configure_rank_mocked(tmp_path: Path) -> None:
    from unittest.mock import patch

    log_dir = tmp_path / "mock_rank"
    with patch("logflow.core.get_rank", return_value=10):
        configure_logging(log_dir=log_dir, script_name="mocked")
        logger = get_logger("mock_rank")
        logger.info("Mocked rank message")
        shutdown_logging()

        content = (log_dir / "mocked.log").read_text()
        assert "[rank 10]" in content


def test_shutdown_multiple_times() -> None:
    # Should not raise exception
    shutdown_logging()
    shutdown_logging()


def test_auto_configure(tmp_path: Path) -> None:
    from unittest.mock import patch

    import logflow.core

    # Reset global state for this test
    with patch("logflow.core._configured", False):
        with patch("logflow.core.configure_logging") as mock_conf:
            logflow.core.get_logger("auto")
            mock_conf.assert_called_once()


def test_rotation_failure(tmp_path: Path) -> None:
    from unittest.mock import patch

    log_dir = tmp_path / "rot_fail"
    log_dir.mkdir()
    log_file = log_dir / "app.log"
    log_file.write_text("old")

    with patch("pathlib.Path.rename", side_effect=OSError("Access denied")):
        # Should not crash, just log warning
        configure_logging(log_dir=log_dir, script_name="app")
        shutdown_logging()


def test_configure_no_rotation(tmp_path: Path) -> None:
    log_dir = tmp_path / "no_rotate"
    log_dir.mkdir()
    log_file = log_dir / "app.log"
    log_file.write_text("old")

    configure_logging(log_dir=log_dir, script_name="app", rotation_on_startup=False)
    logger = get_logger("no_rotate")
    logger.info("new")
    shutdown_logging()

    # Should append, not rotate
    content = log_file.read_text()
    assert "old" in content
    assert "new" in content


def test_startup_rotation(tmp_path: Path) -> None:
    log_dir = tmp_path / "rotation_test"
    log_dir.mkdir()
    log_file = log_dir / "rotate.log"
    log_file.write_text("old content")

    # Configure twice to trigger rotation
    configure_logging(log_dir=log_dir, script_name="rotate", rotation_on_startup=True)
    shutdown_logging()

    # Check that a rotated file exists
    rotated_files = list(log_dir.glob("rotate.*.log"))
    assert len(rotated_files) == 1
    assert rotated_files[0].read_text() == "old content"

    # New log should be empty or have new content
    assert log_file.exists()
    assert "old content" not in log_file.read_text()
