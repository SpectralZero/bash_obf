"""
Layer 2: String Shredding

Transforms every readable string literal into an obfuscated equivalent.
No readable string appears in the output.
"""

from __future__ import annotations

import re
from typing import Any

from obfush.layers.base import Layer, LayerConfig, LayerStats
from obfush.utils.string_utils import random_shred, to_hex_escape


class LayerImpl(Layer):
    name = "str-shred"
    description = "String literal fragmentation"

    # Strings shorter than this are always shredded
    MIN_SHRED_LEN = 1
    # Strings we never touch
    SKIP_PATTERNS = frozenset({"", " ", "\n", "\t"})

    def transform(self, ast: dict, config: LayerConfig) -> tuple[dict, LayerStats]:
        stats = LayerStats()
        rng = config.rng
        ast = _shred_walk(ast, config, stats)
        return ast, stats

    def estimate_size_increase(self, config: LayerConfig) -> float:
        return 1.5 + config.intensity * 1.5  # up to 3x at max intensity


# Patterns that should NOT be shredded
_SHEBANG_RE = re.compile(r'^#!')
_FORMAT_SPEC_RE = re.compile(r'%[-+0 #]*\d*\.?\d*[diouxXeEfFgGaAcspn%]')
_GLOB_RE = re.compile(r'[*?\[\]]')


def _should_shred(value: str, node: dict) -> bool:
    """Decide whether a string value should be shredded."""
    if not value or value in LayerImpl.SKIP_PATTERNS:
        return False
    if _SHEBANG_RE.match(value):
        return False
    # Don't shred single-char operator-like strings
    if len(value) == 1 and value in "=<>|&;(){}!":
        return False
    # Don't shred flag arguments (they break command parsing)
    if value.startswith("-") and len(value) <= 4:
        return False
    # Don't shred raw/opaque nodes
    if node.get("raw") and node.get("value") == node.get("raw"):
        return False
    # Don't shred pre-rendered shell syntax — opaque predicates [[ ... ]],
    # arithmetic (( ... )), assignments name=val, command-substitution
    # eval chains, etc.  Shredding the whole construct as one literal
    # string corrupts it.
    if _is_shell_syntax_value(value):
        return False
    # Don't shred strings that contain shell expansions ($var, ${var},
    # $(cmd), `cmd`).  Methods like base64-decode-via-substitution do not
    # re-trigger expansion on the result, so the variables stay literal.
    if "$" in value or "`" in value:
        return False
    return True


def _is_shell_syntax_value(value: str) -> bool:
    """Return True for word values that are pre-rendered shell constructs."""
    if value.startswith("[[") and value.endswith("]]"):
        return True
    if value.startswith("((") and value.endswith("))"):
        return True
    if value.startswith("[ ") and value.endswith(" ]"):
        return True
    # Assignments and array literals
    if re.match(r'^[a-zA-Z_]\w*\+?=', value):
        return True
    # eval / bash -c chains emitted by the encode layer
    if re.search(r'\beval\s+["\'$]', value):
        return True
    if re.search(r'\bbash\s+-c\b', value):
        return True
    return False


def _shred_value(value: str, config: LayerConfig) -> str | tuple[list[str], str]:
    """Shred a string value, respecting format specifiers and globs."""
    rng = config.rng

    # If it contains glob patterns, only shred non-glob parts
    if _GLOB_RE.search(value):
        return _shred_with_globs(value, config)

    # If it contains format specifiers, shred around them
    if _FORMAT_SPEC_RE.search(value):
        return _shred_with_format_specs(value, config)

    return random_shred(value, rng, config.eval_mode)


def _shred_with_globs(value: str, config: LayerConfig) -> str:
    """Shred a string while preserving glob patterns."""
    parts: list[str] = []
    last_end = 0

    for match in _GLOB_RE.finditer(value):
        start, end = match.span()
        if start > last_end:
            segment = value[last_end:start]
            result = random_shred(segment, config.rng, config.eval_mode)
            if isinstance(result, tuple):
                # Variable reconstruction — just use hex for globs
                parts.append(to_hex_escape(segment))
            else:
                parts.append(result)
        parts.append(match.group())  # preserve glob char
        last_end = end

    if last_end < len(value):
        segment = value[last_end:]
        result = random_shred(segment, config.rng, config.eval_mode)
        if isinstance(result, tuple):
            parts.append(to_hex_escape(segment))
        else:
            parts.append(result)

    return "".join(parts)


def _shred_with_format_specs(value: str, config: LayerConfig) -> str:
    """Shred a string while preserving printf format specifiers."""
    parts: list[str] = []
    last_end = 0

    for match in _FORMAT_SPEC_RE.finditer(value):
        start, end = match.span()
        if start > last_end:
            segment = value[last_end:start]
            result = random_shred(segment, config.rng, config.eval_mode)
            if isinstance(result, tuple):
                parts.append(to_hex_escape(segment))
            else:
                parts.append(result)
        parts.append(match.group())  # preserve format spec
        last_end = end

    if last_end < len(value):
        segment = value[last_end:]
        result = random_shred(segment, config.rng, config.eval_mode)
        if isinstance(result, tuple):
            parts.append(to_hex_escape(segment))
        else:
            parts.append(result)

    return "".join(parts)


def _shred_walk(ast: dict, config: LayerConfig, stats: LayerStats) -> dict:
    """Walk the AST and shred string literals."""
    if not isinstance(ast, dict):
        return ast

    node_type = ast.get("type", "")

    # Shred word values
    if node_type == "word" and not ast.get("parts"):
        value = ast.get("value", "")
        if _should_shred(value, ast):
            result = _shred_value(value, config)
            if isinstance(result, tuple):
                # Variable reconstruction: store setup + expression
                assignments, expr = result
                ast["value"] = expr
                ast["_shred_setup"] = assignments
            else:
                ast["value"] = result
            stats.strings_shredded += 1
            stats.nodes_modified += 1

    # Shred assignment values
    if node_type == "assignment":
        value = ast.get("value", "")
        if isinstance(value, str) and _should_shred(value, ast):
            result = _shred_value(value, config)
            if isinstance(result, tuple):
                assignments, expr = result
                ast["value"] = expr
                ast["_shred_setup"] = assignments
            else:
                ast["value"] = result
            stats.strings_shredded += 1
            stats.nodes_modified += 1

    # Shred heredoc bodies line-by-line
    if node_type == "heredoc":
        body = ast.get("body", "")
        if body:
            lines = body.split("\n")
            shredded_lines = []
            for line in lines:
                if line.strip() and _should_shred(line, ast):
                    result = random_shred(line, config.rng, config.eval_mode)
                    if isinstance(result, tuple):
                        shredded_lines.append(to_hex_escape(line))
                    else:
                        shredded_lines.append(result)
                    stats.strings_shredded += 1
                else:
                    shredded_lines.append(line)
            ast["body"] = "\n".join(shredded_lines)

    stats.nodes_visited += 1

    # Recurse
    for key in ("parts", "body", "test_parts"):
        val = ast.get(key)
        if isinstance(val, list):
            ast[key] = [_shred_walk(i, config, stats) if isinstance(i, dict) else i for i in val]
        elif isinstance(val, dict):
            ast[key] = _shred_walk(val, config, stats)

    return ast
