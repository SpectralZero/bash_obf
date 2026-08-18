"""
String encoding and shredding primitives.

These are the low-level building blocks used by the str_shred layer
(and others) to transform readable strings into obfuscated equivalents.
Each function produces valid bash that evaluates to the original string.
"""

from __future__ import annotations

import random

from obfush.utils.name_pool import NamePool


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
    return f'"$(printf \'%s\' $(printf \'\\\\x%02x\' {codes}))"'


def to_arithmetic_printf_simple(s: str) -> str:
    """Simpler arithmetic printf — one printf with escape codes.

    Example: "Hi" → "$(printf '\\x48\\x69')"

    Args:
        s: Input string.

    Returns:
        Bash command substitution string.
    """
    hex_codes = "".join(f"\\x{ord(c):02x}" for c in s)
    return f'"$(printf \'{hex_codes}\')"'


def to_base64_decode(s: str) -> str:
    """Convert string to base64-encoded inline decode.

    Example: "Hello" → "$(printf '%s' 'SGVsbG8=' | base64 -d)"

    WARNING: Only use when eval_mode == 'ok'. This is flagged by
    shell audit tools.

    Args:
        s: Input string.

    Returns:
        Bash command substitution with base64 decode.
    """
    import base64
    encoded = base64.b64encode(s.encode("utf-8")).decode("ascii")
    return f'"$(printf \'%s\' \'{encoded}\' | base64 -d)"'


def to_split_variable_reconstruction(
    s: str,
    rng: random.Random,
    name_pool: NamePool,
) -> str:
    """Reconstruct UTF-8 bytes from shuffled, subshell-local variables.

    The assignments execute inside command substitution, so generated names
    never enter the caller's variable scope. The final expansion remains
    quoted and therefore occupies exactly one Bash argument.
    """
    data = s.encode("utf-8")
    if not data:
        return '""'
    if s.endswith("\n"):
        raise ValueError("split-variable reconstruction cannot preserve trailing newlines")

    fragments: list[tuple[str, bytes]] = []
    offset = 0
    while offset < len(data):
        width = rng.randint(1, min(4, len(data) - offset))
        fragments.append((name_pool.next_name(), data[offset:offset + width]))
        offset += width

    assignments = list(fragments)
    rng.shuffle(assignments)
    setup = "; ".join(
        f"{name}=$'{_hex_bytes(fragment)}'"
        for name, fragment in assignments
    )
    reconstruction = "".join(f"${{{name}}}" for name, _ in fragments)
    return f'"$({setup}; printf \'%s\' \"{reconstruction}\")"'


def _hex_bytes(data: bytes) -> str:
    return "".join("\\x%02x" % byte for byte in data)


def to_xor_reconstruction(
    s: str,
    rng: random.Random,
    name_pool: NamePool,
) -> str:
    """XOR-encrypt UTF-8 bytes and decrypt them with Bash builtins.

    The key is assembled from three independently embedded byte values. All
    runtime state lives inside command substitution and cannot enter the
    caller's scope.
    """
    data = s.encode("utf-8")
    if not data:
        return '""'
    if b"\0" in data:
        raise ValueError("Bash strings cannot preserve NUL bytes")
    if s.endswith("\n"):
        raise ValueError("XOR reconstruction cannot preserve trailing newlines")

    key = rng.randint(1, 255)
    first_part = rng.randint(0, 255)
    second_part = rng.randint(0, 255)
    third_part = first_part ^ second_part ^ key
    part_names = [name_pool.next_name() for _ in range(3)]
    key_name = name_pool.next_name()
    byte_name = name_pool.next_name()
    octal_name = name_pool.next_name()
    encrypted = " ".join(f"0x{byte ^ key:02x}" for byte in data)

    assignments = list(zip(part_names, (first_part, second_part, third_part)))
    rng.shuffle(assignments)
    setup = "; ".join(f"{name}={value}" for name, value in assignments)
    key_expression = " ^ ".join(part_names)
    return (
        f'"$({setup}; {key_name}=$(({key_expression})); '
        f'for {byte_name} in {encrypted}; do '
        f'printf -v {octal_name} \'%03o\' "$(({byte_name} ^ {key_name}))"; '
        f'printf \'%b\' "\\\\${{{octal_name}}}"; done)"'
    )


def random_shred(
    s: str,
    rng: random.Random,
    eval_mode: str = "ok",
    name_pool: NamePool | None = None,
) -> str:
    """Apply a randomly-chosen shredding technique to a string.

    Args:
        s:         Input string.
        rng:       Seeded PRNG.
        eval_mode: Controls whether base64 decode is available.

    Returns:
        A single Bash expression.
    """
    methods = ["hex", "octal", "fragment", "arithmetic"]
    if eval_mode == "ok":
        methods.append("base64")
    if name_pool is not None and not s.endswith("\n"):
        methods.append("split-variable")
        if "\0" not in s:
            methods.append("xor")

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
    elif method == "split-variable":
        assert name_pool is not None
        return to_split_variable_reconstruction(s, rng, name_pool)
    elif method == "xor":
        assert name_pool is not None
        return to_xor_reconstruction(s, rng, name_pool)
    else:
        return to_hex_escape(s)  # fallback
