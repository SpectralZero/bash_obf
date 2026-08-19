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
    words: list[str] = []
    # Heredoc bodies must be deferred until AFTER the whole command line
    # (command + args + every other redirect).  Emitting the body inline at
    # the `<<EOF` position pushes trailing redirects like `> file` onto the
    # delimiter line, producing broken constructs such as `EOF > file`.
    heredoc_tails: list[str] = []
    for p in parts:
        if (isinstance(p, dict) and p.get("type") == "redirect"
                and p.get("heredoc")):
            marker, tail = _split_heredoc_redirect(p, depth)
            words.append(marker)
            heredoc_tails.append(tail)
            continue
        emitted = _emit_node(p, depth)
        if emitted:
            words.append(emitted)
    result = " ".join(w for w in words if w)
    for tail in heredoc_tails:
        result += "\n" + tail
    return result


def _split_heredoc_redirect(node: dict, depth: int) -> tuple[str, str]:
    """Split a heredoc redirect into (inline marker, deferred body+delimiter).

    The body stored on the node never includes the closing delimiter
    (the parser strips it), so the delimiter is added exactly once here.
    """
    fd = node.get("fd")
    heredoc = node.get("heredoc") or {}
    delim = heredoc.get("delimiter", "EOF")
    body = heredoc.get("body", "")
    fd_str = f"{fd}" if fd is not None else ""
    marker = f"{fd_str}<<{delim}"
    tail = f"{body}\n{delim}" if body else delim
    return marker, tail


def _emit_word(node: dict, depth: int) -> str:
    # Opaque/fallback node: emit verbatim, never quote.
    # bashlex couldn't parse this region, so 'value' contains valid raw bash
    # text (possibly mutated by id-mangle's regex). Wrapping it in quotes
    # would turn it into a literal string and break execution.
    if "raw" in node:
        raw_value = node.get("value", node["raw"])
        # A placeholder-restored complex expansion (${!ref}, ${v//a/b},
        # $((...)), possibly with surrounding literal text) that was quoted in
        # the source must STAY quoted, or it word-splits / glob-expands at
        # runtime.  The 'quoted' attr is only set for genuinely quoted source
        # words; opaque whole-script fallbacks and bare constructs have none.
        q = node.get("quoted")
        if q == "double":
            return '"' + raw_value + '"'
        if q == "single":
            return "'" + raw_value + "'"
        return raw_value
    value = node.get("value", "")
    if not value:
        return ""
    # Literal text that contains '$' or '`' which the source escaped (\$, \`)
    # or otherwise made non-expanding (parser tagged it ``literal``).  Emit it
    # single-quoted so bash performs NO expansion and word-splitting, exactly
    # reproducing the original text.
    if node.get("literal"):
        return "'" + value.replace("'", "'\\''") + "'"
    # If the parser recorded the original quoting style, respect it.
    quoted = node.get("quoted")
    if quoted == "double":
        # Re-wrap in double-quotes — preserves expansions, prevents splitting.
        return '"' + value + '"'
    elif quoted == "single":
        return "'" + value + "'"
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
    if re.fullmatch(r"\$(?:[a-zA-Z_][a-zA-Z0-9_]*|[0-9]+|[?#*!$@-])", value):
        return f'"{value}"'
    # Command substitution: $(...)  or  `...`
    # Whether to quote depends on context (argument vs command position).
    # The parser sets a 'quoted' attribute when it detects the original source
    # had double-quotes; _emit_word checks that BEFORE calling _shell_quote.
    # Here in _shell_quote (no context), leave command-subs unquoted — the
    # _emit_word caller handles quoting from the node's 'quoted' attribute.
    if (value.startswith("$(") and value.endswith(")")) or \
       (value.startswith("`") and value.endswith("`")):
        return value

    # Process substitution:  <(...)  or  >(...)
    # These are self-delimiting shell CONSTRUCTS, not filenames or literals.
    # Quoting or string-encoding them turns them into a literal path such as
    # '<(printf ...)' which bash then fails to open.  Emit verbatim.
    if (value.startswith("<(") or value.startswith(">(")) and value.endswith(")"):
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
        # Genuine array-literal RHS:  name=(elem ...) — tagged by the parser
        # (``array``).  Emit verbatim; quoting would collapse the array into a
        # single scalar string.  We deliberately gate on the parser flag and
        # NOT the value shape, so a scalar whose value merely looks like an
        # array — e.g.  x="(literal text)"  — is still correctly re-quoted.
        if node.get("array"):
            return f"{name}={value}"
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
    rendered: list[tuple[str, str]] = []
    has_heredoc = False
    for part in parts:
        if isinstance(part, dict) and part.get("type") == "operator":
            rendered.append(("op", part.get("op", ";")))
        else:
            emitted = _emit_node(part, depth)
            rendered.append(("cmd", emitted))
            if _ends_with_heredoc(emitted):
                has_heredoc = True

    if not has_heredoc:
        # Historical behavior — preserved exactly so output size (and the
        # engine's size-budget decisions) are unchanged for the common case.
        return " ".join(tok for _, tok in rendered)

    # Heredoc-aware join: a heredoc's closing delimiter must stand alone on
    # its own line — never trail it with a space, ';', or an inline operator,
    # or bash reads to EOF looking for the delimiter.
    out = ""
    prev_heredoc = False
    for kind, tok in rendered:
        if kind == "op":
            if prev_heredoc:
                out += "\n" if tok in ("\n", ";", "&") else "\n" + tok + " "
            elif tok == "\n":
                out += "\n"
            elif tok in (";", "&"):
                out += tok + " "
            else:  # && || |
                out += " " + tok + " "
            prev_heredoc = False
        else:
            if not tok:
                continue
            if out and not out.endswith(("\n", " ")):
                out += "\n" if prev_heredoc else " "
            out += tok
            prev_heredoc = _ends_with_heredoc(tok)
    return out


def _ends_with_heredoc(text: str) -> bool:
    """True if ``text`` ends with a heredoc whose closing delimiter is the
    final line (so a following token must start on a new line)."""
    stripped = text.rstrip("\n")
    if "\n" not in stripped:
        return False
    last_line = stripped.rsplit("\n", 1)[1]
    if not re.fullmatch(r"[A-Za-z_]\w*", last_line):
        return False
    return re.search(r"<<-?\s*['\"]?" + re.escape(last_line) + r"(?!\w)", text) is not None


def _emit_pipeline(node: dict, depth: int) -> str:
    parts = node.get("parts", [])
    commands = [_emit_node(p, depth) for p in parts]
    return " | ".join(commands)


def _emit_compound(node: dict, depth: int) -> str:
    kind = node.get("kind", "group")
    parts = node.get("parts", [])
    inner = "\n".join(_emit_node(p, depth + 1) for p in parts)
    # Redirects attached to the whole compound (e.g. `{ ...; } > file`,
    # `( ...; ) 2>&1`, `for ...; done > log`).  bashlex stores these on the
    # compound node; dropping them silently sends output to the wrong place.
    redir = _emit_trailing_redirects(node, depth)

    if kind == "group" or kind == "{":
        return "{\n" + inner + "\n}" + redir
    elif kind == "(":
        return "(\n" + inner + "\n)" + redir
    elif kind in ("if", "while", "until", "for", "case", "select"):
        # Two possible AST shapes for control-flow compound nodes:
        #   A) Synthetic (entropy-mask, etc.): parts = [test, body, ...]
        #      with NO reservedwords — emitter adds the keywords.
        #   B) bashlex: parts = [ReservedwordNode('if'), test, RW('then'),
        #      body, RW('fi')] — reservedwords are explicit children.
        # Detect by checking if the first part is a reservedword keyword.
        if _has_explicit_keywords(parts, kind):
            return _emit_bashlex_control_flow(parts, depth) + redir
        # Synthetic — dispatch to the kind-specific emitter
        if kind == "if":
            return _emit_if_compound(node, depth) + redir
        elif kind == "for":
            return _emit_for_compound(node, depth) + redir
        elif kind == "while":
            return _emit_while_compound(node, depth) + redir
        elif kind == "until":
            return _emit_until_compound(node, depth) + redir
        elif kind == "case":
            return _emit_case_compound(node, depth) + redir
        return inner + redir
    elif kind == "[[":
        return "[[ " + inner + " ]]" + redir
    else:
        return inner + redir


def _emit_trailing_redirects(node: dict, depth: int) -> str:
    """Emit redirects attached to a compound node, as a leading-space suffix."""
    redirects = node.get("redirects") or []
    rendered = [
        _emit_node(r, depth) for r in redirects
        if isinstance(r, dict)
    ]
    rendered = [r for r in rendered if r]
    return (" " + " ".join(rendered)) if rendered else ""


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
    # A process-substitution operand (<(...) / >(...)) must be separated from the
    # redirection operator by whitespace:  `< <(cmd)`,  `> >(cmd)`.  Concatenated,
    # the tokens merge into `<<(` / `>>(`, which bash parses as a heredoc / append
    # operator followed by `(` -- a syntax error, not a redirect-from-process-sub.
    sep = " " if isinstance(target, str) and target[:2] in ("<(", ">(") else ""
    return f"{fd_str}{rtype}{sep}{target}"


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
