"""
Layer 8: Poly-Shell Embedding

Transforms the script into a self-extracting loader that reconstructs
the payload through multiple child bash invocations. No single file
contains the entire logic.

Only activated at intensity >= 0.9 or via explicit --layers poly-shell.
"""

from __future__ import annotations

import base64
import random
from typing import Any

from obfush.layers.base import Layer, LayerConfig, LayerStats


class LayerImpl(Layer):
    name = "poly-shell"
    description = "Multi-process self-extracting architecture"

    def transform(self, ast: dict, config: LayerConfig) -> tuple[dict, LayerStats]:
        stats = LayerStats()
        rng = config.rng

        # Only activate at high intensity
        if config.intensity < 0.85:
            return ast, stats

        from obfush.engine.ast_emitter import emit
        source = emit(ast)

        # Split into chunks
        num_chunks = rng.randint(3, min(7, max(3, len(source) // 200)))
        chunks = _split_payload(source, num_chunks, rng)

        # Encode each chunk differently
        encoded_chunks = _encode_chunks(chunks, rng)
        stats.chunks_created = len(encoded_chunks)

        # Build bootstrap loader AST
        loader_ast = _build_loader(encoded_chunks, rng)
        stats.nodes_modified = 1

        # Preserve shebang
        if ast.get("shebang"):
            loader_ast["shebang"] = ast["shebang"]

        return loader_ast, stats

    def estimate_size_increase(self, config: LayerConfig) -> float:
        if config.intensity < 0.85:
            return 1.0
        return 2.5 + config.intensity


def _split_payload(source: str, num_chunks: int, rng: random.Random) -> list[str]:
    """Split payload into N randomised chunks."""
    data = source.encode("utf-8")
    total = len(data)

    # Random split points
    points = sorted(rng.sample(range(1, total), min(num_chunks - 1, total - 1)))
    points = [0] + points + [total]

    chunks = []
    for i in range(len(points) - 1):
        chunk = data[points[i]:points[i + 1]]
        chunks.append(chunk)

    return [c.decode("utf-8", errors="replace") for c in chunks]


def _encode_chunks(
    chunks: list[str],
    rng: random.Random,
) -> list[dict[str, str]]:
    """Encode each chunk with a different method."""
    methods = ["base64", "hex", "rev_base64"]
    encoded = []

    for chunk in chunks:
        method = rng.choice(methods)
        data = chunk.encode("utf-8")

        if method == "base64":
            blob = base64.b64encode(data).decode()
            decode_expr = f"echo '{blob}' | base64 -d"
        elif method == "hex":
            blob = data.hex()
            decode_expr = f"echo '{blob}' | xxd -r -p"
        elif method == "rev_base64":
            blob = base64.b64encode(data[::-1]).decode()
            decode_expr = f"echo '{blob}' | base64 -d | rev"
        else:
            blob = base64.b64encode(data).decode()
            decode_expr = f"echo '{blob}' | base64 -d"

        encoded.append({
            "method": method,
            "blob": blob,
            "decode_expr": decode_expr,
        })

    return encoded


def _build_loader(
    encoded_chunks: list[dict[str, str]],
    rng: random.Random,
) -> dict:
    """Build a bootstrap loader AST that chains chunk decoding."""
    body: list[dict] = []

    # Approach: store chunks in variables, decode and concatenate, pipe to bash
    chunk_vars = []
    for i, chunk in enumerate(encoded_chunks):
        var_name = f"_c{rng.randint(0x100, 0xffff):04x}"
        chunk_vars.append(var_name)

        # Assign the decode expression to a variable
        body.append({
            "type": "assignment",
            "name": var_name,
            "value": f'"$({chunk["decode_expr"]})"',
            "pos": None,
        })

    # Concatenate all chunks and pipe to bash
    concat_expr = "".join(f"${{{v}}}" for v in chunk_vars)
    body.append({
        "type": "command",
        "parts": [
            {"type": "word", "value": "bash", "pos": None},
            {"type": "word", "value": "-c", "pos": None},
            {"type": "word", "value": f'"{concat_expr}"', "pos": None},
        ],
        "pos": None,
    })

    return {"type": "script", "body": body}
