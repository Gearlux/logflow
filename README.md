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
