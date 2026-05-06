"""
obfush.layers — Transformation layer registry.

Each layer operates on the normalised AST and returns a modified AST.
Layers are registered here so the engine can discover them by name.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from obfush.layers.base import Layer

# Canonical layer names → module paths (lazy-loaded to avoid circular imports)
LAYER_REGISTRY: dict[str, str] = {
    "id-mangle":    "obfush.layers.id_mangle",
    "str-shred":    "obfush.layers.str_shred",
    "cmd-sub":      "obfush.layers.cmd_sub",
    "junk-inject":  "obfush.layers.junk_inject",
    "flow-obfusc":  "obfush.layers.flow_obfusc",
    "encode":       "obfush.layers.encode",
    "indirection":  "obfush.layers.indirection",
    "poly-shell":   "obfush.layers.poly_shell",
    "entropy-mask": "obfush.layers.entropy_mask",
}

# All known layer names in default application order
ALL_LAYER_NAMES: list[str] = list(LAYER_REGISTRY.keys())


def get_layer(name: str) -> "Layer":
    """Instantiate a layer by its canonical name.

    Args:
        name: Canonical layer name (e.g. 'id-mangle').

    Returns:
        Layer instance.

    Raises:
        KeyError: If the layer name is not registered.
    """
    import importlib

    if name not in LAYER_REGISTRY:
        raise KeyError(
            f"Unknown layer '{name}'. Available: {', '.join(LAYER_REGISTRY)}"
        )

    module_path = LAYER_REGISTRY[name]
    module = importlib.import_module(module_path)

    # Convention: each layer module exposes a class named `LayerImpl`
    layer_cls = getattr(module, "LayerImpl")
    return layer_cls()
