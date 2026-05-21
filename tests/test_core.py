import os
import time
from pathlib import Path
from typing import Any

import pytest
from loguru import logger

from logflow.core import configure_logging, get_logger, shutdown_logging


def _emit(name: str, level: str, msg: str) -> None:
    """Emit a log record with a forced `record["name"]` so per-logger filtering can be tested."""

    def _patch(record: Any) -> None:
        record["name"] = name

    logger.patch(_patch).log(level, msg)


def test_configure_default(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    script_name = "test_app"

    configure_logging(log_dir=log_dir, script_name=script_name)

    test_logger = get_logger("test")
    test_logger.info("Test message")
    shutdown_logging()

    log_file = log_dir / f"{script_name}.log"
    assert log_file.exists()
    assert "Test message" in log_file.read_text()


def test_configure_env_overrides_file(tmp_path: Path) -> None:
    log_dir = tmp_path / "env_test"
    # Create config file
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[tool.logflow]\nfile_level = 'INFO'")

    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    os.environ["LOGFLOW_FILE_LEVEL"] = "TRACE"
    try:
        configure_logging(log_dir=log_dir, script_name="env_over")
        test_logger = get_logger("env_test")
        test_logger.trace("Trace message")
        shutdown_logging()

        # Check the actual file created
        log_file = log_dir / "env_over.log"
        assert log_file.exists()
        assert "Trace message" in log_file.read_text()
    finally:
        os.chdir(old_cwd)
        del os.environ["LOGFLOW_FILE_LEVEL"]


def test_configure_args_overrides_env(tmp_path: Path) -> None:
    log_dir = tmp_path / "arg_test"
    os.environ["LOGFLOW_FILE_LEVEL"] = "INFO"
    try:
        # Pass TRACE via argument
        configure_logging(log_dir=log_dir, script_name="arg_over", file_level="TRACE")
        test_logger = get_logger("arg_test")
        test_logger.trace("Trace message from arg")
        shutdown_logging()

        log_file = log_dir / "arg_over.log"
        assert log_file.exists()
        assert "Trace message from arg" in log_file.read_text()
    finally:
        del os.environ["LOGFLOW_FILE_LEVEL"]


def test_configure_rank_non_zero(tmp_path: Path) -> None:
    log_dir = tmp_path / "rank_test"
    os.environ["RANK"] = "1"
    try:
        configure_logging(log_dir=log_dir, script_name="rank_app")
        test_logger = get_logger("rank")
        test_logger.info("Rank 1 message")
        shutdown_logging()

        log_file = log_dir / "rank_app.log"
        assert log_file.exists()
        content = log_file.read_text()
        assert "Rank 1 message" in content
        assert "[rank 1]" in content
    finally:
        del os.environ["RANK"]


def test_configure_rank_mocked(tmp_path: Path, monkeypatch: Any) -> None:
    log_dir = tmp_path / "mock_rank"
    # Mock get_rank to return 2
    import logflow.discovery

    monkeypatch.setattr(logflow.discovery, "get_rank", lambda: 2)

    configure_logging(log_dir=log_dir, script_name="mocked")
    test_logger = get_logger("test")
    test_logger.info("Mocked rank message")
    shutdown_logging()

    log_file = log_dir / "mocked.log"
    assert log_file.exists()
    content = log_file.read_text()
    assert "Mocked rank message" in content
    assert "[rank 2]" in content


def test_configure_no_rotation(tmp_path: Path) -> None:
    log_dir = tmp_path / "no_rotate"
    log_dir.mkdir()
    log_file = log_dir / "app.log"
    log_file.write_text("old\n")

    # Wait a bit so mtime is different if needed
    time.sleep(0.1)

    # Initial config (this will clobber or append depending on mode)
    # Since it's the first config in this process, it might rotate if rotation_on_startup is True
    configure_logging(log_dir=log_dir, script_name="app", rotation_on_startup=False)
    test_logger = get_logger("no_rotate")
    test_logger.info("new")
    shutdown_logging()

    content = log_file.read_text()
    assert "old" in content
    assert "new" in content


def test_startup_rotation(tmp_path: Path) -> None:
    log_dir = tmp_path / "rotation_test"
    log_dir.mkdir()
    log_file = log_dir / "rotate.log"
    log_file.write_text("old content")

    # Small sleep to ensure mtime is distinct
    time.sleep(0.1)

    # First configuration: should rotate the existing file
    configure_logging(log_dir=log_dir, script_name="rotate", rotation_on_startup=True)
    get_logger().info("new content")
    shutdown_logging()

    # Check that a rotated file exists
    rotated_files = list(log_dir.glob("rotate.*.log"))
    assert len(rotated_files) == 1
    assert "old content" in rotated_files[0].read_text()
    assert "new content" in (log_dir / "rotate.log").read_text()


# --- Per-logger, per-sink level overrides (`module_levels`) -----------------


def _write_yaml(path: Path, body: str) -> None:
    path.write_text(body)


def test_module_levels_demotes_logger_on_file_sink(tmp_path: Path) -> None:
    """Global file_level=DEBUG, override file=WARNING for pkg.a — INFO from pkg.a dropped, INFO from pkg.b kept."""
    _write_yaml(
        tmp_path / "logflow.yaml",
        'file_level: "DEBUG"\nconsole_level: "INFO"\nmodule_levels:\n  "pkg.a":\n    file: WARNING\n',
    )
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        configure_logging(log_dir=tmp_path / "logs", script_name="demote")
        _emit("pkg.a", "INFO", "from-a-info")
        _emit("pkg.a", "WARNING", "from-a-warn")
        _emit("pkg.b", "INFO", "from-b-info")
        shutdown_logging()

        text = (tmp_path / "logs" / "demote.log").read_text()
        assert "from-a-info" not in text
        assert "from-a-warn" in text
        assert "from-b-info" in text
    finally:
        os.chdir(old_cwd)


def test_module_levels_per_sink_split(tmp_path: Path) -> None:
    """Override console=ERROR, file=DEBUG for same logger — INFO appears in file but not console."""
    _write_yaml(
        tmp_path / "logflow.yaml",
        (
            'file_level: "DEBUG"\n'
            'console_level: "INFO"\n'
            "module_levels:\n"
            '  "pkg.split":\n'
            "    console: ERROR\n"
            "    file: DEBUG\n"
        ),
    )
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        configure_logging(log_dir=tmp_path / "logs", script_name="split")
        _emit("pkg.split", "INFO", "split-info")
        _emit("pkg.split", "DEBUG", "split-debug")
        shutdown_logging()

        text = (tmp_path / "logs" / "split.log").read_text()
        # File sink: DEBUG threshold for this logger, so both lines pass.
        assert "split-info" in text
        assert "split-debug" in text
    finally:
        os.chdir(old_cwd)


def test_module_levels_promotes_above_global(tmp_path: Path) -> None:
    """Global file_level=INFO, override file=DEBUG for pkg.a — DEBUG from pkg.a written, DEBUG from pkg.b dropped."""
    _write_yaml(
        tmp_path / "logflow.yaml",
        'file_level: "INFO"\nconsole_level: "INFO"\nmodule_levels:\n  "pkg.a":\n    file: DEBUG\n',
    )
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        configure_logging(log_dir=tmp_path / "logs", script_name="promote")
        _emit("pkg.a", "DEBUG", "a-debug")
        _emit("pkg.b", "DEBUG", "b-debug")
        _emit("pkg.b", "INFO", "b-info")
        shutdown_logging()

        text = (tmp_path / "logs" / "promote.log").read_text()
        assert "a-debug" in text
        assert "b-debug" not in text
        assert "b-info" in text
    finally:
        os.chdir(old_cwd)


def test_module_levels_workers_only_no_effect_in_main(tmp_path: Path) -> None:
    """workers_only=true rule is a no-op when current_process().name == 'MainProcess'."""
    _write_yaml(
        tmp_path / "logflow.yaml",
        (
            'file_level: "DEBUG"\n'
            "module_levels:\n"
            '  "pkg.workeronly":\n'
            "    file: WARNING\n"
            "    workers_only: true\n"
        ),
    )
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        configure_logging(log_dir=tmp_path / "logs", script_name="wo_main")
        _emit("pkg.workeronly", "INFO", "main-info")
        shutdown_logging()

        text = (tmp_path / "logs" / "wo_main.log").read_text()
        assert "main-info" in text
    finally:
        os.chdir(old_cwd)


def test_module_levels_workers_only_applies_in_child(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """workers_only=true rule fires when current_process().name != 'MainProcess'."""
    _write_yaml(
        tmp_path / "logflow.yaml",
        (
            'file_level: "DEBUG"\n'
            "module_levels:\n"
            '  "pkg.workeronly":\n'
            "    file: WARNING\n"
            "    workers_only: true\n"
        ),
    )
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        # Patch current_process BEFORE configure_logging so the filter closure
        # is built against the real function, and the patch is visible at
        # record-emission time (the filter calls current_process() per record).
        import logflow.core

        class _FakeProc:
            name = "Worker-1"

        monkeypatch.setattr(logflow.core, "current_process", lambda: _FakeProc())

        configure_logging(log_dir=tmp_path / "logs", script_name="wo_child")
        _emit("pkg.workeronly", "INFO", "child-info")
        _emit("pkg.workeronly", "WARNING", "child-warn")
        _emit("pkg.other", "INFO", "other-info")
        shutdown_logging()

        text = (tmp_path / "logs" / "wo_child.log").read_text()
        assert "child-info" not in text
        assert "child-warn" in text
        assert "other-info" in text
    finally:
        os.chdir(old_cwd)


def test_module_levels_longest_prefix_wins(tmp_path: Path) -> None:
    """Keys 'pkg' (WARNING) and 'pkg.sub' (DEBUG) — DEBUG record from pkg.sub.mod passes."""
    _write_yaml(
        tmp_path / "logflow.yaml",
        (
            'file_level: "DEBUG"\n'
            "module_levels:\n"
            '  "pkg":\n'
            "    file: WARNING\n"
            '  "pkg.sub":\n'
            "    file: DEBUG\n"
        ),
    )
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        configure_logging(log_dir=tmp_path / "logs", script_name="longest")
        _emit(
            "pkg.sub.mod", "DEBUG", "submod-debug"
        )  # matches longer "pkg.sub" → DEBUG threshold
        _emit(
            "pkg.other", "DEBUG", "other-debug"
        )  # matches only "pkg" → WARNING threshold
        _emit("pkg.other", "WARNING", "other-warn")
        shutdown_logging()

        text = (tmp_path / "logs" / "longest.log").read_text()
        assert "submod-debug" in text
        assert "other-debug" not in text
        assert "other-warn" in text
    finally:
        os.chdir(old_cwd)


def test_module_levels_prefix_does_not_match_substring(tmp_path: Path) -> None:
    """Key 'foo' must NOT silence logs from 'foobar.baz'."""
    _write_yaml(
        tmp_path / "logflow.yaml",
        'file_level: "DEBUG"\nmodule_levels:\n  "foo":\n    file: ERROR\n',
    )
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        configure_logging(log_dir=tmp_path / "logs", script_name="substr")
        _emit("foobar.baz", "INFO", "foobar-info")  # must NOT match "foo"
        _emit("foo.child", "INFO", "foo-child-info")  # must match
        _emit("foo", "INFO", "foo-info")  # exact match
        shutdown_logging()

        text = (tmp_path / "logs" / "substr.log").read_text()
        assert "foobar-info" in text
        assert "foo-child-info" not in text
        assert "foo-info" not in text
    finally:
        os.chdir(old_cwd)


def test_module_levels_invalid_level_raises(tmp_path: Path) -> None:
    _write_yaml(
        tmp_path / "logflow.yaml",
        'file_level: "DEBUG"\nmodule_levels:\n  "pkg.a":\n    file: BOGUS\n',
    )
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        with pytest.raises(ValueError, match="BOGUS"):
            configure_logging(log_dir=tmp_path / "logs", script_name="bad_level")
    finally:
        os.chdir(old_cwd)


def test_module_levels_unknown_subkey_raises(tmp_path: Path) -> None:
    """Typo guard — silent ignores are how this feature rotted unimplemented."""
    _write_yaml(
        tmp_path / "logflow.yaml",
        'file_level: "DEBUG"\nmodule_levels:\n  "pkg.a":\n    file: INFO\n    file_level: INFO\n',
    )
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        with pytest.raises(ValueError, match="file_level"):
            configure_logging(log_dir=tmp_path / "logs", script_name="typo")
    finally:
        os.chdir(old_cwd)


def test_module_levels_absent_is_no_op(tmp_path: Path) -> None:
    """Config without `module_levels` behaves exactly as before."""
    _write_yaml(
        tmp_path / "logflow.yaml", 'file_level: "DEBUG"\nconsole_level: "INFO"\n'
    )
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        configure_logging(log_dir=tmp_path / "logs", script_name="noop")
        _emit("anything.at.all", "INFO", "noop-info")
        _emit("anything.at.all", "DEBUG", "noop-debug")
        shutdown_logging()

        text = (tmp_path / "logs" / "noop.log").read_text()
        assert "noop-info" in text
        assert "noop-debug" in text
    finally:
        os.chdir(old_cwd)


def test_module_levels_requires_at_least_one_sink(tmp_path: Path) -> None:
    _write_yaml(
        tmp_path / "logflow.yaml",
        'file_level: "DEBUG"\nmodule_levels:\n  "pkg.a":\n    workers_only: true\n',
    )
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        with pytest.raises(ValueError, match="at least one"):
            configure_logging(log_dir=tmp_path / "logs", script_name="empty_rule")
    finally:
        os.chdir(old_cwd)
