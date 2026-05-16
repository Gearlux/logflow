# LogFlow Mandates

- **Rank-Zero Console:** In distributed environments, console output MUST be filtered to Rank 0 only. File logging captures all ranks with rank tags.
- **Multiprocess Safety:** All sinks MUST use Loguru's `enqueue=True` whenever multiple processes will write. The underlying `multiprocessing.SimpleQueue` is created **lazily** — deferred until something actually forks or spawns a child — so a request for `enqueue=True` does not allocate a POSIX semaphore in single-process runs. Hooks fire in `os.register_at_fork(before=...)` and a one-shot `multiprocessing.process.BaseProcess.__init__` patch. Set `LOGFLOW_EAGER_ENQUEUE=true` to force allocation at handler-creation time (rare; needed only when something bypasses both hook surfaces).
- **Startup Rotation:** Log files MUST be archived with timestamps on script start. Only the main rank/process performs rotation to prevent race conditions.
- **Framework Interception:** Standard Python `logging`, TensorFlow, PyTorch, and JAX logs MUST be automatically intercepted and routed through LogFlow.
- **Zero-Blocking:** Logging MUST never block the training critical path. Background sinking is mandatory.
- **Configuration Hierarchy:** Resolution order: function args > env vars (`LOGFLOW_`) > local YAML > local pyproject.toml > XDG global config > defaults. Never violate this precedence.

## Testing & Validation
- **No Sleep Loops:** NEVER use `time.sleep()` for synchronization. Use `logger.complete()`, `join()`, or `close()`.
- **Environment Isolation:** Tests MUST mock HOME and XDG_CONFIG_HOME. Always call `_reset_state()` between tests.
- **Line Length:** 120 characters (Black, isort, flake8).
