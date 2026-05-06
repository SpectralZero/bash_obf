"""
Layer 3: Command Substitution & Syntax Morphing

Replaces commands and syntax with equivalent but structurally different
alternatives. Every substitution is semantically equivalent.
"""

from __future__ import annotations

from typing import Any

from obfush.layers.base import Layer, LayerConfig, LayerStats


class LayerImpl(Layer):
    name = "cmd-sub"
    description = "Syntax & command substitution"

    def transform(self, ast: dict, config: LayerConfig) -> tuple[dict, LayerStats]:
        stats = LayerStats()
        ast = _morph_walk(ast, config, stats)
        return ast, stats

    def estimate_size_increase(self, config: LayerConfig) -> float:
        return 1.2


def _morph_walk(ast: dict, config: LayerConfig, stats: LayerStats) -> dict:
    """Walk AST and apply command/syntax morphing."""
    if not isinstance(ast, dict):
        return ast

    rng = config.rng
    node_type = ast.get("type", "")
    stats.nodes_visited += 1

    # ── echo → printf / cat ──
    if node_type == "command":
        parts = ast.get("parts", [])
        if parts and parts[0].get("type") == "word" and parts[0].get("value") == "echo":
            if rng.random() < config.intensity:
                ast = _morph_echo(ast, rng)
                stats.commands_substituted += 1
                stats.nodes_modified += 1

    # ── source → . and vice versa ──
    if node_type == "command":
        parts = ast.get("parts", [])
        if parts and parts[0].get("type") == "word":
            cmd = parts[0].get("value", "")
            if cmd == "source" and rng.random() < config.intensity:
                parts[0]["value"] = "."
                stats.commands_substituted += 1
                stats.nodes_modified += 1
            elif cmd == "." and len(cmd) == 1 and rng.random() < config.intensity:
                parts[0]["value"] = "source"
                stats.commands_substituted += 1
                stats.nodes_modified += 1

    # ── true → : and vice versa ──
    if node_type == "command":
        parts = ast.get("parts", [])
        if parts and parts[0].get("type") == "word":
            cmd = parts[0].get("value", "")
            if cmd == "true" and rng.random() < config.intensity:
                parts[0]["value"] = ":"
                stats.commands_substituted += 1
            elif cmd == ":" and rng.random() < config.intensity * 0.5:
                parts[0]["value"] = "true"
                stats.commands_substituted += 1

    # ── $(cmd) ↔ `cmd` ──
    if node_type == "expansion" and ast.get("kind") == "command_sub":
        if rng.random() < config.intensity * 0.7:
            # Toggle the representation style
            current = ast.get("style", "dollar")
            ast["style"] = "backtick" if current == "dollar" else "dollar"
            stats.commands_substituted += 1

    # ── test expression style morphing ──
    if node_type == "test_expr":
        if rng.random() < config.intensity:
            ast = _morph_test(ast, rng)
            stats.commands_substituted += 1
            stats.nodes_modified += 1

    # ── > file → : > file ──
    if node_type == "redirect":
        rtype = ast.get("redirect_type", "")
        if rtype == ">" and rng.random() < config.intensity * 0.3:
            ast["_prepend_noop"] = True
            stats.commands_substituted += 1

    # Recurse
    for key in ("parts", "body", "test_parts"):
        val = ast.get(key)
        if isinstance(val, list):
            ast[key] = [_morph_walk(i, config, stats) if isinstance(i, dict) else i for i in val]
        elif isinstance(val, dict):
            ast[key] = _morph_walk(val, config, stats)

    return ast


def _morph_echo(ast: dict, rng: Any) -> dict:
    """Replace echo with printf or cat <<<."""
    parts = ast.get("parts", [])
    args = parts[1:] if len(parts) > 1 else []

    choice = rng.choice(["printf", "cat_herestring"])

    if choice == "printf":
        # echo "x" → printf '%s\n' "x"
        new_parts = [
            {"type": "word", "value": "printf", "pos": None},
            {"type": "word", "value": "'%s\\n'", "pos": None},
        ]
        new_parts.extend(args)
        ast["parts"] = new_parts

    elif choice == "cat_herestring":
        # echo "x" → cat <<< "x"
        # Only works for single-argument echo
        if len(args) == 1:
            new_parts = [
                {"type": "word", "value": "cat", "pos": None},
                {"type": "word", "value": "<<<", "pos": None},
            ]
            new_parts.extend(args)
            ast["parts"] = new_parts
        else:
            # Fall back to printf for multi-arg
            new_parts = [
                {"type": "word", "value": "printf", "pos": None},
                {"type": "word", "value": "'%s\\n'", "pos": None},
            ]
            new_parts.extend(args)
            ast["parts"] = new_parts

    return ast


def _morph_test(ast: dict, rng: Any) -> dict:
    """Morph test expression style: [ ] ↔ [[ ]] ↔ test."""
    current = ast.get("original_style", "[[")
    styles = ["[", "[[", "test"]
    styles = [s for s in styles if s != current]
    ast["original_style"] = rng.choice(styles)
    return ast
