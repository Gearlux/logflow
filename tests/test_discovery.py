import os
from logflow.discovery import get_rank, determine_script_name

def test_get_rank_none():
    # Ensure rank is None when no env vars are set
    if "RANK" in os.environ: del os.environ["RANK"]
    if "SLURM_PROCID" in os.environ: del os.environ["SLURM_PROCID"]
    if "LOCAL_RANK" in os.environ: del os.environ["LOCAL_RANK"]
    assert get_rank() is None

def test_get_rank_torchrun():
    os.environ["RANK"] = "3"
    assert get_rank() == 3
    del os.environ["RANK"]

def test_get_rank_slurm():
    os.environ["SLURM_PROCID"] = "5"
    assert get_rank() == 5
    del os.environ["SLURM_PROCID"]

def test_determine_script_name_explicit():
    assert determine_script_name("custom_name") == "custom_name"

def test_determine_script_name_env():
    os.environ["LOGFLOW_SCRIPT_NAME"] = "env_name"
    assert determine_script_name() == "env_name"
    del os.environ["LOGFLOW_SCRIPT_NAME"]
