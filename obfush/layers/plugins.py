"""Explicit loading for trusted local transformation-layer plugins."""

from __future__ import annotations

import hashlib
import importlib.util
from dataclasses import dataclass
from pathlib import Path

from obfush.layers import register_layer
from obfush.layers.base import Layer


@dataclass(frozen=True)
class LoadedPlugin:
    name: str
    path: str
    sha256: str


def load_plugin(path: str | Path) -> LoadedPlugin:
    """Load one explicitly selected Python file exposing ``LayerImpl``."""
    plugin_path = Path(path).expanduser().resolve()
    if not plugin_path.is_file() or plugin_path.suffix != ".py":
        raise ValueError(f"Plugin must be an existing .py file: {plugin_path}")
    data = plugin_path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    module_name = f"obfush_plugin_{digest[:16]}"
    spec = importlib.util.spec_from_file_location(module_name, plugin_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Could not create plugin module: {plugin_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    layer_class = getattr(module, "LayerImpl", None)
    if not isinstance(layer_class, type) or not issubclass(layer_class, Layer):
        raise ValueError("Plugin must expose LayerImpl inheriting Layer")
    name = getattr(layer_class, "name", "")
    register_layer(name, layer_class)
    return LoadedPlugin(name=name, path=str(plugin_path), sha256=digest)
