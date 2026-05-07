"""
String encoding and shredding primitives.

These are the low-level building blocks used by the str_shred layer
(and others) to transform readable strings into obfuscated equivalents.
Each function produces valid bash that evaluates to the original string.
"""

from __future__ import annotations

import random
from typing import Any


def to_hex_escape(s: str) -> str:
    r"""Convert string to hex escape sequence.

    Example: "Hello" → $'\x48\x65\x6c\x6c\x6f'

    Args:
        s: Input string.

    Returns:
        Bash hex-escaped string literal.
    """
    escaped = "".join(f"\\x{ord(c):02x}" for c in s)
    return f"$'{escaped}'"


def to_octal_escape(s: str) -> str:
    r"""Convert string to octal escape sequence.

    Example: "Hello" → $'\110\145\154\154\157'

    Args:
        s: Input string.

    Returns:
        Bash octal-escaped string literal.
    """
    escaped = "".join(f"\\{ord(c):03o}" for c in s)
    return f"$'{escaped}'"


def to_fragmented_concat(s: str, rng: random.Random) -> str:
    """Split string into randomly-sized fragments and concatenate.

    Example: "Hello" → "He"$'\\x6c\\x6c'"o"

    The fragment boundaries and encoding methods are randomised.

    Args:
        s:   Input string.
        rng: Seeded PRNG.

    Returns:
        Bash concatenated fragment expression.
    """
    if len(s) <= 1:
        return f'"{s}"'

    fragments: list[str] = []
    pos = 0

    while pos < len(s):
        # Random chunk size: 1–4 characters
        chunk_size = rng.randint(1, min(4, len(s) - pos))
        chunk = s[pos : pos + chunk_size]
        pos += chunk_size

        # Random encoding for this fragment
        method = rng.choice(["plain", "hex", "octal"])
        if method == "hex":
            escaped = "".join(f"\\x{ord(c):02x}" for c in chunk)
            fragments.append(f"$'{escaped}'")
        elif method == "octal":
            escaped = "".join(f"\\{ord(c):03o}" for c in chunk)
            fragments.append(f"$'{escaped}'")
        else:
            # Escape double-quote special chars
            safe = chunk.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")
            fragments.append(f'"{safe}"')

    return "".join(fragments)


def to_variable_reconstruction(
    s: str,
    rng: random.Random,
    prefix: str = "_v",
) -> tuple[list[str], str]:
    """Decompose string into per-character variables and reassemble.

    Example: "cur" →
        _v0="c" _v1="u" _v2="r"
        assembly: "${_v0}${_v1}${_v2}"

    Args:
        s:      Input string.
        rng:    Seeded PRNG.
        prefix: Variable name prefix.

    Returns:
        Tuple of (list of assignment statements, assembly expression).
    """
    # Generate unique suffixes
    suffix_pool = list(range(1000))
    rng.shuffle(suffix_pool)

    assignments: list[str] = []
    refs: list[str] = []

    for i, char in enumerate(s):
        var_name = f"{prefix}{suffix_pool[i]:03x}"
        # Escape for assignment
        if char == "'":
            assignments.append(f'{var_name}="' + "'" + '"')
        elif char == '"':
            assignments.append(f"{var_name}='\"'")
        elif char == "\\":
            assignments.append(f'{var_name}="\\\\"')
        else:
            assignments.append(f'{var_name}="{char}"')
        refs.append(f"${{{var_name}}}")

    return assignments, "".join(refs)


def to_arithmetic_printf(s: str) -> str:
    """Convert string to printf with arithmetic ASCII code expansion.

    Example: "Hello" → printf '%c' $((0x48))$((0x65))$((0x6c))$((0x6c))$((0x6f))

    This produces no high-entropy base64 alphabet and looks like
    genuine numeric calculations.

    Args:
        s: Input string.

    Returns:
        Bash printf command string.
    """
    codes = " ".join(f"$(( 0x{ord(c):02x} ))" for c in s)
    return f"$(printf '%s' $(printf '\\\\x%02x' {codes}))"


def to_arithmetic_printf_simple(s: str) -> str:
    """Simpler arithmetic printf — one printf with escape codes.

    Example: "Hi" → $(printf '\\x48\\x69')

    Args:
        s: Input string.

    Returns:
        Bash command substitution string.
    """
    hex_codes = "".join(f"\\x{ord(c):02x}" for c in s)
    return f"$(printf '{hex_codes}')"


def to_base64_decode(s: str) -> str:
    """Convert string to base64-encoded inline decode.

    Example: "Hello" → $(echo 'SGVsbG8=' | base64 -d)

    WARNING: Only use when eval_mode == 'ok'. This is flagged by
    shell audit tools.

    Args:
        s: Input string.

    Returns:
        Bash command substitution with base64 decode.
    """
    import base64
    encoded = base64.b64encode(s.encode("utf-8")).decode("ascii")
    return f"$(echo '{encoded}' | base64 -d)"


def random_shred(
    s: str,
    rng: random.Random,
    eval_mode: str = "ok",
) -> str | tuple[list[str], str]:
    """Apply a randomly-chosen shredding technique to a string.

    Args:
        s:         Input string.
        rng:       Seeded PRNG.
        eval_mode: Controls whether base64 decode is available.

    Returns:
        Either a single bash expression (str) or a tuple of
        (setup_statements, expression) when variable reconstruction is used.
    """
    methods = ["hex", "octal", "fragment", "arithmetic"]
    if eval_mode == "ok":
        methods.append("base64")

    # Variable reconstruction is disabled: its setup assignments would need
    # to be inserted before the use site, but the str-shred layer currently
    # only annotates them on the node without hoisting them to the script
    # body. Re-enable once the hoister is implemented.

    method = rng.choice(methods)

    if method == "hex":
        return to_hex_escape(s)
    elif method == "octal":
        return to_octal_escape(s)
    elif method == "fragment":
        return to_fragmented_concat(s, rng)
    elif method == "arithmetic":
        return to_arithmetic_printf_simple(s)
    elif method == "base64":
        return to_base64_decode(s)
    elif method == "variable":
        return to_variable_reconstruction(s, rng)
    else:
        return to_hex_escape(s)  # fallback
