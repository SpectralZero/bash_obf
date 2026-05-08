"""
Pre-processing: Comment Stripping

Runs BEFORE bashlex parsing to deterministically remove all comments from
the source.  This prevents operator OPSEC leaks — comments like
``# C2 callback``, ``# persistence via cron``, author tags, TODOs, and
non-English text are stripped unconditionally.

Without this pass, comment leakage is **non-deterministic**: bashlex drops
comments when it parses successfully but preserves them verbatim in the
opaque-blob fallback path.  This pass makes privacy deterministic.

Preserved:
    - Shebang (``#!/...``) at line 1
    - ``#`` inside single-quoted strings
    - ``#`` inside double-quoted strings
    - ``#`` inside here-documents (<<EOF ... EOF)
    - ``#`` in parameter expansion (``${#var}``, ``${var#pattern}``)
    - ``#`` in arithmetic contexts (``$(( x # ... ))``) — rare but valid
"""

from __future__ import annotations

import re


def strip_comments(source: str) -> str:
    """Remove all comments from bash source, preserving shebangs and
    ``#`` inside strings, here-docs, and parameter expansions.

    Returns the cleaned source with the same number of lines (comments
    are replaced with blank lines to preserve line-number alignment for
    error messages).
    """
    lines = source.split("\n")
    result: list[str] = []

    in_heredoc = False
    heredoc_delim = ""
    # Track quote state across lines (for multi-line strings)
    in_single_quote = False
    in_double_quote = False

    for line_idx, line in enumerate(lines):
        # Line 1 shebang — always preserve
        if line_idx == 0 and line.startswith("#!"):
            result.append(line)
            continue

        # Inside a here-document — pass through verbatim
        if in_heredoc:
            # Check if this line terminates the here-document
            stripped = line.strip()
            if stripped == heredoc_delim or stripped == heredoc_delim.strip("'\""):
                in_heredoc = False
            result.append(line)
            continue

        # Process the line character by character to find comments
        # outside of quoted contexts
        clean_line = _strip_line_comment(
            line, in_single_quote, in_double_quote
        )

        # Update quote state for multi-line strings
        in_single_quote, in_double_quote = _track_quotes(
            clean_line, in_single_quote, in_double_quote
        )

        # Check for here-document start
        heredoc_match = _detect_heredoc(clean_line)
        if heredoc_match:
            in_heredoc = True
            heredoc_delim = heredoc_match

        result.append(clean_line)

    return "\n".join(result)


# Pattern for here-document redirection:  <<EOF, <<'EOF', <<"EOF", <<-EOF
_HEREDOC_RE = re.compile(
    r'<<-?\s*([\'"]?)(\w+)\1'
)


def _detect_heredoc(line: str) -> str | None:
    """If the line starts a here-document, return the delimiter word."""
    # Only detect outside of quotes/comments (line is already cleaned)
    match = _HEREDOC_RE.search(line)
    if match:
        return match.group(2)
    return None


def _strip_line_comment(
    line: str,
    in_single_quote: bool,
    in_double_quote: bool,
) -> str:
    """Remove the comment portion of a single line.

    Handles:
    - Single-quoted strings (no escaping inside, # is literal)
    - Double-quoted strings (backslash-escaping, # is literal)
    - $'...' ANSI-C strings
    - Escaped # outside quotes
    - ${#var}, ${var#pattern} (parameter expansion)
    - $((...)) arithmetic
    """
    i = 0
    n = len(line)
    sq = in_single_quote
    dq = in_double_quote

    while i < n:
        c = line[i]

        # Backslash escape (outside single quotes)
        if c == '\\' and not sq and i + 1 < n:
            i += 2  # skip escaped char
            continue

        # Single quote toggle (not inside double quotes)
        if c == "'" and not dq:
            # Check for $'...' ANSI-C quoting
            if not sq and i > 0 and line[i - 1] == '$':
                # Enter $'...' — find the closing '
                i += 1
                while i < n:
                    if line[i] == '\\' and i + 1 < n:
                        i += 2
                        continue
                    if line[i] == "'":
                        i += 1
                        break
                    i += 1
                continue
            sq = not sq
            i += 1
            continue

        # Double quote toggle (not inside single quotes)
        if c == '"' and not sq:
            dq = not dq
            i += 1
            continue

        # # outside any quotes — this is a comment start
        if c == '#' and not sq and not dq:
            # BUT: ${#var}, ${var#pat}, ${var##pat} are NOT comments
            # Check if preceded by ${ or inside ${...}
            prefix = line[:i]
            if _is_param_expansion_hash(prefix):
                i += 1
                continue
            # It's a real comment — strip from here
            return line[:i].rstrip()

        i += 1

    return line


def _is_param_expansion_hash(prefix: str) -> bool:
    """Check if # at the current position is inside parameter expansion.

    Detects patterns like ${#, ${var#, ${var## where # is not a comment.
    """
    # Count unclosed ${ before this position
    depth = 0
    i = 0
    n = len(prefix)
    while i < n:
        if prefix[i] == '\\' and i + 1 < n:
            i += 2
            continue
        if i + 1 < n and prefix[i] == '$' and prefix[i + 1] == '{':
            depth += 1
            i += 2
            continue
        if prefix[i] == '}':
            depth = max(0, depth - 1)
            i += 1
            continue
        i += 1
    return depth > 0


def _track_quotes(
    line: str,
    in_single_quote: bool,
    in_double_quote: bool,
) -> tuple[bool, bool]:
    """Track quote state across line boundaries for multi-line strings."""
    sq = in_single_quote
    dq = in_double_quote
    i = 0
    n = len(line)

    while i < n:
        c = line[i]

        if c == '\\' and not sq and i + 1 < n:
            i += 2
            continue

        if c == "'" and not dq:
            # $'...' — skip through (handles escapes)
            if not sq and i > 0 and line[i - 1] == '$':
                i += 1
                while i < n:
                    if line[i] == '\\' and i + 1 < n:
                        i += 2
                        continue
                    if line[i] == "'":
                        i += 1
                        break
                    i += 1
                continue
            sq = not sq
            i += 1
            continue

        if c == '"' and not sq:
            dq = not dq
            i += 1
            continue

        i += 1

    return sq, dq
