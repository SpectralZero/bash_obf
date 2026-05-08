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
        # Filter out string tokens (e.g., '|') AND the 'pipe' separator
        # nodes that bashlex interleaves between piped commands — they're
        # syntactic separators, not commands.
        parts = [
            _convert_node(p) for p in child_nodes
            if not isinstance(p, str)
            and hasattr(p, "kind")
            and p.kind != "pipe"
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
        # Output may be:
        #   - a bashlex WordNode (file path, e.g. /dev/null)
        #   - an integer (target FD, e.g. 1 in `2>&1`)
        #   - None
        raw_output = getattr(node, "output", None)
        if raw_output is None:
            target: Any = ""
        elif isinstance(raw_output, int):
            target = str(raw_output)
        elif hasattr(raw_output, "kind"):
            target = _convert_node(raw_output)
        else:
            target = str(raw_output)
        fd = getattr(node, "input", None)
        heredoc = None
        raw_heredoc = getattr(node, "heredoc", None)
        if raw_heredoc is not None:
            heredoc = _heredoc(
                body=getattr(raw_heredoc, "value", str(raw_heredoc)),
                delimiter=getattr(raw_heredoc, "delimiter", "EOF"),
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

    elif kind in ("if", "while", "until", "for", "case", "select"):
        # Control-flow constructs — bashlex stores them as a flat list of
        # parts (reservedwords, conditions, bodies). Recurse into each part
        # and re-emit them in order. The compound emitter joins with spaces,
        # which is correct for the typical shell layout.
        parts = []
        for attr in ("parts", "list"):
            if hasattr(node, attr):
                v = getattr(node, attr)
                if v:
                    parts = [_convert_node(p) for p in v]
                    break
        return _compound(kind=kind, parts=parts, pos=node.pos)

    elif kind == "reservedword":
        # Reserved keyword like '{', '}', 'do', 'done', 'then', 'fi', etc.
        # Emit as a literal word with the keyword text — never the Python repr.
        word_text = getattr(node, "word", "")
        return _word(value=word_text, pos=node.pos, raw=word_text)

    elif kind == "operator":
        op = getattr(node, "op", "")
        return _node("operator", op=op, pos=getattr(node, "pos", None))

    else:
        # Unknown node — preserve actual source text via .word if present,
        # otherwise fall back to str(node) which is the Python repr.
        word_text = getattr(node, "word", None)
        if isinstance(word_text, str):
            return _word(value=word_text, pos=getattr(node, "pos", None),
                         raw=word_text)
        raw = str(node) if node else ""
        return _word(value=raw, pos=getattr(node, "pos", None), raw=raw)


# ──────────────────────────────────────────────────────────────────────
# Fallback parser for bashlex failures
# ──────────────────────────────────────────────────────────────────────

# Patterns bashlex can't handle
_ARITHMETIC_EXPR_RE = re.compile(r'\$\(\(.*?\)\)', re.DOTALL)
_ANSI_C_QUOTE_RE = re.compile(r"\$'(?:[^'\\]|\\.)*'")
# Simple expansion: ${var}, ${1}, ${#}, ${?}, ${@} etc. -- bashlex handles these.
_SIMPLE_EXPANSION_RE = re.compile(r'^[a-zA-Z_]\w*$|^\d+$|^[#?$!@*-]$')


def _find_complex_params(source: str) -> list[tuple[int, int]]:
    """Find ${...} expansions that bashlex can't parse, using brace-counting.

    Handles nested braces like ${var/${other}/replacement} correctly,
    which the old regex approach could not.  Returns a list of (start, end)
    spans covering the full ``${...}`` token.
    """
    spans: list[tuple[int, int]] = []
    i = 0
    n = len(source)

    while i < n - 1:
        if source[i] == '$' and source[i + 1] == '{':
            start = i
            depth = 1
            j = i + 2

            while j < n and depth > 0:
                c = source[j]
                if c == '\\':
                    j += 2      # skip escaped character
                    continue
                if c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                j += 1

            if depth == 0:
                # Content between ${ and }
                content = source[start + 2 : j - 1]
                if not _SIMPLE_EXPANSION_RE.match(content):
                    spans.append((start, j))
                i = j
                continue

        i += 1

    return spans


def _find_arith_commands(source: str) -> list[tuple[int, int]]:
    """Find (( ... )) arithmetic commands (NOT $((...)) expressions).

    In bash, )) always terminates the arithmetic command -- there is
    no nesting of (( )) inside (( )).  So we just scan for the first
    )) after each ((.
    """
    spans: list[tuple[int, int]] = []
    i = 0
    n = len(source)

    while i < n - 1:
        if source[i] == '(' and source[i + 1] == '(':
            # Must NOT be preceded by $ (that's $((..)) arithmetic expression)
            if i > 0 and source[i - 1] == '$':
                i += 2
                continue

            start = i
            j = i + 2

            # Scan for ))
            while j < n - 1:
                if source[j] == ')' and source[j + 1] == ')':
                    spans.append((start, j + 2))
                    i = j + 2
                    break
                j += 1
            else:
                i += 1
                continue
            continue

        i += 1

    return spans


def _find_array_assignments(source: str) -> list[tuple[int, int]]:
    """Find name=(...) array assignments that bashlex can't parse.

    Uses quote-aware paren-counting so ')' inside quoted strings
    doesn't terminate the match prematurely.
    """
    _ARRAY_START = re.compile(r'[a-zA-Z_]\w*=\(')
    spans: list[tuple[int, int]] = []
    n = len(source)

    for m in _ARRAY_START.finditer(source):
        start = m.start()
        j = m.end()  # position after the opening (
        depth = 1

        while j < n and depth > 0:
            c = source[j]
            if c == '\\':
                j += 2
                continue
            if c == '"':
                j += 1
                while j < n and source[j] != '"':
                    if source[j] == '\\':
                        j += 1
                    j += 1
            elif c == "'":
                j += 1
                while j < n and source[j] != "'":
                    j += 1
            elif c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
            j += 1

        if depth == 0:
            spans.append((start, j))

    return spans


def _find_double_bracket(source: str) -> list[tuple[int, int]]:
    """Find [[ ... ]] conditional tests that bashlex can't parse.

    Scans for ``[[`` and finds the matching ``]]``.  Handles nested
    quotes so ``]]`` inside strings doesn't terminate prematurely.
    """
    spans: list[tuple[int, int]] = []
    i = 0
    n = len(source)

    while i < n - 1:
        if source[i] == '[' and source[i + 1] == '[':
            # Make sure this isn't inside a word (e.g. 'foo[[')
            if i > 0 and source[i - 1] not in (' ', '\t', '\n', ';', '&', '|', '(', '!'):
                i += 2
                continue

            start = i
            j = i + 2

            while j < n - 1:
                c = source[j]
                # Skip quoted strings
                if c == '"':
                    j += 1
                    while j < n and source[j] != '"':
                        if source[j] == '\\':
                            j += 1
                        j += 1
                elif c == "'":
                    j += 1
                    while j < n and source[j] != "'":
                        j += 1
                elif c == ']' and source[j + 1] == ']':
                    spans.append((start, j + 2))
                    i = j + 2
                    break
                j += 1
            else:
                i += 1
                continue
            continue

        i += 1

    return spans


def _preprocess_for_bashlex(source: str) -> tuple[str, dict[str, str]]:
    """Replace constructs bashlex can't parse with placeholders.

    Substitution order matters:
      1. $'...' ANSI-C quoting  -- prevents interference with ${...} scanning
      2. $((...)) arithmetic expressions  -- prevents confusion with (( ))
      3. Complex ${...} via brace-counting  -- handles nested braces
      4. Array assignments name=(...)  -- bashlex can't parse these
      5. (( ... )) arithmetic commands  -- bare (( )) after $(( )) is gone
      6. [[ ... ]] double-bracket tests  -- bashlex can't parse these

    Returns the processed source and a mapping of placeholder -> original.
    """
    placeholders: dict[str, str] = {}
    counter = [0]

    def _make_placeholder(original: str) -> str:
        ph = f"__OBFUSH_PH_{counter[0]:04d}__"
        counter[0] += 1
        placeholders[ph] = original
        return ph

    def _regex_replace(match: re.Match) -> str:
        return _make_placeholder(match.group(0))

    def _replace_spans(text: str, spans: list[tuple[int, int]]) -> str:
        if not spans:
            return text
        parts: list[str] = []
        prev = 0
        for start, end in spans:
            parts.append(text[prev:start])
            parts.append(_make_placeholder(text[start:end]))
            prev = end
        parts.append(text[prev:])
        return "".join(parts)

    processed = source

    # 1. $'...' ANSI-C quoting (all occurrences)
    processed = _ANSI_C_QUOTE_RE.sub(_regex_replace, processed)

    # 2. $((...)) arithmetic expressions
    processed = _ARITHMETIC_EXPR_RE.sub(_regex_replace, processed)

    # 3. Complex ${...} via brace-counting (must re-scan after prior subs)
    processed = _replace_spans(processed, _find_complex_params(processed))

    # 4. Array assignments: name=(...)
    processed = _replace_spans(processed, _find_array_assignments(processed))

    # 5. (( ... )) arithmetic commands
    processed = _replace_spans(processed, _find_arith_commands(processed))

    # 6. [[ ... ]] double-bracket conditional tests
    processed = _replace_spans(processed, _find_double_bracket(processed))

    return processed, placeholders


def _restore_placeholders(ast: dict, placeholders: dict[str, str]) -> dict:
    """Walk AST and restore placeholder strings to their original form.

    Handles nested placeholders (a placeholder whose restored value
    contains another placeholder) by resolving the values first.
    """
    if not placeholders:
        return ast

    # Pre-resolve nested placeholders: expand inner placeholders in values
    # until no more expansions are possible.  This ensures that when we
    # walk the AST, each placeholder restores to fully-resolved text.
    resolved = dict(placeholders)
    changed = True
    while changed:
        changed = False
        for ph, val in resolved.items():
            for inner_ph, inner_val in placeholders.items():
                if inner_ph in val and inner_ph != ph:
                    resolved[ph] = val.replace(inner_ph, inner_val)
                    changed = True
                    break  # restart scan after mutation

    def _walk(node: dict) -> dict:
        if not isinstance(node, dict):
            return node

        # Check string values for placeholders
        for key in ("value", "name", "target", "body", "op"):
            if key in node and isinstance(node[key], str):
                for ph, original in resolved.items():
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
        # Total fallback: treat the (shebang-stripped) script as a single
        # opaque node, but preserve the shebang separately so the emitter
        # can put it on line 1 and entropy-mask doesn't inject above it.
        fallback_ast = _script(body=[_word(
            value=parse_source, raw=parse_source,
            pos=(0, len(parse_source)),
        )])
        if shebang:
            fallback_ast["shebang"] = shebang
        return fallback_ast

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
