import os
from typing import Any, Generator

import pytest
from loguru import logger

import logflow.core


@pytest.fixture(autouse=True)
def global_reset_logflow(tmp_path: Any, monkeypatch: Any) -> Generator[None, None, None]:
    """Nuclear reset of all LogFlow state and Environment between tests."""
    # 1. Isolate HOME so global config (~/.config/logflow/) is never found
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    # 2. Clear environment state
    for k in list(os.environ.keys()):
        if k.startswith("LOGFLOW_") or k.startswith("_LOGFLOW_"):
            os.environ.pop(k)

    # 3. Clear MPI/DDP vars that might interfere
    for k in ("RANK", "LOCAL_RANK", "NODE_RANK", "GROUP_RANK", "SLURM_PROCID"):
        os.environ.pop(k, None)

    # 4. Reset core state pointers
    logflow.core._reset_state()

    # 5. Purge Loguru
    logger.remove()

    yield

    # Cleanup after
    logflow.core._reset_state()
    for k in list(os.environ.keys()):
        if k.startswith("LOGFLOW_") or k.startswith("_LOGFLOW_"):
            os.environ.pop(k)
