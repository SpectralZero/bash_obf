"""
Layer 5: Control Flow Obfuscation

Reorders and disguises logic so the original structure cannot be recovered.
Must run BEFORE junk_inject and indirection (compatibility matrix).
"""

from __future__ import annotations

import random
import re
from typing import Any

from obfush.layers.base import Layer, LayerConfig, LayerStats


class LayerImpl(Layer):
    name = "flow-obfusc"
    description = "Control flow restructuring"

    def transform(self, ast: dict, config: LayerConfig) -> tuple[dict, LayerStats]:
        stats = LayerStats()
        rng = config.rng
        ast = _flow_walk(ast, config, stats)
        return ast, stats

    def estimate_size_increase(self, config: LayerConfig) -> float:
        return 1.4 + config.intensity * 0.6


def _flow_walk(ast: dict, config: LayerConfig, stats: LayerStats) -> dict:
    """Walk AST and apply control flow obfuscation."""
    if not isinstance(ast, dict):
        return ast

    rng = config.rng
    node_type = ast.get("type", "")
    stats.nodes_visited += 1

    # ── Independent block reordering ──
    if node_type == "script":
        body = ast.get("body", [])
        if len(body) > 2 and rng.random() < config.intensity:
            ast["body"] = _reorder_independent_blocks(body, rng)
            stats.blocks_reordered += 1
            stats.nodes_modified += 1

    # ── Opaque predicate wrapping ──
    if node_type == "command" and rng.random() < config.intensity * 0.3:
        ast = _wrap_opaque_predicate(ast, rng)
        stats.nodes_modified += 1

    # ── Subshell wrapping ──
    if (node_type == "command"
            and rng.random() < config.intensity * 0.2
            and not _has_variable_escape(ast)):
        ast = _wrap_subshell(ast)
        stats.nodes_modified += 1

    # ── Function extraction ──
    if node_type == "script":
        body = ast.get("body", [])
        if len(body) > 3 and rng.random() < config.intensity * 0.4:
            ast["body"] = _extract_functions(body, rng)
            stats.nodes_modified += 1

    # Recurse
    for key in ("parts", "body", "test_parts"):
        val = ast.get(key)
        if isinstance(val, list):
            ast[key] = [_flow_walk(i, config, stats) if isinstance(i, dict) else i for i in val]
        elif isinstance(val, dict):
            ast[key] = _flow_walk(val, config, stats)

    return ast


_VAR_REF_RE = re.compile(r'\$\{?!?#?([a-zA-Z_]\w*)')

_BARRIER_COMMANDS = frozenset({
    "exit", "return", "break", "continue",
    "trap", "exec", "shift",
    ".", "source",                       # may load globals at unknown order
    "set", "shopt", "ulimit", "umask",   # global state
    "cd", "pushd", "popd",               # CWD-dependent
})


def _is_control_flow_barrier(node: dict) -> bool:
    """True if reordering past this node would break script semantics.

    Conservative: ANY command except pure variable assignments is a barrier,
    because most commands have I/O side effects whose order is observable
    (stdout, stderr, file writes, signals, network calls). Reordering only
    pure assignments is statically safe; everything else is risky.
    """
    if not isinstance(node, dict):
        return False
    if node.get("type") == "command":
        parts = node.get("parts") or []
        # Pure assignment block: every part is type=='assignment'
        if parts and all(
            isinstance(p, dict) and p.get("type") == "assignment"
            for p in parts
        ):
            return False  # safe to reorder
        # Any other command (echo, printf, cat, custom function, etc.)
        # has observable side effects — barrier.
        return True
    # Compound constructs (if / while / for / case / function / subshell etc.)
    if node.get("type") in ("compound", "function_def", "list", "pipeline"):
        return True
    return False


def _get_var_refs(node: dict) -> set[str]:
    """Collect all variable references (READS) from a node tree.

    Notes:
      - Assignment NAMEs are writes, not reads — we scan the assignment
        VALUE for $-references instead.
      - Word values are scanned with the same regex (covers the
        opaque-blob fallback case where bashlex couldn't parse).
    """
    refs: set[str] = set()

    def _walk(n: dict) -> None:
        if not isinstance(n, dict):
            return
        refs.update(n.get("var_refs", []))
        if n.get("type") == "assignment":
            value = n.get("value", "")
            if isinstance(value, str):
                refs.update(_VAR_REF_RE.findall(value))
        if n.get("type") == "expansion" and n.get("kind") == "parameter":
            v = n.get("value", "")
            if isinstance(v, str):
                refs.add(v)
        if n.get("type") == "word":
            value = n.get("value", "")
            if isinstance(value, str):
                refs.update(_VAR_REF_RE.findall(value))
        for key in ("parts", "body", "test_parts"):
            val = n.get(key)
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        _walk(item)
            elif isinstance(val, dict):
                _walk(val)
    _walk(node)
    return refs


def _get_var_writes(node: dict) -> set[str]:
    """Collect all variable assignments from a node tree."""
    writes: set[str] = set()

    def _walk(n: dict) -> None:
        if not isinstance(n, dict):
            return
        if n.get("type") == "assignment":
            writes.add(n.get("name", ""))
        for key in ("parts", "body", "test_parts"):
            val = n.get(key)
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        _walk(item)
            elif isinstance(val, dict):
                _walk(val)
    _walk(node)
    return writes


def _reorder_independent_blocks(body: list[dict], rng: random.Random) -> list[dict]:
    """Reorder blocks that have no data dependencies on each other."""
    # Build dependency info for each block
    blocks = []
    for node in body:
        reads = _get_var_refs(node) - _get_var_writes(node)
        writes = _get_var_writes(node)
        is_barrier = _is_control_flow_barrier(node)
        blocks.append({
            "node": node, "reads": reads, "writes": writes,
            "barrier": is_barrier,
        })

    # Find groups of independent blocks (no shared variables, no barrier)
    result: list[dict] = []
    independent_group: list[dict] = []

    for i, block in enumerate(blocks):
        can_reorder = True
        # Control-flow barriers (exit, return, break, continue, trap)
        # MUST keep their original position relative to surrounding blocks.
        if block["barrier"]:
            can_reorder = False
        for other in independent_group:
            # Check if this block depends on any block in the group
            if (block["reads"] & other["writes"]
                    or block["writes"] & other["reads"]
                    or block["writes"] & other["writes"]
                    or other["barrier"]):
                can_reorder = False
                break

        if can_reorder:
            independent_group.append(block)
        else:
            # Flush the current group (shuffled)
            if independent_group:
                rng.shuffle(independent_group)
                result.extend(b["node"] for b in independent_group)
            independent_group = [block]

    # Flush remaining
    if independent_group:
        rng.shuffle(independent_group)
        result.extend(b["node"] for b in independent_group)

    return result


def _wrap_opaque_predicate(node: dict, rng: random.Random) -> dict:
    """Wrap a command in an opaque predicate (always true)."""
    predicates = [
        '[[ $(( 0x7f ^ 0x7f )) -eq 0 ]]',
        '[[ $(( 1 + 1 )) -eq 2 ]]',
        '[[ $(( 0xFF & 0xFF )) -ne 0 ]]',
        '[[ -z "" ]]',
        '[[ $(( 42 % 42 )) -eq 0 ]]',
        '[[ $(( 0xDEAD ^ 0xDEAD )) -eq 0 ]]',
    ]
    predicate = rng.choice(predicates)

    return {
        "type": "compound",
        "kind": "if",
        "parts": [
            {
                "type": "command",
                "parts": [{"type": "word", "value": predicate, "pos": None}],
                "pos": None,
            },
            node,
        ],
        "pos": None,
        "_opaque": True,
    }


def _has_variable_escape(node: dict) -> bool:
    """Check if a command modifies variables that escape its scope."""
    writes = _get_var_writes(node)
    # If it assigns to variables, it might need to be in the parent scope
    return bool(writes)


def _wrap_subshell(node: dict) -> dict:
    """Wrap a command in a subshell."""
    return {
        "type": "compound",
        "kind": "(",
        "parts": [node],
        "pos": None,
    }


def _extract_functions(body: list[dict], rng: random.Random) -> list[dict]:
    """Extract random blocks into functions, then call them."""
    if len(body) < 4:
        return body

    # Pick 1-2 blocks to extract
    extractable = [
        i for i, node in enumerate(body)
        if (isinstance(node, dict)
            and node.get("type") == "command"
            and not _has_variable_escape(node))
    ]

    if not extractable:
        return body

    count = min(len(extractable), rng.randint(1, 2))
    chosen = rng.sample(extractable, count)

    new_body: list[dict] = []
    extracted_functions: list[dict] = []

    for i, node in enumerate(body):
        if i in chosen:
            # Create function
            fname = f"_blk_{rng.randint(0x100, 0xffff):04x}"
            func_def = {
                "type": "function_def",
                "name": fname,
                "body": {
                    "type": "compound",
                    "kind": "{",
                    "parts": [node],
                    "pos": None,
                },
                "pos": None,
            }
            extracted_functions.append(func_def)

            # Replace with function call
            call = {
                "type": "command",
                "parts": [{"type": "word", "value": fname, "pos": None}],
                "pos": None,
            }
            new_body.append(call)
        else:
            new_body.append(node)

    # Prepend extracted functions
    return extracted_functions + new_body
