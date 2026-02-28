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
