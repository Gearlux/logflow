import multiprocessing as mp
import os
from pathlib import Path

from logflow import configure_logging, get_logger, shutdown_logging


def worker(rank: int, log_dir: Path, script_name: str) -> None:
    os.environ["RANK"] = str(rank)
    # Signal that we are in a child so rotation doesn't happen again
    # In a real app this is inherited from parent's env
    os.environ["_LOGFLOW_ROTATED"] = "1"

    configure_logging(log_dir=log_dir, script_name=script_name)
    logger = get_logger(f"worker_{rank}")
    logger.info(f"Worker {rank} log message")
    shutdown_logging()


def test_multiprocess_safety(tmp_path: Path) -> None:
    log_dir = tmp_path / "mp_test"
    script_name = "mp_safety"

    # Initialize parent
    os.environ["_LOGFLOW_ROTATED"] = "0"
    configure_logging(log_dir=log_dir, script_name=script_name)
    main_logger = get_logger("main")
    main_logger.info("Main start")

    # Use 'spawn' context for consistent behavior on Linux, macOS, and Windows.
    # This avoids deadlocks with Loguru's background sink queue.
    ctx = mp.get_context("spawn")
    processes = []
    num_workers = 4
    for i in range(num_workers):
        p = ctx.Process(target=worker, args=(i, log_dir, script_name))
        p.start()
        processes.append(p)

    for p in processes:
        p.join(timeout=15)
        if p.is_alive():
            p.terminate()
            p.join()

    main_logger.info("Main end")
    shutdown_logging()

    # Verify results
    log_file = log_dir / f"{script_name}.log"
    assert log_file.exists()
    content = log_file.read_text()

    for i in range(num_workers):
        assert f"Worker {i} log message" in content

    assert "Main start" in content
    assert "Main end" in content
