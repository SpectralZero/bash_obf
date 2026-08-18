"""Validated YAML configuration loading for the obfush CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from obfush.layers import ALL_LAYER_NAMES


MAX_CONFIG_BYTES = 1_048_576
_ALIASES = {
    "layers": "force_layers",
    "no_layer": "disable_layers",
}
_ALLOWED_KEYS = {
    "preset", "seed", "intensity", "force_layers", "disable_layers",
    "min_layers", "eval_mode", "entropy_target", "max_size_ratio",
    "verify", "test_input", "workers", "fail_fast",
    "log_level",
    "output_mode", "environment_key", "anti_debug",
}


class ConfigError(ValueError):
    """Raised when a configuration file is malformed or unsupported."""


def discover_config(start: Path | None = None, home: Path | None = None) -> list[Path]:
    """Return global then nearest-project configuration files."""
    start = (start or Path.cwd()).resolve()
    home = (home or Path.home()).resolve()
    found: list[Path] = []

    global_config = home / ".obfushrc"
    if global_config.is_file():
        found.append(global_config)

    project_config = None
    for directory in (start, *start.parents):
        candidate = directory / ".obfushrc"
        if candidate.is_file():
            project_config = candidate
            break
    if project_config is not None and project_config not in found:
        found.append(project_config)
    return found


def load_config(paths: list[Path]) -> dict[str, Any]:
    """Load, validate, and merge configuration files in precedence order."""
    merged: dict[str, Any] = {}
    for path in paths:
        try:
            if path.stat().st_size > MAX_CONFIG_BYTES:
                raise ConfigError(f"Configuration file is too large: {path}")
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except ConfigError:
            raise
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise ConfigError(f"Could not read configuration {path}: {exc}") from exc

        if loaded is None:
            continue
        if not isinstance(loaded, dict):
            raise ConfigError(f"Configuration root must be a mapping: {path}")

        normalized = {
            _ALIASES.get(str(key).replace("-", "_"), str(key).replace("-", "_")): value
            for key, value in loaded.items()
        }
        unknown = sorted(set(normalized) - _ALLOWED_KEYS)
        if unknown:
            raise ConfigError(
                f"Unknown configuration key(s) in {path}: {', '.join(unknown)}"
            )
        if normalized.get("test_input") is not None:
            test_input = Path(str(normalized["test_input"])).expanduser()
            if not test_input.is_absolute():
                test_input = path.parent / test_input
            normalized["test_input"] = str(test_input.resolve())
        merged.update(normalized)

    validated = validate_config(merged)
    if validated.get("test_input") is not None:
        test_input = Path(validated["test_input"])
        if not test_input.is_file():
            raise ConfigError(f"test_input does not exist or is not a file: {test_input}")
    return validated


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    """Normalize values to the CLI's internal representation."""
    result = dict(config)

    if "preset" in result and result["preset"] not in {
        "stealth", "standard", "paranoid", "godmode",
    }:
        raise ConfigError("preset must be stealth, standard, paranoid, or godmode")

    if "seed" in result and not isinstance(result["seed"], (str, int)):
        raise ConfigError("seed must be a string or integer")

    for name, minimum, maximum in (
        ("intensity", 0.0, 1.0),
        ("entropy_target", 0.0, 8.0),
    ):
        if name in result:
            value = result[name]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ConfigError(f"{name} must be numeric")
            if not minimum <= float(value) <= maximum:
                raise ConfigError(f"{name} must be {minimum}-{maximum}")
            result[name] = float(value)

    if "max_size_ratio" in result:
        value = result["max_size_ratio"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 1.0:
            raise ConfigError("max_size_ratio must be numeric and at least 1.0")
        result["max_size_ratio"] = float(value)

    for name, minimum in (("min_layers", 1), ("workers", 1)):
        if name in result:
            value = result[name]
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ConfigError(f"{name} must be an integer of at least {minimum}")

    if "eval_mode" in result and result["eval_mode"] not in {
        "ok", "no-eval", "direct-exec",
    }:
        raise ConfigError("eval_mode must be ok, no-eval, or direct-exec")

    if "log_level" in result:
        if not isinstance(result["log_level"], str):
            raise ConfigError("log_level must be a string")
        result["log_level"] = result["log_level"].upper()
        if result["log_level"] not in {
            "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL",
        }:
            raise ConfigError("log_level must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")

    if "output_mode" in result and result["output_mode"] not in {"script", "binary"}:
        raise ConfigError("output_mode must be script or binary")
    if "environment_key" in result and result["environment_key"] is not None:
        if not isinstance(result["environment_key"], str) or not result["environment_key"]:
            raise ConfigError("environment_key must be a non-empty string")

    for name in ("verify", "fail_fast", "anti_debug"):
        if name in result and not isinstance(result[name], bool):
            raise ConfigError(f"{name} must be true or false")

    for name in ("force_layers", "disable_layers"):
        if name not in result or result[name] is None:
            continue
        value = result[name]
        if isinstance(value, str):
            layers = [layer.strip() for layer in value.split(",") if layer.strip()]
        elif isinstance(value, list) and all(isinstance(layer, str) for layer in value):
            layers = [layer.strip() for layer in value if layer.strip()]
        else:
            raise ConfigError(f"{name} must be a comma-separated string or string list")
        unknown = sorted(set(layers) - set(ALL_LAYER_NAMES))
        if unknown:
            raise ConfigError(f"Unknown layer(s) in {name}: {', '.join(unknown)}")
        result[name] = ",".join(layers) if layers else None

    if "test_input" in result and result["test_input"] is not None:
        if not isinstance(result["test_input"], str):
            raise ConfigError("test_input must be a path string")

    return result
