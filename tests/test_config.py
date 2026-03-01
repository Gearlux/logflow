import os
from pathlib import Path

from logflow.config import get_xdg_config_dir, load_config


def test_load_config_pyproject(tmp_path: Path) -> None:
    # Mock pyproject.toml
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("""
[tool.logflow]
console_level = "DEBUG"
retention = 10
""")

    # Change directory to tmp_path
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        cfg = load_config()
        assert cfg["console_level"] == "DEBUG"
        assert cfg["retention"] == 10
    finally:
        os.chdir(old_cwd)


def test_load_config_yaml_overrides_toml(tmp_path: Path) -> None:
    # Mock pyproject.toml
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[tool.logflow]\nconsole_level = 'INFO'")

    # Mock logflow.yaml (higher priority)
    logflow_yaml = tmp_path / "logflow.yaml"
    logflow_yaml.write_text("console_level: 'DEBUG'")

    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        cfg = load_config()
        assert cfg["console_level"] == "DEBUG"
    finally:
        os.chdir(old_cwd)


def test_load_config_yml_extension(tmp_path: Path) -> None:
    # Mock logflow.yml
    logflow_yml = tmp_path / "logflow.yml"
    logflow_yml.write_text("file_level: 'TRACE'")

    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        cfg = load_config()
        assert cfg["file_level"] == "TRACE"
    finally:
        os.chdir(old_cwd)


def test_load_config_xdg(tmp_path: Path) -> None:
    # Set XDG_CONFIG_HOME to tmp_path
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path)
    xdg_dir = tmp_path / "logflow"
    xdg_dir.mkdir()
    xdg_file = xdg_dir / "config.yaml"
    xdg_file.write_text("retention: 20")

    try:
        cfg = load_config()
        assert cfg["retention"] == 20
    finally:
        del os.environ["XDG_CONFIG_HOME"]


def test_xdg_config_path_default() -> None:
    # Ensure it returns default home path if env not set
    if "XDG_CONFIG_HOME" in os.environ:
        del os.environ["XDG_CONFIG_HOME"]
    path = get_xdg_config_dir()
    assert ".config/logflow" in str(path)


def test_load_config_corrupt_yaml(tmp_path: Path) -> None:
    # Create invalid YAML
    logflow_yaml = tmp_path / "logflow.yaml"
    logflow_yaml.write_bytes(b"\x00\x01\x02")  # Binary data is invalid YAML

    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        cfg = load_config()
        # Should fail gracefully and return empty dict
        assert cfg == {}
    finally:
        os.chdir(old_cwd)


def test_load_config_pyproject_missing_tool(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[tool.something_else]\nkey = 'value'")

    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        cfg = load_config()
        assert cfg == {}
    finally:
        os.chdir(old_cwd)


def test_load_config_corrupt_toml(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    # Write invalid TOML (unquoted string or similar)
    pyproject.write_text("[tool.logflow]\nkey = value_without_quotes")

    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        cfg = load_config()
        assert cfg == {}
    finally:
        os.chdir(old_cwd)


def test_load_config_empty(tmp_path: Path) -> None:
    # Test loading when no files exist
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        cfg = load_config()
        assert cfg == {}
    finally:
        os.chdir(old_cwd)
