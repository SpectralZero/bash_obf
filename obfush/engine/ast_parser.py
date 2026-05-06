"""
Bash AST parser — wraps bashlex and converts to internal AST format.

Internal AST nodes are plain dicts with a 'type' key.  This makes them
JSON-serialisable, easy to inspect, and trivial to copy/modify.

Fallback: For constructs bashlex can't handle (arithmetic $((...)),
complex parameter expansions ${param#word}), a regex-based extractor
preserves them as opaque 'word' nodes with a 'raw' field.
"""

from __future__ import annotations

import re
from typing import Any

import bashlex
import bashlex.ast


# ──────────────────────────────────────────────────────────────────────
# Internal AST node constructors
# ──────────────────────────────────────────────────────────────────────

def _node(type_: str, **kwargs: Any) -> dict:
    """Create an AST node dict."""
    return {"type": type_, **kwargs}


def _script(body: list[dict]) -> dict:
    return _node("script", body=body)


def _command(parts: list[dict], pos: tuple[int, int] | None = None) -> dict:
    return _node("command", parts=parts, pos=pos)


def _word(value: str, pos: tuple[int, int] | None = None,
          parts: list[dict] | None = None, raw: str | None = None) -> dict:
    n = _node("word", value=value, pos=pos)
    if parts:
        n["parts"] = parts
    if raw:
        n["raw"] = raw
    return n


def _list_node(parts: list[dict], op: str = ";",
               pos: tuple[int, int] | None = None) -> dict:
    return _node("list", parts=parts, op=op, pos=pos)


def _pipeline(parts: list[dict], pos: tuple[int, int] | None = None) -> dict:
    return _node("pipeline", parts=parts, pos=pos)


def _compound(kind: str, parts: list[dict],
              pos: tuple[int, int] | None = None, **kwargs: Any) -> dict:
    return _node("compound", kind=kind, parts=parts, pos=pos, **kwargs)


def _function_def(name: str, body: dict,
                  pos: tuple[int, int] | None = None) -> dict:
    return _node("function_def", name=name, body=body, pos=pos)


def _assignment(name: str, value: str | dict,
                pos: tuple[int, int] | None = None) -> dict:
    return _node("assignment", name=name, value=value, pos=pos)


def _redirect(type_: str, target: str | dict, fd: int | None = None,
              pos: tuple[int, int] | None = None, heredoc: dict | None = None) -> dict:
    n = _node("redirect", redirect_type=type_, target=target, fd=fd, pos=pos)
    if heredoc:
        n["heredoc"] = heredoc
    return n


def _heredoc(body: str, delimiter: str,
             pos: tuple[int, int] | None = None) -> dict:
    return _node("heredoc", body=body, delimiter=delimiter, pos=pos)


def _expansion(kind: str, value: str, parts: list[dict] | None = None,
               pos: tuple[int, int] | None = None) -> dict:
    n = _node("expansion", kind=kind, value=value, pos=pos)
    if parts:
        n["parts"] = parts
    return n


def _operator(op: str, pos: tuple[int, int] | None = None) -> dict:
    return _node("operator", op=op, pos=pos)


# ──────────────────────────────────────────────────────────────────────
# bashlex AST → internal AST converter
# ──────────────────────────────────────────────────────────────────────

def _convert_node(node: Any) -> dict:
    """Recursively convert a bashlex AST node to internal format."""
    kind = node.kind

    if kind == "word":
        parts = []
        if hasattr(node, "parts") and node.parts:
            parts = [_convert_node(p) for p in node.parts]

        # Detect assignments: word contains '=' and is first in command
        word_val = node.word
        return _word(word_val, pos=node.pos, parts=parts if parts else None)

    elif kind == "command":
        parts = [_convert_node(p) for p in node.parts]
        return _command(parts, pos=node.pos)

    elif kind == "list":
        parts = [_convert_node(p) for p in node.parts]
        return _list_node(parts, pos=node.pos)

    elif kind == "operator":
        return _operator(node.op, pos=node.pos)

    elif kind in ("pipe", "pipeline"):
        child_nodes = []
        if hasattr(node, "parts") and node.parts:
            child_nodes = node.parts
        elif hasattr(node, "pipe") and node.pipe:
            child_nodes = node.pipe
        # Some bashlex versions store pipe components as direct list attribute
        if not child_nodes:
            for attr in dir(node):
                val = getattr(node, attr, None)
                if (isinstance(val, list) and val
                        and not isinstance(val[0], str)
                        and hasattr(val[0], "kind")):
                    child_nodes = val
                    break
        # Filter out string tokens (e.g., '|') — only convert node objects
        parts = [
            _convert_node(p) for p in child_nodes
            if not isinstance(p, str) and hasattr(p, "kind")
        ]
        return _pipeline(parts, pos=node.pos)

    elif kind == "compound":
        parts = []
        if hasattr(node, "list") and node.list:
            parts = [_convert_node(p) for p in node.list]
        elif hasattr(node, "parts") and node.parts:
            parts = [_convert_node(p) for p in node.parts]
        return _compound(
            kind=getattr(node, "compound_kind", "group"),
            parts=parts, pos=node.pos,
        )

    elif kind == "function":
        # bashlex: node.name is a WordNode, node.body is the compound block.
        name_node = getattr(node, "name", None)
        name = getattr(name_node, "word", "") if name_node is not None else ""
        body_node = getattr(node, "body", None)
        body = _convert_node(body_node) if body_node is not None else _node("noop")
        return _function_def(name=name, body=body, pos=node.pos)

    elif kind == "redirect":
        redirect_type = getattr(node, "type", ">")
        target = node.output if hasattr(node, "output") else ""
        fd = getattr(node, "input", None)
        heredoc = None
        if hasattr(node, "heredoc"):
            heredoc = _heredoc(
                body=node.heredoc.value if hasattr(node.heredoc, "value") else str(node.heredoc),
                delimiter=getattr(node.heredoc, "delimiter", "EOF"),
            )
        return _redirect(redirect_type, target, fd=fd, pos=node.pos, heredoc=heredoc)

    elif kind == "commandsubstitution":
        command = _convert_node(node.command) if hasattr(node, "command") else _node("noop")
        return _expansion("command_sub", value="", parts=[command], pos=node.pos)

    elif kind == "processsubstitution":
        command = _convert_node(node.command) if hasattr(node, "command") else _node("noop")
        return _expansion("process_sub", value="", parts=[command], pos=node.pos)

    elif kind == "parameter":
        value = node.value if hasattr(node, "value") else ""
        return _expansion("parameter", value=value, pos=node.pos)

    elif kind == "tilde":
        value = node.value if hasattr(node, "value") else "~"
        return _expansion("tilde", value=value, pos=node.pos)

    elif kind == "heredoc":
        body = node.value if hasattr(node, "value") else ""
        delimiter = getattr(node, "delimiter", "EOF")
        return _heredoc(body=body, delimiter=delimiter, pos=node.pos)

    elif kind == "assignment":
        # bashlex stores assignments as a single .word like 'name=value';
        # .name/.value are not populated — split it ourselves.
        word = getattr(node, "word", "") or ""
        if "=" in word:
            name, _, value = word.partition("=")
        else:
            name, value = word, ""
        return _assignment(name=name, value=value, pos=node.pos)

    else:
        # Unknown node — preserve as opaque word with raw content
        raw = str(node) if node else ""
        return _word(value=raw, pos=getattr(node, "pos", None), raw=raw)


# ──────────────────────────────────────────────────────────────────────
# Fallback parser for bashlex failures
# ──────────────────────────────────────────────────────────────────────

# Patterns bashlex can't handle
_ARITHMETIC_RE = re.compile(r'\$\(\(.*?\)\)', re.DOTALL)
_COMPLEX_PARAM_RE = re.compile(r'\$\{[^}]*[#%/!@:^,].*?\}', re.DOTALL)


def _preprocess_for_bashlex(source: str) -> tuple[str, dict[str, str]]:
    """Replace constructs bashlex can't parse with placeholders.

    Returns the processed source and a mapping of placeholder → original.
    """
    placeholders: dict[str, str] = {}
    counter = [0]

    def _replace(match: re.Match) -> str:
        placeholder = f"__OBFUSH_PH_{counter[0]:04d}__"
        counter[0] += 1
        placeholders[placeholder] = match.group(0)
        return placeholder

    processed = source
    processed = _ARITHMETIC_RE.sub(_replace, processed)
    processed = _COMPLEX_PARAM_RE.sub(_replace, processed)

    return processed, placeholders


def _restore_placeholders(ast: dict, placeholders: dict[str, str]) -> dict:
    """Walk AST and restore placeholder strings to their original form."""
    if not placeholders:
        return ast

    def _walk(node: dict) -> dict:
        if not isinstance(node, dict):
            return node

        # Check string values for placeholders
        for key in ("value", "name", "target", "body", "op"):
            if key in node and isinstance(node[key], str):
                for ph, original in placeholders.items():
                    if ph in node[key]:
                        node[key] = node[key].replace(ph, original)
                        if "raw" not in node:
                            node["raw"] = original

        # Recurse into child nodes
        for key in ("parts", "body"):
            if key in node:
                val = node[key]
                if isinstance(val, list):
                    node[key] = [_walk(item) if isinstance(item, dict) else item for item in val]
                elif isinstance(val, dict):
                    node[key] = _walk(val)

        return node

    return _walk(ast)


# ──────────────────────────────────────────────────────────────────────
# Detection of assignments in command parts
# ──────────────────────────────────────────────────────────────────────

_ASSIGNMENT_RE = re.compile(r'^([a-zA-Z_][a-zA-Z0-9_]*)=(.*)', re.DOTALL)


def _detect_assignments(ast: dict) -> dict:
    """Post-process to detect variable assignments in word nodes.

    bashlex doesn't always separate assignments; they appear as word
    nodes with 'var=value' content.  We detect and promote them.
    """
    def _walk(node: dict) -> dict:
        if not isinstance(node, dict):
            return node

        if node.get("type") == "command":
            new_parts = []
            for part in node.get("parts", []):
                if part.get("type") == "word":
                    match = _ASSIGNMENT_RE.match(part.get("value", ""))
                    if match and not part.get("parts"):
                        new_parts.append(_assignment(
                            name=match.group(1),
                            value=match.group(2),
                            pos=part.get("pos"),
                        ))
                        continue
                new_parts.append(_walk(part))
            node["parts"] = new_parts

        for key in ("parts", "body"):
            if key in node:
                val = node[key]
                if isinstance(val, list):
                    node[key] = [_walk(i) if isinstance(i, dict) else i for i in val]
                elif isinstance(val, dict):
                    node[key] = _walk(val)

        return node

    return _walk(ast)


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────

def parse_bash(source: str) -> dict:
    """Parse bash source into the internal AST format.

    Uses bashlex as primary parser, with regex fallback for unsupported
    constructs (arithmetic expressions, complex parameter expansions).

    Args:
        source: Bash script source code.

    Returns:
        Root AST node (type='script').
    """
    # Strip shebang for parsing, we'll re-add it in the emitter
    shebang = None
    lines = source.split("\n")
    if lines and lines[0].startswith("#!"):
        shebang = lines[0]
        parse_source = "\n".join(lines[1:])
    else:
        parse_source = source

    # Pre-process to handle bashlex limitations
    processed, placeholders = _preprocess_for_bashlex(parse_source)

    # Parse with bashlex
    try:
        parts = bashlex.parse(processed)
    except Exception as e:
        # Total fallback: treat the entire script as a single opaque node
        return _script(body=[_word(
            value=source, raw=source,
            pos=(0, len(source)),
        )])

    # Convert bashlex AST to internal format
    body = [_convert_node(part) for part in parts]

    # Restore placeholders
    ast = _script(body=body)
    ast = _restore_placeholders(ast, placeholders)

    # Detect assignments
    ast = _detect_assignments(ast)

    # Preserve shebang
    if shebang:
        ast["shebang"] = shebang

    return ast
