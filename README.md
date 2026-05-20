# LogFlow

Modern, multiprocess-safe logging specifically engineered for High-Performance Computing (HPC) and Machine Learning (ML).

## Why LogFlow?
ML experiments and distributed training (like PyTorch DDP) present unique logging challenges:
- **Log Storms:** 128 identical lines when 128 GPUs log simultaneously.
- **Multiprocess Safety:** Corrupted log files when multiple processes write to the same file.
- **Startup Consistency:** Tracking which logs belong to which experiment run.

LogFlow solves these by being **distributed-aware** and **framework-agnostic**.

## Design Goals & Requirements

### Core Functionality
- **High-Fidelity Logging:** Provide a thread-safe and multiprocess-safe logging engine.
- **Unified Observability:** Standardize logging levels (TRACE, DEBUG, INFO, SUCCESS, WARNING, ERROR, CRITICAL).
- **Auto-Infrastructure:** Automatically create log directories if they do not exist.
- **Global Configuration:** Support XDG-standard configuration (~/.config/logflow/config.yaml).

### Integration
- **Log-Symmetry:** Support automatic log file naming based on the active script/config name.
- **Rich Integration:** Provide beautiful, filtered console output via the Rich library.
- **Framework Interception:** Intercept standard library logging and redirect to LogFlow.

### Performance
- **Zero-Overhead Inactive Levels:** Ensure that TRACE/DEBUG levels have minimal impact when disabled.
- **Asynchronous Sinks:** Support enqueued logging to prevent blocking the hot path.

## Key Features
- **Rank-Aware:** Automatically filters console output to Rank 0 (supports SLURM, DDP, MPI).
- **Multiprocess Safe:** Uses Loguru's `enqueue=True` for thread/process safety.
- **Startup Rotation:** Archives old logs on script start, giving every run a fresh log file.
- **Framework Interoperability:** Automatically intercepts and formats logs from **TensorFlow**, **PyTorch**, **JAX**, and standard Python `logging`.
- **Zero-Blocking:** Non-blocking logging via background sinking.

## Installation
```bash
pip install git+https://github.com/Gearlux/logflow.git@main
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

### 3. Per-logger, Per-sink Level Overrides

`file_level` / `console_level` set global thresholds for the file and console sinks. To override the threshold for specific loggers — and, optionally, only on one of the two sinks — use `module_levels`:

```yaml
file_level: "DEBUG"
console_level: "INFO"

module_levels:
  # Silence a chatty discovery logger on the file sink, in DataLoader workers only.
  # The main process still emits INFO so first-time discovery stays visible.
  "waivefront.rfuav.data.archive":
    file: WARNING
    workers_only: true

  # Quiet on screen, full detail on disk — promotes this logger below the global file_level.
  "noisy.lib.but.useful.in.debug":
    console: ERROR
    file: DEBUG
```

Rules:

- Keys match loguru's `record["name"]` (the calling module's dotted path) by **dotted-segment prefix**: `"pkg.sub"` matches `"pkg.sub"` and `"pkg.sub.mod"`, but **not** `"pkg.subway"`. `"foo"` does not match `"foobar.baz"`.
- On overlap, the **longest matching prefix wins**. YAML order is irrelevant.
- `console:` and `file:` are each optional; an omitted sink falls back to the global level for that logger.
- `workers_only: true` restricts the override to non-`MainProcess` processes (typically PyTorch DataLoader workers).
- Unknown sub-keys or invalid level strings raise `ValueError` at startup — no silent ignores.

See `logflow.example.yaml` for the full reference.

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
