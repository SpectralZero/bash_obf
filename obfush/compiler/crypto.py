"""Deterministic rolling-XOR payload encryption."""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class EncryptedPayload:
    ciphertext: bytes
    key: bytes


def encrypt_payload(
    payload: bytes,
    rng: random.Random,
    key_size: int = 32,
) -> EncryptedPayload:
    """Encrypt payload bytes with a deterministic repeated XOR key."""
    if not payload:
        raise ValueError("payload must not be empty")
    if not 16 <= key_size <= 64:
        raise ValueError("key_size must be 16-64 bytes")
    key = rng.randbytes(key_size)
    ciphertext = bytes(
        byte ^ key[index % len(key)]
        for index, byte in enumerate(payload)
    )
    return EncryptedPayload(ciphertext=ciphertext, key=key)


def decrypt_payload(encrypted: EncryptedPayload) -> bytes:
    """Reference decryption used by tests and build validation."""
    return bytes(
        byte ^ encrypted.key[index % len(encrypted.key)]
        for index, byte in enumerate(encrypted.ciphertext)
    )
