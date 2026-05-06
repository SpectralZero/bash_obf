"""
Layer selector — picks active layers, randomises order, assigns intensities.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from obfush.layers import ALL_LAYER_NAMES
from obfush.utils.compat_matrix import get_safe_order, validate_layer_set


@dataclass
class LayerPlan:
    """Plan for a single layer's execution."""
    name: str
    intensity: float
    seed: int

    def __repr__(self) -> str:
        return f"LayerPlan({self.name}, intensity={self.intensity:.2f})"


class LayerSelector:
    """Selects, orders, and parameterises layers for an obfuscation run."""

    def __init__(
        self,
        master_seed: int,
        intensity: float = 0.8,
        force_layers: list[str] | None = None,
        disable_layers: list[str] | None = None,
        min_layers: int = 4,
        eval_mode: str = "ok",
    ) -> None:
        self.master_seed = master_seed
        self.intensity = intensity
        self.force_layers = force_layers
        self.disable_layers = disable_layers or []
        self.min_layers = max(1, min_layers)
        self.eval_mode = eval_mode
        self.rng = random.Random(master_seed)

    def select(self) -> list[LayerPlan]:
        """Select and order layers for this run."""
        if self.force_layers:
            validate_layer_set(self.force_layers)
            candidates = list(self.force_layers)
        else:
            candidates = self._auto_select()

        if self.disable_layers:
            validate_layer_set(self.disable_layers)
            candidates = [l for l in candidates if l not in self.disable_layers]

        if len(candidates) < self.min_layers:
            available = [
                l for l in ALL_LAYER_NAMES
                if l not in candidates and l not in self.disable_layers
            ]
            self.rng.shuffle(available)
            while len(candidates) < self.min_layers and available:
                candidates.append(available.pop())

        self.rng.shuffle(candidates)
        ordered = get_safe_order(candidates)

        plans: list[LayerPlan] = []
        for layer_name in ordered:
            from obfush.engine.seed import derive_layer_seed
            layer_seed = derive_layer_seed(self.master_seed, layer_name)
            jitter = (self.rng.random() - 0.5) * 0.4 * self.intensity
            layer_intensity = max(0.0, min(1.0, self.intensity + jitter))
            plans.append(LayerPlan(
                name=layer_name, intensity=layer_intensity, seed=layer_seed,
            ))
        return plans

    def _auto_select(self) -> list[str]:
        """Auto-select layers based on intensity."""
        always_on = ["id-mangle", "str-shred", "cmd-sub", "junk-inject"]
        optional = {
            "flow-obfusc": 0.4, "encode": 0.3, "indirection": 0.5,
            "poly-shell": 0.9, "entropy-mask": 0.6,
        }
        selected = list(always_on)
        for name, threshold in optional.items():
            if self.intensity >= threshold:
                prob = min(1.0, (self.intensity - threshold) / (1.0 - threshold + 0.01) + 0.5)
                if self.rng.random() < prob:
                    selected.append(name)
        return selected
