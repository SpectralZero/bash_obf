"""
Layer compatibility matrix & ordering enforcement.

Defines which layers can safely run in which order, and provides
topological sorting that respects DANGER constraints.

Matrix values:
    OK     — Any order is safe.
    CAUT   — May reduce obfuscation quality, but semantically safe.
    DANGER — Specific order is REQUIRED or equivalence breaks.
"""

from __future__ import annotations

from enum import Enum


class Compat(Enum):
    """Compatibility level between two layers."""
    OK = "OK"
    CAUT = "CAUT"
    DANGER = "DANGER"


# ──────────────────────────────────────────────────────────────────────
# Compatibility matrix
# Read as: MATRIX[row][col] = compatibility when row runs BEFORE col
# DANGER entries have forced ordering in ORDERING_RULES below.
# ──────────────────────────────────────────────────────────────────────
MATRIX: dict[str, dict[str, Compat]] = {
    "id-mangle": {
        "str-shred": Compat.OK, "cmd-sub": Compat.OK,
        "junk-inject": Compat.OK, "flow-obfusc": Compat.OK,
        "encode": Compat.OK, "indirection": Compat.OK,
        "poly-shell": Compat.OK, "entropy-mask": Compat.OK,
    },
    "str-shred": {
        "id-mangle": Compat.OK, "cmd-sub": Compat.OK,
        "junk-inject": Compat.OK, "flow-obfusc": Compat.OK,
        "encode": Compat.OK, "indirection": Compat.OK,
        "poly-shell": Compat.OK, "entropy-mask": Compat.OK,
    },
    "cmd-sub": {
        "id-mangle": Compat.OK, "str-shred": Compat.OK,
        "junk-inject": Compat.OK, "flow-obfusc": Compat.DANGER,
        "encode": Compat.OK, "indirection": Compat.OK,
        "poly-shell": Compat.DANGER, "entropy-mask": Compat.OK,
    },
    "junk-inject": {
        "id-mangle": Compat.OK, "str-shred": Compat.CAUT,
        "cmd-sub": Compat.OK, "flow-obfusc": Compat.OK,
        "encode": Compat.OK, "indirection": Compat.OK,
        "poly-shell": Compat.OK, "entropy-mask": Compat.OK,
    },
    "flow-obfusc": {
        "id-mangle": Compat.DANGER, "str-shred": Compat.OK,
        "cmd-sub": Compat.DANGER, "junk-inject": Compat.OK,
        "encode": Compat.OK, "indirection": Compat.DANGER,
        "poly-shell": Compat.DANGER, "entropy-mask": Compat.OK,
    },
    "opaque-const": {
        "id-mangle": Compat.OK, "str-shred": Compat.OK,
        "cmd-sub": Compat.OK, "junk-inject": Compat.OK,
        "flow-obfusc": Compat.OK, "encode": Compat.OK,
        "indirection": Compat.OK, "poly-shell": Compat.OK,
        "entropy-mask": Compat.OK,
    },
    "cff": {
        "id-mangle": Compat.OK, "str-shred": Compat.OK,
        "cmd-sub": Compat.OK, "junk-inject": Compat.OK,
        "flow-obfusc": Compat.DANGER, "opaque-const": Compat.OK,
        "encode": Compat.OK, "indirection": Compat.OK,
        "poly-shell": Compat.OK, "entropy-mask": Compat.OK,
    },
    "encode": {
        "id-mangle": Compat.OK, "str-shred": Compat.OK,
        "cmd-sub": Compat.OK, "junk-inject": Compat.OK,
        "flow-obfusc": Compat.OK, "indirection": Compat.OK,
        "poly-shell": Compat.OK, "entropy-mask": Compat.OK,
    },
    "indirection": {
        "id-mangle": Compat.OK, "str-shred": Compat.OK,
        "cmd-sub": Compat.OK, "junk-inject": Compat.OK,
        "flow-obfusc": Compat.DANGER, "encode": Compat.OK,
        "poly-shell": Compat.OK, "entropy-mask": Compat.OK,
    },
    "poly-shell": {
        "id-mangle": Compat.OK, "str-shred": Compat.OK,
        "cmd-sub": Compat.OK, "junk-inject": Compat.OK,
        "flow-obfusc": Compat.OK, "encode": Compat.OK,
        "indirection": Compat.OK, "entropy-mask": Compat.OK,
    },
    "entropy-mask": {
        "id-mangle": Compat.OK, "str-shred": Compat.OK,
        "cmd-sub": Compat.OK, "junk-inject": Compat.OK,
        "flow-obfusc": Compat.OK, "encode": Compat.OK,
        "indirection": Compat.OK, "poly-shell": Compat.OK,
    },
}

# ──────────────────────────────────────────────────────────────────────
# Hard ordering rules (edges in a DAG)
# (A, B) means A MUST run before B
# ──────────────────────────────────────────────────────────────────────
ORDERING_RULES: list[tuple[str, str]] = [
    ("flow-obfusc", "junk-inject"),    # flow restructuring before dead code
    ("flow-obfusc", "indirection"),    # flow before indirection
    # id-mangle MUST run before any layer that hides assignment LHS or
    # command names inside opaque encoded blobs (encode, str-shred). Otherwise
    # references like ${count} get renamed but the encoded `count=42`
    # assignment stays literal — they no longer match at runtime.
    ("id-mangle", "encode"),
    ("id-mangle", "str-shred"),
    ("id-mangle", "cmd-sub"),
    # flow-obfusc must also run BEFORE encode — flow's dependency analysis
    # (subshell-wrap, reorder) walks the AST looking for var writes; if
    # encode has already wrapped them in `eval "..."` blobs, the writes are
    # invisible and flow-obfusc may incorrectly wrap them in subshells,
    # losing the variable scope.
    ("flow-obfusc", "encode"),
    ("flow-obfusc", "str-shred"),
    ("flow-obfusc", "cmd-sub"),
    # Opaque constants operate on visible numeric syntax. Run after identifier
    # and flow analysis but before text-hiding layers.
    ("id-mangle", "opaque-const"),
    ("flow-obfusc", "opaque-const"),
    ("opaque-const", "encode"),
    ("opaque-const", "str-shred"),
    ("opaque-const", "entropy-mask"),
    ("opaque-const", "poly-shell"),
    ("id-mangle", "cff"),
    ("flow-obfusc", "cff"),
    ("opaque-const", "cff"),
    ("cmd-sub", "cff"),
    ("cff", "junk-inject"),
    ("cff", "encode"),
    ("cff", "str-shred"),
    ("cff", "entropy-mask"),
    ("cff", "poly-shell"),
    # entropy-mask injects raw bash decoy text that must pass through verbatim.
    # All AST-rewriting / string-mangling layers must run BEFORE it, otherwise
    # they corrupt the decoys (e.g. str-shred hex-escaping the decoy LHS).
    ("encode", "entropy-mask"),
    ("str-shred", "entropy-mask"),
    ("cmd-sub", "entropy-mask"),
    ("id-mangle", "entropy-mask"),
    ("junk-inject", "entropy-mask"),
    ("indirection", "entropy-mask"),
    ("flow-obfusc", "entropy-mask"),
    # poly-shell wraps the ENTIRE emitted script in a chunk-loader.
    # All AST-rewriting layers must complete before poly-shell sees the
    # output — otherwise their transformations are invisible to it.
    ("encode", "poly-shell"),
    ("indirection", "poly-shell"),
    ("str-shred", "poly-shell"),
    # anti-trace injects a preamble — must be the very last layer so
    # the anti-debugging code appears at the top of the final output
    # and isn't mangled by other layers.
    ("entropy-mask", "anti-trace"),
    ("poly-shell", "anti-trace"),
    ("encode", "anti-trace"),
    ("str-shred", "anti-trace"),
    ("id-mangle", "anti-trace"),
    ("indirection", "anti-trace"),
    ("junk-inject", "anti-trace"),
    ("flow-obfusc", "anti-trace"),
    ("cff", "anti-trace"),
    ("cmd-sub", "anti-trace"),
    ("opaque-const", "anti-trace"),
]


def get_compatibility(layer_a: str, layer_b: str) -> Compat:
    """Get compatibility level when layer_a runs before layer_b.

    Args:
        layer_a: Layer running first.
        layer_b: Layer running second.

    Returns:
        Compat enum value.
    """
    if layer_a == layer_b:
        return Compat.OK
    return MATRIX.get(layer_a, {}).get(layer_b, Compat.OK)


def get_safe_order(layers: list[str]) -> list[str]:
    """Topologically sort layers respecting DANGER constraints.

    Uses Kahn's algorithm with the ORDERING_RULES DAG edges.
    Layers with no ordering constraints retain their input order
    as a stable tiebreaker.

    Args:
        layers: List of layer names to order.

    Returns:
        Safely ordered list of layer names.

    Raises:
        ValueError: If ordering rules contain a cycle (should never happen
                    with our static rules, but guard against config errors).
    """
    layer_set = set(layers)

    # Build adjacency list and in-degree count from applicable rules
    adj: dict[str, list[str]] = {layer: [] for layer in layers}
    in_degree: dict[str, int] = {layer: 0 for layer in layers}

    for before, after in ORDERING_RULES:
        if before in layer_set and after in layer_set:
            adj[before].append(after)
            in_degree[after] += 1

    # Kahn's algorithm — use original index as tiebreaker for stable sort
    index_map = {name: i for i, name in enumerate(layers)}
    queue: list[str] = sorted(
        [layer for layer in layers if in_degree[layer] == 0],
        key=lambda x: index_map[x],
    )

    result: list[str] = []
    while queue:
        node = queue.pop(0)
        result.append(node)

        for neighbour in adj[node]:
            in_degree[neighbour] -= 1
            if in_degree[neighbour] == 0:
                # Insert sorted by original index for stability
                inserted = False
                for i, q_item in enumerate(queue):
                    if index_map[neighbour] < index_map[q_item]:
                        queue.insert(i, neighbour)
                        inserted = True
                        break
                if not inserted:
                    queue.append(neighbour)

    if len(result) != len(layers):
        remaining = set(layers) - set(result)
        raise ValueError(
            f"Cycle detected in layer ordering rules. "
            f"Stuck layers: {remaining}"
        )

    return result


def validate_layer_set(layers: list[str]) -> list[str]:
    """Validate that all layer names are known.

    Args:
        layers: List of layer names.

    Returns:
        The same list (for chaining).

    Raises:
        ValueError: If any layer name is unknown.
    """
    from obfush.layers import ALL_LAYER_NAMES

    known = set(ALL_LAYER_NAMES)
    unknown = set(layers) - known
    if unknown:
        raise ValueError(
            f"Unknown layer(s): {', '.join(sorted(unknown))}. "
            f"Available: {', '.join(sorted(known))}"
        )
    return layers
