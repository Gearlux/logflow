import os

from logflow.discovery import determine_script_name, get_rank


def test_get_rank_none() -> None:
    # Ensure rank is None when no env vars are set
    if "RANK" in os.environ:
        del os.environ["RANK"]
    if "SLURM_PROCID" in os.environ:
        del os.environ["SLURM_PROCID"]
    if "LOCAL_RANK" in os.environ:
        del os.environ["LOCAL_RANK"]
    assert get_rank() is None


def test_get_rank_torchrun() -> None:
    os.environ["RANK"] = "3"
    assert get_rank() == 3
    del os.environ["RANK"]


def test_get_rank_slurm() -> None:
    os.environ["SLURM_PROCID"] = "5"
    assert get_rank() == 5
    del os.environ["SLURM_PROCID"]


def test_determine_script_name_explicit() -> None:
    assert determine_script_name("custom_name") == "custom_name"


def test_determine_script_name_env() -> None:
    os.environ["LOGFLOW_SCRIPT_NAME"] = "env_name"
    assert determine_script_name() == "env_name"
    del os.environ["LOGFLOW_SCRIPT_NAME"]
