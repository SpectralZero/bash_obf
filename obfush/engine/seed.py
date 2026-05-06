"""
Seed generation & PRNG management.

The seed drives ALL random decisions across every layer.  A deterministic
--seed flag forces reproducible output for debugging or team synchronisation.
"""

from __future__ import annotations

import os
import random
import time

import xxhash


def generate_seed(source: str | bytes) -> int:
    """Generate a unique seed by mixing source content hash, timestamp, and entropy.

    The XOR combination ensures that:
      - Same source at different times → different seed
      - Different source at the same time → different seed
      - os.urandom adds true entropy beyond predictable components

    Args:
        source: Bash source code as string or bytes.

    Returns:
        64-bit integer seed.
    """
    if isinstance(source, str):
        source = source.encode("utf-8")

    source_hash = xxhash.xxh64(source).intdigest()
    entropy = int.from_bytes(os.urandom(8), "big")
    timestamp = int(time.time() * 1_000_000)  # microsecond precision

    return (source_hash ^ entropy ^ timestamp) & 0xFFFFFFFFFFFFFFFF


def generate_seed_from_path(source_path: str) -> int:
    """Generate seed from a file path (reads file content).

    Args:
        source_path: Path to the bash script.

    Returns:
        64-bit integer seed.
    """
    with open(source_path, "rb") as f:
        return generate_seed(f.read())


def create_rng(seed: int) -> random.Random:
    """Create a seeded PRNG instance.

    Uses Python's Mersenne Twister — not cryptographic, but provides
    excellent distribution for obfuscation decisions.

    Args:
        seed: Integer seed value.

    Returns:
        Seeded random.Random instance (independent of global state).
    """
    rng = random.Random()
    rng.seed(seed)
    return rng


def derive_layer_seed(master_seed: int, layer_name: str) -> int:
    """Derive a per-layer seed from the master seed.

    Each layer gets its own deterministic sub-seed so that enabling/disabling
    one layer does not change the random decisions of other layers.

    Args:
        master_seed: The global engine seed.
        layer_name:  Canonical layer name (e.g. 'id-mangle').

    Returns:
        Derived 64-bit integer seed for the layer.
    """
    combined = f"{master_seed}:{layer_name}".encode("utf-8")
    return xxhash.xxh64(combined).intdigest()
