"""
AST emitter — converts the internal AST back to valid bash source code.

Walks the AST recursively and produces properly quoted, escaped,
and formatted bash that is syntactically valid.
"""

from __future__ import annotations

import re
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
    # Opaque/fallback node: emit verbatim, never quote.
    # bashlex couldn't parse this region, so 'value' contains valid raw bash
    # text (possibly mutated by id-mangle's regex). Wrapping it in quotes
    # would turn it into a literal string and break execution.
    if "raw" in node:
        return node.get("value", node["raw"])
    value = node.get("value", "")
    if not value:
        return ""
    return _shell_quote(value)


# Characters that force a word to be quoted to preserve its meaning.
# Notably: whitespace, glob, redir, pipe, separator, control chars, escapes.
_QUOTE_REQUIRING = set(" \t\n\r*?[]{}()|&;<>#'\"\\`")


def _shell_quote(value: str) -> str:
    """Re-add shell quoting that bashlex stripped from literal-string words.

    Skips words that already contain shell syntax (assignments, command-subs,
    arrays, pre-quoted strings, eval chains). Only wraps "naked literal" words
    whose value contains characters bash would interpret on word-splitting.
    """
    # Already quoted? Leave alone.
    if (value.startswith('"') and value.endswith('"') and len(value) >= 2) or \
       (value.startswith("'") and value.endswith("'") and len(value) >= 2) or \
       (value.startswith("$'") and value.endswith("'") and len(value) >= 3) or \
       (value.startswith('$"') and value.endswith('"') and len(value) >= 3):
        return value

    # Word that mixes quoted segments with raw expansions:
    # e.g. str-shred emits  "Hello"$'\x20'"World"  or  $'\x68'"i"
    # Detect by presence of an opening quote anywhere AND no whitespace
    # outside quotes — these are valid concatenation expressions.
    if _is_quoted_concat(value):
        return value

    # Single self-delimiting expansion: ${...} / $(...) / `...`
    # Default to double-quoting variable expansions so the value is treated
    # as one word (preserves intended-quoted bash semantics; bashlex strips
    # the original quotes so we have to re-add a safe default).
    if value.startswith("${") and value.endswith("}") and "}" not in value[2:-1]:
        return f'"{value}"'
    if (value.startswith("$(") and value.endswith(")")) or \
       (value.startswith("`") and value.endswith("`")):
        return value

    # Words that are pre-rendered shell syntax — leave them verbatim.
    # Detected when the value contains any of these patterns that wouldn't
    # appear in a "literal string the user wrote in quotes".
    if _is_shell_syntax(value):
        return value

    # Otherwise this looks like a literal that bashlex stripped quotes from.
    needs_quote = any(ch in _QUOTE_REQUIRING for ch in value) or \
                  any(ord(ch) < 32 for ch in value) or \
                  any(ord(ch) > 127 for ch in value)
    if not needs_quote:
        return value

    has_expansion = "$" in value or "`" in value
    if has_expansion:
        # Don't escape $ — preserve expansions. Escape `\` and `"` only.
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    else:
        escaped = value.replace("'", "'\\''")
        return f"'{escaped}'"


def _is_quoted_concat(value: str) -> bool:
    """Detect mixed-quote concatenations like  "He"$'\\x6c\\x6c'"o"  or  $'\\x68'"i".

    These are valid bash word concatenations produced by str-shred. They must
    pass through verbatim — wrapping them in outer quotes breaks them.
    """
    if "'" not in value and '"' not in value:
        return False
    # Walk the value and ensure every char is inside SOME quote/escape segment
    # OR is a continuation between adjacent segments (zero whitespace outside).
    i = 0
    n = len(value)
    while i < n:
        ch = value[i]
        if ch == "'":
            # Find matching '
            j = value.find("'", i + 1)
            if j < 0:
                return False
            i = j + 1
        elif ch == '"':
            # Find matching " (respect \" escapes)
            j = i + 1
            while j < n:
                if value[j] == '\\' and j + 1 < n:
                    j += 2
                    continue
                if value[j] == '"':
                    break
                j += 1
            if j >= n:
                return False
            i = j + 1
        elif ch == "$" and i + 1 < n and value[i + 1] in ("'", '"'):
            # ANSI-C quote $'...' or locale-translated $"..."
            quote = value[i + 1]
            j = i + 2
            while j < n:
                if value[j] == '\\' and j + 1 < n:
                    j += 2
                    continue
                if value[j] == quote:
                    break
                j += 1
            if j >= n:
                return False
            i = j + 1
        elif ch == "$" and i + 1 < n and value[i + 1] == "(":
            # $(...) — find matching )
            depth = 1
            j = i + 2
            while j < n and depth > 0:
                if value[j] == '(':
                    depth += 1
                elif value[j] == ')':
                    depth -= 1
                j += 1
            if depth != 0:
                return False
            i = j
        elif ch in (" ", "\t", "\n"):
            return False  # bare whitespace = not a single concat word
        elif ch == "$" and i + 1 < n and value[i + 1] == "{":
            # ${var...} — find matching }
            j = value.find("}", i + 2)
            if j < 0:
                return False
            i = j + 1
        elif ch in "()|&;<>":
            # Bash metachars outside quotes break the "single word" property.
            return False
        else:
            # Permit any other "literal connector" between quoted segments:
            # letters, digits, %, -, +, /, =, ., ,, :, etc. These can
            # legitimately appear between concatenated quoted strings (e.g.
            # printf format specs like  %s$'\\x6e'  or  3+$'\\x34').
            i += 1
    return True


def _is_shell_syntax(value: str) -> bool:
    """Heuristic: does this word value contain pre-rendered shell syntax?

    True when the word looks like something a layer rendered (assignment,
    array literal, eval chain, conditional, redirection) rather than a
    quoted literal.
    """
    # Conditional / arithmetic constructs:  [[ ... ]]   ((  ...  ))   [ ... ]
    if value.startswith("[[") and value.endswith("]]"):
        return True
    if value.startswith("((") and value.endswith("))"):
        return True
    # Bracketed test that won't be confused with array index: starts with `[ `
    if value.startswith("[ ") and value.endswith(" ]"):
        return True
    # Array literal:  name=(...)  or  name+=(...)
    if re.search(r'^[a-zA-Z_]\w*\+?=\(', value):
        return True
    # Bare assignment with $ expansion:  name="..."  or  name=$(...)
    if re.search(r'^[a-zA-Z_]\w*\+?=', value) and ('$' in value or '`' in value or '"' in value or "'" in value):
        return True
    # Commands embedded as text (encode/cmd-sub layer output)
    if re.search(r'\beval\s+["\'$]', value):
        return True
    if re.search(r'\bbash\s+-c\s+["\'$]', value):
        return True
    # Pipeline-looking text:  cmd | cmd  or  cmd && cmd
    if re.search(r'\s\|\s|\s&&\s|\s\|\|\s', value):
        return True
    return False


def _emit_assignment(node: dict, depth: int) -> str:
    name = node.get("name", "")
    value = node.get("value", "")
    if isinstance(value, dict):
        value = _emit_node(value, depth)
    # If value is empty and name looks like it contains the full assignment
    # (e.g., bashlex kept it as name='x="hello"'), reconstruct properly
    if not value and "=" in name:
        return name  # Already in name=value form
    # Quoting policy:
    #   - Already quoted (' or "): leave as-is
    #   - Pure command substitution / arithmetic / process-sub starting the value:
    #     $(...), $((...)), `...`, <(...), >(...) — these self-delimit
    #   - Anything else with whitespace, glob chars, or non-ASCII: wrap in "..."
    if value and isinstance(value, str):
        already_quoted = (
            value.startswith(('"', "'"))
            or value.startswith("$'") or value.startswith('$"')
        )
        self_delim = (
            value.startswith("$(") or value.startswith("$((") or
            value.startswith("`") or value.startswith("<(") or value.startswith(">(")
        ) and (
            value.endswith(")") or value.endswith("`")
        ) and " " not in _strip_balanced(value)
        # If the value is a quoted concatenation (e.g. shred output:
        # "He"$'\\x6c\\x6c'"o"  or  $'\\x34\\x32'  or  %s$'\\x6e' ), pass through.
        is_concat = _is_quoted_concat(value)
        needs_quoting = (
            not already_quoted
            and not self_delim
            and not is_concat
            and (any(ch in value for ch in (' ', '\t', '*', '?', '[', '{', '<', '>', '|', '&', ';', '(', ')', "'", '\\'))
                 or any(ord(ch) > 127 for ch in value))
        )
        if needs_quoting:
            escaped = value.replace('\\', '\\\\').replace('"', '\\"')
            value = f'"{escaped}"'
    return f"{name}={value}"


def _strip_balanced(s: str) -> str:
    """Return s with the outermost matching brackets/parens stripped, for self-delim check."""
    if not s or len(s) < 2:
        return s
    pairs = {'(': ')', '[': ']', '{': '}', '`': '`'}
    if s[0] == '$' and len(s) > 2 and s[1] in pairs and s[-1] == pairs[s[1]]:
        return s[2:-1]
    if s[0] in pairs and s[-1] == pairs[s[0]]:
        return s[1:-1]
    return s


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
    elif kind in ("if", "while", "until", "for", "case", "select"):
        # Two possible AST shapes for control-flow compound nodes:
        #   A) Synthetic (entropy-mask, etc.): parts = [test, body, ...]
        #      with NO reservedwords — emitter adds the keywords.
        #   B) bashlex: parts = [ReservedwordNode('if'), test, RW('then'),
        #      body, RW('fi')] — reservedwords are explicit children.
        # Detect by checking if the first part is a reservedword keyword.
        if _has_explicit_keywords(parts, kind):
            return _emit_bashlex_control_flow(parts, depth)
        # Synthetic — dispatch to the kind-specific emitter
        if kind == "if":
            return _emit_if_compound(node, depth)
        elif kind == "for":
            return _emit_for_compound(node, depth)
        elif kind == "while":
            return _emit_while_compound(node, depth)
        elif kind == "until":
            return _emit_until_compound(node, depth)
        elif kind == "case":
            return _emit_case_compound(node, depth)
        return inner
    elif kind == "[[":
        return "[[ " + inner + " ]]"
    else:
        return inner


_CONTROL_KEYWORDS = frozenset({
    "if", "then", "elif", "else", "fi",
    "while", "until", "do", "done",
    "for", "in", "case", "esac", "select",
})


def _has_explicit_keywords(parts: list, kind: str) -> bool:
    """True if parts[] starts with a bashlex-style reservedword keyword."""
    if not parts:
        return False
    first = parts[0]
    if not isinstance(first, dict):
        return False
    if first.get("type") != "word":
        return False
    return first.get("value", "") == kind or first.get("value", "") in _CONTROL_KEYWORDS


def _emit_bashlex_control_flow(parts: list, depth: int) -> str:
    """Emit a flat bashlex-style control flow whose parts include the
    reservedword keywords. Strategy: join children with newlines so each
    keyword starts a new line, but keep the condition next to its opening
    keyword via a semicolon.
    """
    out: list[str] = []
    for i, p in enumerate(parts):
        if not isinstance(p, dict):
            continue
        emitted = _emit_node(p, depth + 1)
        if emitted == "":
            continue
        out.append(emitted)
    # Layout pass: keywords like 'do' / 'then' should follow ';' from the
    # previous list (condition); 'done' / 'fi' / 'esac' should be on their
    # own line. We use the source order from `out` and add the connectors.
    rendered: list[str] = []
    for i, tok in enumerate(out):
        if tok in ("do", "then"):
            # Attach to previous via ';' if previous didn't end in keyword
            # AND doesn't already end in ';' or '\n' (avoids double `;;`).
            if rendered and rendered[-1] not in _CONTROL_KEYWORDS:
                prev = rendered[-1].rstrip()
                connector = "; " if not prev.endswith((";", "\n", "&")) else " "
                rendered[-1] = prev + connector + tok
            else:
                rendered.append(tok)
        elif tok in ("done", "fi", "esac", "else", "elif"):
            rendered.append("\n" + tok)
        else:
            rendered.append(tok)
    return " ".join(rendered).replace(" \n", "\n").replace("  ", " ")


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
