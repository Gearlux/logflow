import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

# For Python < 3.11, use tomli
if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


def get_xdg_config_dir() -> Path:
    """Return the XDG config directory (e.g., ~/.config/logflow)."""
    xdg_config_home = os.getenv("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home) / "logflow"
    return Path.home() / ".config" / "logflow"


def load_config() -> Dict[str, Any]:
    """
    Load configuration from multiple sources with the following priority:
    1. Local logflow.yaml / logflow.yml
    2. Local pyproject.toml ([tool.logflow] section)
    3. XDG User Config (~/.config/logflow/config.yaml)
    
    Returns:
        A dictionary containing the merged configuration.
    """
    config: Dict[str, Any] = {}

    # 1. XDG User Config (lowest priority)
    xdg_path = get_xdg_config_dir() / "config.yaml"
    if xdg_path.exists():
        try:
            with open(xdg_path, "r") as f:
                config.update(yaml.safe_load(f) or {})
        except Exception:
            pass

    # 2. Local pyproject.toml
    pyproject_path = Path("pyproject.toml")
    if pyproject_path.exists():
        try:
            with open(pyproject_path, "rb") as f:
                toml_data = tomllib.load(f)
                config.update(toml_data.get("tool", {}).get("logflow", {}))
        except Exception:
            pass

    # 3. Local logflow.yaml / logflow.yml (highest priority)
    for ext in ["yaml", "yml"]:
        local_yaml = Path(f"logflow.{ext}")
        if local_yaml.exists():
            try:
                with open(local_yaml, "r") as f:
                    config.update(yaml.safe_load(f) or {})
                    break
            except Exception:
                pass

    return config
