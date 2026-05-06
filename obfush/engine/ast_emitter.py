"""
AST emitter — converts the internal AST back to valid bash source code.

Walks the AST recursively and produces properly quoted, escaped,
and formatted bash that is syntactically valid.
"""

from __future__ import annotations

from typing import Any


def emit(ast: dict) -> str:
    """Convert AST to bash source code.

    Args:
        ast: Internal AST (root should be type='script').

    Returns:
        Valid bash source code string.
    """
    lines: list[str] = []

    # Shebang
    shebang = ast.get("shebang")
    if shebang:
        lines.append(shebang)

    # Emit body
    body = ast.get("body", [])
    for node in body:
        result = _emit_node(node)
        if result:
            lines.append(result)

    return "\n".join(lines) + "\n"


def _emit_node(node: dict, depth: int = 0) -> str:
    """Emit a single AST node as bash source."""
    if not isinstance(node, dict):
        return str(node)

    node_type = node.get("type", "")

    emitter = _EMITTERS.get(node_type, _emit_raw)
    return emitter(node, depth)


def _emit_script(node: dict, depth: int) -> str:
    parts = []
    for child in node.get("body", []):
        parts.append(_emit_node(child, depth))
    return "\n".join(parts)


def _emit_command(node: dict, depth: int) -> str:
    parts = node.get("parts", [])
    words = [_emit_node(p, depth) for p in parts]
    result = " ".join(w for w in words if w)
    return result


def _emit_word(node: dict, depth: int) -> str:
    # If there's a raw field (opaque/fallback node), use it
    if "raw" in node and node.get("value", "") == node.get("raw", ""):
        return node["raw"]
    return node.get("value", "")


def _emit_assignment(node: dict, depth: int) -> str:
    name = node.get("name", "")
    value = node.get("value", "")
    if isinstance(value, dict):
        value = _emit_node(value, depth)
    # If value is empty and name looks like it contains the full assignment
    # (e.g., bashlex kept it as name='x="hello"'), reconstruct properly
    if not value and "=" in name:
        return name  # Already in name=value form
    # Ensure value is properly quoted if it's a bare string with spaces
    if value and not value.startswith(('"', "'", '$', '(', '`')):
        if ' ' in value or '\t' in value:
            value = f'"{value}"'
    return f"{name}={value}"


def _emit_list(node: dict, depth: int) -> str:
    parts = node.get("parts", [])
    result_parts: list[str] = []
    for part in parts:
        if part.get("type") == "operator":
            result_parts.append(part.get("op", ";"))
        else:
            result_parts.append(_emit_node(part, depth))

    # Join with spaces (operators already included)
    return " ".join(result_parts)


def _emit_pipeline(node: dict, depth: int) -> str:
    parts = node.get("parts", [])
    commands = [_emit_node(p, depth) for p in parts]
    return " | ".join(commands)


def _emit_compound(node: dict, depth: int) -> str:
    kind = node.get("kind", "group")
    parts = node.get("parts", [])
    inner = "\n".join(_emit_node(p, depth + 1) for p in parts)

    if kind == "group" or kind == "{":
        return "{\n" + inner + "\n}"
    elif kind == "(":
        return "(\n" + inner + "\n)"
    elif kind == "if":
        return _emit_if_compound(node, depth)
    elif kind == "for":
        return _emit_for_compound(node, depth)
    elif kind == "while":
        return _emit_while_compound(node, depth)
    elif kind == "until":
        return _emit_until_compound(node, depth)
    elif kind == "case":
        return _emit_case_compound(node, depth)
    elif kind == "[[":
        return "[[ " + inner + " ]]"
    else:
        return inner


def _emit_if_compound(node: dict, depth: int) -> str:
    """Emit if/then/else/elif/fi structure."""
    parts = node.get("parts", [])
    if not parts:
        return "if true; then\n:\nfi"

    lines = []
    i = 0
    keyword = "if"
    while i < len(parts):
        condition = _emit_node(parts[i], depth + 1)
        lines.append(f"{keyword} {condition}; then")
        i += 1
        if i < len(parts):
            body = _emit_node(parts[i], depth + 1)
            lines.append(body)
            i += 1
        # Check for elif
        if i < len(parts) and i + 1 < len(parts):
            keyword = "elif"
        elif i < len(parts):
            lines.append("else")
            lines.append(_emit_node(parts[i], depth + 1))
            i += 1

    lines.append("fi")
    return "\n".join(lines)


def _emit_for_compound(node: dict, depth: int) -> str:
    var = node.get("variable", "i")
    items = node.get("items", "")
    parts = node.get("parts", [])
    body = "\n".join(_emit_node(p, depth + 1) for p in parts)
    return f"for {var} in {items}; do\n{body}\ndone"


def _emit_while_compound(node: dict, depth: int) -> str:
    parts = node.get("parts", [])
    if len(parts) >= 2:
        condition = _emit_node(parts[0], depth + 1)
        body = "\n".join(_emit_node(p, depth + 1) for p in parts[1:])
        return f"while {condition}; do\n{body}\ndone"
    body = "\n".join(_emit_node(p, depth + 1) for p in parts)
    return f"while true; do\n{body}\ndone"


def _emit_until_compound(node: dict, depth: int) -> str:
    parts = node.get("parts", [])
    if len(parts) >= 2:
        condition = _emit_node(parts[0], depth + 1)
        body = "\n".join(_emit_node(p, depth + 1) for p in parts[1:])
        return f"until {condition}; do\n{body}\ndone"
    return "until true; do\n:\ndone"


def _emit_case_compound(node: dict, depth: int) -> str:
    word = node.get("word", "$1")
    parts = node.get("parts", [])
    lines = [f"case {word} in"]
    for part in parts:
        pattern = part.get("pattern", "*")
        body = _emit_node(part.get("body", {}), depth + 1)
        lines.append(f"  {pattern})")
        lines.append(f"    {body}")
        lines.append("    ;;")
    lines.append("esac")
    return "\n".join(lines)


def _emit_function_def(node: dict, depth: int) -> str:
    name = node.get("name", "func")
    body = node.get("body", {})
    body_str = _emit_node(body, depth + 1)
    return f"{name}() {{\n{body_str}\n}}"


def _emit_redirect(node: dict, depth: int) -> str:
    rtype = node.get("redirect_type", ">")
    target = node.get("target", "")
    if isinstance(target, dict):
        target = _emit_node(target, depth)
    fd = node.get("fd")

    heredoc = node.get("heredoc")
    if heredoc:
        delim = heredoc.get("delimiter", "EOF")
        body = heredoc.get("body", "")
        fd_str = f"{fd}" if fd is not None else ""
        return f"{fd_str}<<{delim}\n{body}\n{delim}"

    fd_str = f"{fd}" if fd is not None else ""
    return f"{fd_str}{rtype}{target}"


def _emit_heredoc(node: dict, depth: int) -> str:
    delim = node.get("delimiter", "EOF")
    body = node.get("body", "")
    return f"<<{delim}\n{body}\n{delim}"


def _emit_expansion(node: dict, depth: int) -> str:
    kind = node.get("kind", "")
    value = node.get("value", "")
    parts = node.get("parts", [])

    if kind == "parameter":
        return f"${{{value}}}"
    elif kind == "command_sub":
        if parts:
            inner = _emit_node(parts[0], depth)
            return f"$({inner})"
        return f"$({value})"
    elif kind == "process_sub":
        if parts:
            inner = _emit_node(parts[0], depth)
            return f"<({inner})"
        return f"<({value})"
    elif kind == "arithmetic":
        return f"$(({value}))"
    elif kind == "tilde":
        return value if value else "~"
    else:
        return value


def _emit_operator(node: dict, depth: int) -> str:
    return node.get("op", ";")


def _emit_test_expr(node: dict, depth: int) -> str:
    style = node.get("original_style", "[[")
    test_parts = node.get("test_parts", [])
    parts = node.get("parts", [])

    inner_parts = test_parts or parts
    inner = " ".join(_emit_node(p, depth) for p in inner_parts)

    if style == "[[":
        return f"[[ {inner} ]]"
    elif style == "[":
        return f"[ {inner} ]"
    elif style == "test":
        return f"test {inner}"
    else:
        return f"[[ {inner} ]]"


def _emit_raw(node: dict, depth: int) -> str:
    """Fallback emitter — try to reconstruct from available data."""
    if "raw" in node:
        return node["raw"]
    if "value" in node:
        return str(node["value"])
    # Last resort: emit parts
    parts = node.get("parts", [])
    if parts:
        return " ".join(_emit_node(p, depth) for p in parts)
    return ""


# Emitter dispatch table
_EMITTERS: dict[str, Any] = {
    "script": _emit_script,
    "command": _emit_command,
    "word": _emit_word,
    "assignment": _emit_assignment,
    "list": _emit_list,
    "pipeline": _emit_pipeline,
    "compound": _emit_compound,
    "function_def": _emit_function_def,
    "redirect": _emit_redirect,
    "heredoc": _emit_heredoc,
    "expansion": _emit_expansion,
    "operator": _emit_operator,
    "test_expr": _emit_test_expr,
}
