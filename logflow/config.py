import os
from pathlib import Path
from typing import Any, Dict

import yaml

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore


def get_xdg_config_dir() -> Path:
    """Get the XDG compliant configuration directory for LogFlow."""
    xdg_config_home = os.getenv("XDG_CONFIG_HOME")
    if xdg_config_home:
        base = Path(xdg_config_home)
    else:
        base = Path("~/.config").expanduser()
    return base / "logflow"


def load_config() -> Dict[str, Any]:
    """
    Load LogFlow configuration from standard locations.
    Priority:
    1. logflow.yaml (CWD)
    2. pyproject.toml (CWD)
    3. ~/.config/logflow/config.yaml (or XDG_CONFIG_HOME)
    """
    config: Dict[str, Any] = {}

    # 1. Check for logflow.yaml / .yml in CWD
    for ext in ["yaml", "yml"]:
        yaml_path = Path(f"logflow.{ext}")
        if yaml_path.exists():
            try:
                with open(yaml_path, "r") as f:
                    config.update(yaml.safe_load(f) or {})
                    return config  # Return immediately if found in CWD
            except Exception:
                pass

    # 2. Check for pyproject.toml in CWD
    toml_path = Path("pyproject.toml")
    if toml_path.exists():
        try:
            with open(toml_path, "rb") as f:
                data = tomllib.load(f)
                toml_cfg = data.get("tool", {}).get("logflow", {})
                if toml_cfg:
                    config.update(toml_cfg)
                    return config  # Return immediately if found in CWD
        except Exception:
            pass

    # 3. Check for global config (~/.config/logflow/config.yaml or XDG_CONFIG_HOME)
    if not config:
        global_path = get_xdg_config_dir() / "config.yaml"
        if global_path.exists():
            try:
                with open(global_path, "r") as f:
                    config.update(yaml.safe_load(f) or {})
            except Exception:
                pass

    return config
