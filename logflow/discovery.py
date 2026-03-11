import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Optional


@lru_cache(maxsize=1)
def get_rank() -> Optional[int]:
    """
    Detect the rank of the current process in a distributed environment.
    Supports PyTorch DDP (torchrun), SLURM, and MPI.

    Returns:
        The global rank as an integer, or None if not in a distributed environment.
    """
    # 1. PyTorch DDP / torchrun
    for var in ("RANK", "SLURM_PROCID"):
        val = os.environ.get(var)
        if val is not None:
            try:
                return int(val)
            except ValueError:
                pass

    # 2. Lightning / Generic DDP (Local + Node Rank)
    local_rank = os.environ.get("LOCAL_RANK")
    if local_rank is not None:
        try:
            node_rank = int(os.environ.get("NODE_RANK", os.environ.get("GROUP_RANK", "0")))
            lr = int(local_rank)
            # Best effort global rank calculation
            device_count = int(os.environ.get("LOCAL_WORLD_SIZE", "1"))
            return node_rank * device_count + lr
        except ValueError:
            pass

    return None


def determine_script_name(explicit: Optional[str] = None) -> str:
    """
    Determine a sensible name for the log file based on execution context.
    """
    if explicit:
        return explicit

    # Check env var for consistency across processes
    env_name = os.getenv("LOGFLOW_SCRIPT_NAME")
    if env_name:
        return env_name

    # Try to infer from __main__
    main_module = sys.modules.get("__main__")
    if main_module and hasattr(main_module, "__file__") and main_module.__file__:
        path = Path(main_module.__file__)
        if path.name == "__main__.py":
            # If package run, use parent folder name
            return path.parent.name or "app"
        return path.stem

    # Fallback to sys.argv[0] if it's not a flag
    if sys.argv and sys.argv[0] and not sys.argv[0].startswith("-"):
        return Path(sys.argv[0]).stem

    return "app"
