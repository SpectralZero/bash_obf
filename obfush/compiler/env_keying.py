"""Optional deterministic environment binding for compiled loaders."""

from __future__ import annotations

import hashlib


def derive_environment_tag(value: str) -> bytes:
    """Return the embedded eight-byte tag for an explicit environment key."""
    if not value:
        raise ValueError("environment key must not be empty")
    return hashlib.sha256(value.encode("utf-8")).digest()[:8]


def c_environment_check(tag: bytes, function_name: str) -> str:
    """Generate a hostname-or-OBFUSH_ENV_KEY comparison without plaintext."""
    if len(tag) != 8:
        raise ValueError("environment tag must be eight bytes")
    expected = _c_bytes(tag)
    return f"""static int {function_name}(void) {{
    char value[256] = {{0}};
    const char *override = getenv("OBFUSH_ENV_KEY");
    if (override && *override) {{
        snprintf(value, sizeof(value), "%s", override);
    }} else if (gethostname(value, sizeof(value) - 1) != 0) {{
        return 0;
    }}
    unsigned char expected[8] = {{{expected}}};
    unsigned char actual[32];
    obfush_sha256((const unsigned char *)value, strlen(value), actual);
    return memcmp(expected, actual, 8) == 0;
}}"""


def _c_bytes(data: bytes) -> str:
    return ", ".join(f"0x{byte:02x}" for byte in data)
