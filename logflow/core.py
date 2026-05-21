import os
import re
import shutil
import sys
import warnings
from dataclasses import dataclass
from datetime import datetime
from multiprocessing import current_process
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Literal, Optional, Union

from loguru import logger

if TYPE_CHECKING:
    from loguru import Logger

from logflow import discovery
from logflow.config import load_config
from logflow.intercept import setup_interception


class LoggingState:
    """Singleton state management for LogFlow."""

    configured: bool = False
    log_file: Optional[Path] = None
    # Lazy-enqueue bookkeeping — keep the params for the file sink so we can
    # re-add it with enqueue=True the first time multiprocess activity is
    # detected. Avoids paying the POSIX-semaphore cost in single-process runs.
    file_sink_id: Optional[int] = None
    file_sink_params: Optional[dict] = None
    enqueue_active: bool = False
    enqueue_requested: bool = False

    @classmethod
    def reset(cls) -> None:
        cls.configured = False
        cls.log_file = None
        cls.file_sink_id = None
        cls.file_sink_params = None
        cls.enqueue_active = False
        cls.enqueue_requested = False
        logger.remove()
        if hasattr(discovery.get_rank, "cache_clear"):
            discovery.get_rank.cache_clear()


def _upgrade_to_enqueue() -> None:
    """Swap the file sink to ``enqueue=True``. Idempotent.

    Called the first time the parent process is about to fork or spawn a
    child. Allocating the multiprocessing queue here (instead of at handler
    creation) avoids the POSIX semaphore cost — and on macOS the kernel-wide
    semaphore-table exhaustion — for single-process runs.
    """
    if LoggingState.enqueue_active:
        return
    if not LoggingState.enqueue_requested:
        return
    if LoggingState.file_sink_id is None or LoggingState.file_sink_params is None:
        return
    try:
        logger.remove(LoggingState.file_sink_id)
    except ValueError:
        pass  # already removed by an external caller
    params: Any = dict(LoggingState.file_sink_params)
    params["enqueue"] = True
    LoggingState.file_sink_id = logger.add(**params)
    LoggingState.enqueue_active = True


def _install_lazy_enqueue_hooks() -> None:
    """Install one-time fork + spawn hooks that trigger ``_upgrade_to_enqueue``.

    The fork hook is wired via :func:`os.register_at_fork`; the spawn hook is
    a one-shot monkey-patch of ``multiprocessing.process.BaseProcess.__init__``
    so the queue exists in the parent before the spawn pickles parent state.
    Both are idempotent and process-local.
    """
    if getattr(_install_lazy_enqueue_hooks, "_installed", False):
        return

    try:
        os.register_at_fork(before=_upgrade_to_enqueue)
    except (AttributeError, RuntimeError):  # pragma: no cover - platform-dep
        pass

    import multiprocessing.process as _mp_process

    if not getattr(_mp_process.BaseProcess.__init__, "_logflow_patched", False):
        _orig_init = _mp_process.BaseProcess.__init__

        def _patched_init(self: Any, *args: Any, **kwargs: Any) -> None:
            _upgrade_to_enqueue()
            _orig_init(self, *args, **kwargs)

        _patched_init._logflow_patched = True  # type: ignore[attr-defined]
        _mp_process.BaseProcess.__init__ = _patched_init  # type: ignore[method-assign]

    _install_lazy_enqueue_hooks._installed = True  # type: ignore[attr-defined]


# --- Per-logger, per-sink level overrides -----------------------------------

_VALID_RULE_KEYS = {"console", "file", "workers_only"}


@dataclass(frozen=True)
class ModuleLevelRule:
    """A parsed `module_levels` entry.

    `console_no` / `file_no` are loguru level numbers (`logger.level(name).no`)
    or `None` to defer to the sink's global level. `workers_only=True` restricts
    the rule to non-MainProcess processes (e.g. DataLoader workers).
    """

    prefix: str
    console_no: Optional[int]
    file_no: Optional[int]
    workers_only: bool


def _level_no(level: str, where: str) -> int:
    try:
        return int(logger.level(level.upper()).no)
    except (ValueError, TypeError) as e:
        raise ValueError(f"module_levels: invalid level '{level}' for {where}") from e


def _parse_module_levels(cfg: Dict[str, Any]) -> List[ModuleLevelRule]:
    """Parse and validate the optional ``module_levels`` config block.

    Fails fast on unknown sub-keys or invalid levels — silent ignores are
    exactly how this feature rotted unimplemented for so long.
    """
    raw = cfg.get("module_levels")
    if raw is None:
        return []
    if not isinstance(raw, dict):
        raise ValueError(f"module_levels: expected a mapping, got {type(raw).__name__}")

    rules: List[ModuleLevelRule] = []
    for prefix, entry in raw.items():
        if not isinstance(prefix, str) or not prefix:
            raise ValueError(
                f"module_levels: prefix keys must be non-empty strings, got {prefix!r}"
            )
        if not isinstance(entry, dict):
            raise ValueError(
                f"module_levels[{prefix!r}]: expected a mapping with keys {sorted(_VALID_RULE_KEYS)}, "
                f"got {type(entry).__name__}"
            )
        unknown = set(entry.keys()) - _VALID_RULE_KEYS
        if unknown:
            raise ValueError(
                f"module_levels[{prefix!r}]: unknown sub-key(s) {sorted(unknown)}; "
                f"valid keys are {sorted(_VALID_RULE_KEYS)}"
            )
        c = entry.get("console")
        f = entry.get("file")
        if c is None and f is None:
            raise ValueError(
                f"module_levels[{prefix!r}]: must set at least one of 'console' or 'file'"
            )
        workers_only = entry.get("workers_only", False)
        if not isinstance(workers_only, bool):
            raise ValueError(
                f"module_levels[{prefix!r}].workers_only: expected bool, got {type(workers_only).__name__}"
            )
        rules.append(
            ModuleLevelRule(
                prefix=prefix,
                console_no=(
                    _level_no(c, f"module_levels[{prefix!r}].console")
                    if c is not None
                    else None
                ),
                file_no=(
                    _level_no(f, f"module_levels[{prefix!r}].file")
                    if f is not None
                    else None
                ),
                workers_only=workers_only,
            )
        )

    # Longest prefix first → first-match wins gives most-specific match.
    rules.sort(key=lambda r: len(r.prefix), reverse=True)
    return rules


def _make_sink_filter(
    sink: Literal["console", "file"],
    global_no: int,
    rules: List[ModuleLevelRule],
) -> Callable[[Any], bool]:
    """Build a loguru `filter=` callable that gates records by per-logger threshold.

    Also tags `record["extra"]["rank_tag"]` (used by both sinks' format strings).
    """

    def _filter(record: Any) -> bool:
        r = discovery.get_rank()
        record["extra"]["rank_tag"] = f"[rank {r}] | " if r and r > 0 else ""

        threshold = global_no
        if rules:
            name = record["name"] or ""
            in_worker = current_process().name != "MainProcess"
            for rule in rules:
                if rule.workers_only and not in_worker:
                    continue
                if name == rule.prefix or name.startswith(rule.prefix + "."):
                    override = rule.console_no if sink == "console" else rule.file_no
                    if override is not None:
                        threshold = override
                    break
        return bool(record["level"].no >= threshold)

    return _filter


def _purge_old_files(candidates: List[Path], keep: int) -> None:
    """Keep the `keep` most recent files by mtime, delete the rest."""
    by_age = sorted(candidates, key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
    for old in by_age[keep:]:
        try:
            old.unlink()
        except Exception as e:
            warnings.warn(f"LogFlow: Failed to purge old log file {old}: {e}")


def _rotate(path: Path, retention: int = 5) -> None:
    """Manual rotation of an existing log file (Main process only)."""
    if (
        not path.exists()
        or path.stat().st_size == 0
        or discovery.get_rank() not in (None, 0)
    ):
        return

    timestamp = datetime.fromtimestamp(path.stat().st_mtime).strftime(
        "%Y-%m-%d_%H-%M-%S"
    )
    rotated_path = path.parent / f"{path.stem}.{timestamp}{path.suffix}"

    try:
        path.rename(rotated_path)
        pattern = (
            re.escape(path.stem)
            + r"\.\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}"
            + re.escape(path.suffix)
        )
        candidates = [
            p
            for p in path.parent.iterdir()
            if p.is_file() and re.fullmatch(pattern, p.name)
        ]
        _purge_old_files(candidates, retention)
    except Exception as e:
        warnings.warn(f"LogFlow: Failed to rotate log file {path}: {e}")


def _perform_pivot(
    current_log: Path, new_log: Path, do_rotation: bool, retention: int
) -> None:
    """Transition from an interim log file to a final target file."""
    logger.remove()
    try:
        logger.complete()
    except Exception as e:
        warnings.warn(f"LogFlow: Failed to complete logger during pivot: {e}")

    if do_rotation:
        _rotate(new_log, retention)

    if current_log.exists():
        try:
            shutil.copy2(current_log, new_log)
            current_log.unlink()
        except Exception as e:
            warnings.warn(
                f"LogFlow: Failed to pivot logs from {current_log} to {new_log}: {e}"
            )
    LoggingState.configured = False


def configure_logging(
    log_dir: Optional[Union[str, Path]] = None,
    script_name: Optional[str] = None,
    file_level: Optional[str] = None,
    console_level: Optional[str] = None,
    rotation_on_startup: Optional[bool] = None,
    retention: Optional[int] = None,
    enqueue: Optional[bool] = None,
    force: bool = False,
) -> None:
    """
    Configure the global LogFlow system with Atomic Pivot support.
    """
    is_main_proc = current_process().name == "MainProcess" and discovery.get_rank() in (
        None,
        0,
    )

    if LoggingState.configured and not force:
        return

    # 1. Resolve Parameters
    cfg = load_config()

    def str_to_bool(v: Any) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.lower() in ("true", "1", "t", "y", "yes")
        return bool(v)

    def resolve(val: Any, env: str, key: str, default: Any) -> Any:
        return val if val is not None else (os.getenv(env) or cfg.get(key) or default)

    log_dir_val = resolve(log_dir, "LOGFLOW_DIR", "log_dir", "./logs")
    log_dir_path = Path(log_dir_val).expanduser().resolve()
    log_dir_path.mkdir(parents=True, exist_ok=True)

    f_level = str(
        resolve(file_level, "LOGFLOW_FILE_LEVEL", "file_level", "DEBUG")
    ).upper()
    c_level = str(
        resolve(console_level, "LOGFLOW_CONSOLE_LEVEL", "console_level", "INFO")
    ).upper()
    f_no = _level_no(f_level, "file_level")
    c_no = _level_no(c_level, "console_level")
    module_rules = _parse_module_levels(cfg)
    retention_val = int(resolve(retention, "LOGFLOW_RETENTION", "retention", 5))
    do_rotation = str_to_bool(
        resolve(
            rotation_on_startup,
            "LOGFLOW_ROTATION_ON_STARTUP",
            "rotation_on_startup",
            True,
        )
    )
    enqueue_val = str_to_bool(resolve(enqueue, "LOGFLOW_ENQUEUE", "enqueue", False))

    target_name = discovery.determine_script_name(
        resolve(script_name, "LOGFLOW_SCRIPT_NAME", "script_name", None)
    )
    new_log_file = log_dir_path / f"{target_name}.log"

    # 2. PIVOT & ROTATION
    if is_main_proc:
        curr = LoggingState.log_file
        if curr and new_log_file.resolve() != curr.resolve():
            _perform_pivot(curr, new_log_file, do_rotation, retention_val)
        elif do_rotation and not LoggingState.configured and new_log_file.exists():
            _rotate(new_log_file, retention_val)

    # 3. Setup Sinks
    if not LoggingState.configured or force:
        logger.remove()

        if is_main_proc:
            fmt = (
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                "<level>{level: <8}</level> | "
                "{extra[rank_tag]}<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
                "<level>{message}</level>"
            )
            logger.add(
                sys.stderr,
                level="TRACE",
                format=fmt,
                filter=_make_sink_filter("console", c_no, module_rules),
                colorize=True,
            )

        file_fmt = (
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
            "{extra[rank_tag]}{name}:{function}:{line} | {message}"
        )
        # Lazy-enqueue: when the user asks for ``enqueue=True``, defer the
        # multiprocessing queue (and its POSIX semaphore) until something
        # actually forks/spawns a child. Children re-running configure_logging
        # detect themselves via current_process().name and start eagerly.
        eager_env = os.getenv("LOGFLOW_EAGER_ENQUEUE")
        force_eager = eager_env is not None and str_to_bool(eager_env)
        in_child = current_process().name != "MainProcess"
        start_with_enqueue = enqueue_val and (force_eager or in_child)
        file_sink_params: dict = dict(
            sink=str(new_log_file),
            level="TRACE",
            format=file_fmt,
            filter=_make_sink_filter("file", f_no, module_rules),
            mode="a",
            enqueue=start_with_enqueue,
        )
        sink_id = logger.add(**file_sink_params)

        LoggingState.file_sink_id = sink_id
        LoggingState.file_sink_params = file_sink_params
        LoggingState.enqueue_active = start_with_enqueue
        LoggingState.enqueue_requested = bool(enqueue_val)

        if enqueue_val and not start_with_enqueue:
            _install_lazy_enqueue_hooks()

    was_cfg = LoggingState.configured
    LoggingState.log_file = new_log_file
    LoggingState.configured = True
    setup_interception()

    if is_main_proc:
        os.environ["LOGFLOW_SCRIPT_NAME"] = target_name

        all_logs = [
            f
            for f in log_dir_path.glob("*.log")
            if f.is_file() and f.resolve() != new_log_file.resolve()
        ]
        _purge_old_files(all_logs, max(retention_val - 1, 0))

        logger.info(
            f"LogFlow {'Re-' if was_cfg else ''}initialized: {new_log_file.name}"
        )


def shutdown_logging() -> None:
    try:
        logger.complete()
    except Exception as e:
        warnings.warn(f"LogFlow: Failed to complete logger during shutdown: {e}")


def get_logger(name: Optional[str] = None) -> "Logger":
    if not LoggingState.configured:
        configure_logging()
    return logger.bind(name=name) if name else logger
