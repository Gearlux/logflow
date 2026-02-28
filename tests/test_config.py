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


def test_xdg_config_path() -> None:
    # Mock XDG_CONFIG_HOME
    os.environ["XDG_CONFIG_HOME"] = "/tmp/xdg"
    assert str(get_xdg_config_dir()) == "/tmp/xdg/logflow"
    del os.environ["XDG_CONFIG_HOME"]
