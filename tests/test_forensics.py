import os
import time
from pathlib import Path

import logflow.core


def test_pivot_and_rotate_handoff(tmp_path: Path) -> None:
    """
    Verify Pattern:
    1. Start with wf.log
    2. Log bootstrap
    3. Handoff to convert.log
    4. wf.log should be gone, convert.log should have bootstrap
    """
    log_dir = tmp_path / "logs"

    # 1. Initial config (Simulate wf start)
    # We must use logflow.core.configure_logging after the reload
    logflow.core.configure_logging(log_dir=log_dir, script_name="wf", force=True)
    test_logger = logflow.core.get_logger("bootstrap")
    test_logger.info("BOOTSTRAP START")

    wf_log = log_dir / "wf.log"
    assert wf_log.exists()

    # 2. Handoff (Simulate convert command)
    logflow.core.configure_logging(log_dir=log_dir, script_name="convert", force=True)
    test_logger.info("CONVERT START")

    convert_log = log_dir / "convert.log"
    assert convert_log.exists()
    assert not wf_log.exists(), "wf.log should have been pivoted (renamed) to convert.log"

    # 3. Check content
    content = convert_log.read_text()
    assert "BOOTSTRAP START" in content
    assert "CONVERT START" in content


def test_retention_enforcement(tmp_path: Path) -> None:
    """
    Verify that only the requested number of files are kept,
    even when we manually rotate.
    """
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    for i in range(5):
        p = log_dir / f"test.{i}.log"
        p.write_text(f"old log {i}")
        os.utime(p, (time.time() - (100 - i), time.time() - (100 - i)))

    logflow.core.configure_logging(log_dir=log_dir, script_name="test", retention=2, force=True)

    remaining_files = list(log_dir.glob("*.log"))
    assert len(remaining_files) <= 2


def test_retention_decrease_cleanup(tmp_path: Path) -> None:
    """
    Verify that if retention goes from 5 to 2, older files are purged.
    """
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    for i in range(5):
        p = log_dir / f"old_run_{i}.log"
        p.write_text(f"Log {i}")
        os.utime(p, (time.time() - (100 - i), time.time() - (100 - i)))

    assert len(list(log_dir.glob("*.log"))) == 5

    logflow.core.configure_logging(log_dir=log_dir, script_name="final_run", retention=2, force=True)

    remaining = list(log_dir.glob("*.log"))
    assert len(remaining) <= 2
