# LogFlow

Modern, multiprocess-safe logging specifically engineered for High-Performance Computing (HPC) and Machine Learning (ML).

## Why LogFlow?
ML experiments and distributed training (like PyTorch DDP) present unique logging challenges:
- **Log Storms:** 128 identical lines when 128 GPUs log simultaneously.
- **Multiprocess Safety:** Corrupted log files when multiple processes write to the same file.
- **Startup Consistency:** Tracking which logs belong to which experiment run.

LogFlow solves these by being **distributed-aware** and **framework-agnostic**.

## Key Features
- **Rank-Aware:** Automatically filters console output to Rank 0 (supports SLURM, DDP, MPI).
- **Multiprocess Safe:** Uses Loguru's `enqueue=True` for thread/process safety.
- **Startup Rotation:** Archives old logs on script start, giving every run a fresh log file.
- **Framework Interoperability:** Automatically intercepts and formats logs from **TensorFlow**, **PyTorch**, **JAX**, and standard Python `logging`.
- **Zero-Blocking:** Non-blocking logging via background sinking.

## Installation
```bash
pip install logflow
```

## Quick Start
```python
from logflow import get_logger, configure_logging

# Optional: customize levels and directories
configure_logging(log_dir="./experiment_logs", console_level="INFO")

logger = get_logger(__name__)

logger.info("Starting training loop...")
logger.debug("Hyperparameters: batch_size=32, lr=0.001")
logger.success("Model checkpoint saved!")
```

## Configuration
LogFlow supports a hierarchical configuration system that allows you to manage settings across different projects and environments.

### 1. Configuration Priority
Settings are resolved in the following order (highest to lowest):
1.  **Function Arguments** (passed to `configure_logging()`)
2.  **Environment Variables** (prefixed with `LOGFLOW_`)
3.  **Local `logflow.yaml` / `logflow.yml`**
4.  **Local `pyproject.toml`** (under `[tool.logflow]`)
5.  **XDG User Config** (`~/.config/logflow/config.yaml`)
6.  **Defaults**

### 2. Usage Examples

#### via `pyproject.toml`
```toml
[tool.logflow]
log_dir = "./custom_logs"
console_level = "DEBUG"
retention = 10
```

#### via `logflow.yaml`
```yaml
log_dir: "./experiment_logs"
file_level: "TRACE"
enqueue: true
rotation_on_startup: true
```

#### via Environment Variables
```bash
export LOGFLOW_DIR="/var/log/myapp"
export LOGFLOW_CONSOLE_LEVEL="ERROR"
```

## Log Inspection
For the best experience viewing LogFlow logs (especially interleaving logs from multiple ranks/workers), we recommend using **[lnav](https://lnav.org/)** (The Log File Navigator).

`lnav` automatically detects LogFlow's timestamp format and can merge multiple log files into a single, chronological view.

### Usage with lnav
```bash
# View all logs in the directory interleaved by time
lnav ./logs
```

For more information, see the **[lnav documentation](https://docs.lnav.org/)**.

## Distributed Training (DDP/SLURM)
LogFlow handles ranks automatically. No need to wrap your log calls in `if rank == 0:`.
```python
# In a torchrun or SLURM environment
from logflow import get_logger

logger = get_logger(__name__)

# Only shows up once in console (Rank 0), but saved in file for all Ranks
logger.info("Initializing process group...")
```

## License
MIT
