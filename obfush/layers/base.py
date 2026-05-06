"""
Abstract base class and configuration for all transformation layers.

Every layer receives a normalised AST dict and a LayerConfig, and returns
a modified AST dict.  The contract guarantees that the transform preserves
semantic equivalence — verified by the engine's equivalence harness.
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LayerConfig:
    """Configuration passed to every layer at transform time.

    Attributes:
        intensity:  0.0–1.0 obfuscation aggressiveness.
        seed:       Per-layer deterministic seed.
        rng:        Seeded PRNG instance (do NOT use random.* globals).
        eval_mode:  'ok' | 'no-eval' | 'direct-exec'.
    """

    intensity: float
    seed: int
    rng: random.Random
    eval_mode: str = "ok"

    def __post_init__(self) -> None:
        if not 0.0 <= self.intensity <= 1.0:
            raise ValueError(f"intensity must be 0.0–1.0, got {self.intensity}")
        if self.eval_mode not in ("ok", "no-eval", "direct-exec"):
            raise ValueError(
                f"eval_mode must be 'ok', 'no-eval', or 'direct-exec', "
                f"got '{self.eval_mode}'"
            )


@dataclass
class LayerStats:
    """Statistics collected during a layer's transform pass.

    Layers populate this to give the CLI verbose output and debug logging.
    """

    nodes_visited: int = 0
    nodes_modified: int = 0
    identifiers_mangled: int = 0
    strings_shredded: int = 0
    commands_substituted: int = 0
    junk_blocks_injected: int = 0
    blocks_reordered: int = 0
    regions_encoded: int = 0
    indirections_added: int = 0
    chunks_created: int = 0
    decoy_lines_added: int = 0
    custom: dict[str, Any] = field(default_factory=dict)


class Layer(ABC):
    """Abstract base for all obfuscation layers.

    Subclasses MUST implement:
        - name (str):        Canonical layer name (e.g. 'id-mangle')
        - description (str): Human-readable one-liner
        - transform():       AST → AST transformation

    Subclasses MAY override:
        - validate():              Quick structural sanity check
        - estimate_size_increase(): Predicted output size multiplier
    """

    name: str = ""
    description: str = ""

    @abstractmethod
    def transform(
        self,
        ast: dict,
        config: LayerConfig,
    ) -> tuple[dict, LayerStats]:
        """Apply the transformation to the AST.

        Args:
            ast:    Normalised AST dictionary.
            config: Layer-specific configuration.

        Returns:
            Tuple of (modified AST, statistics).
        """
        ...

    def validate(self, ast_before: dict, ast_after: dict) -> bool:
        """Quick structural sanity check after transformation.

        Default implementation just checks that the AST root is intact.
        Layers should override for deeper checks.

        Args:
            ast_before: AST before transformation.
            ast_after:  AST after transformation.

        Returns:
            True if structurally valid.
        """
        return (
            isinstance(ast_after, dict)
            and "type" in ast_after
            and ast_after["type"] == ast_before.get("type", "script")
        )

    def estimate_size_increase(self, config: LayerConfig) -> float:
        """Estimated output size multiplier.

        Used by the engine to warn about size explosion.

        Args:
            config: Layer configuration.

        Returns:
            Multiplier (1.0 = no change, 2.0 = double, etc.)
        """
        return 1.0

    def __repr__(self) -> str:
        return f"<Layer:{self.name}>"
