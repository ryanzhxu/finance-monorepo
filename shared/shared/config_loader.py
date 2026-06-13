from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class ConfigError(RuntimeError):
    pass


def load_yaml_config(path: Path, required_keys: set[str] | None = None) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Missing config file: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"Config must be a mapping: {path}")
    missing = sorted((required_keys or set()) - set(data))
    if missing:
        raise ConfigError(f"Config {path} missing required keys: {', '.join(missing)}")
    return data


def require_nested_keys(config: dict[str, Any], required: dict[str, set[str]], name: str) -> None:
    missing: list[str] = []
    for section, keys in required.items():
        value = config.get(section)
        if not isinstance(value, dict):
            missing.append(section)
            continue
        missing.extend(f"{section}.{key}" for key in sorted(keys - set(value)))
    if missing:
        raise ConfigError(f"{name} missing required keys: {', '.join(missing)}")
