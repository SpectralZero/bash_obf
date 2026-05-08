"""
Layer 8: Poly-Shell Embedding

Transforms the script into a self-extracting loader that reconstructs
the payload through chunk decoding and in-process execution.

Execution method respects --eval-mode:
  ok         — eval "${chunks}"  (functions stay in scope)
  no-eval    — source <(printf '%s' "${chunks}")  (no eval token, scope preserved)
  direct-exec — source <(printf '%s' "${chunks}")  (same as no-eval)

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

        # Split into chunks at line boundaries
        num_chunks = rng.randint(3, min(7, max(3, len(source) // 200)))
        chunks = _split_payload(source, num_chunks, rng)

        # Encode each chunk differently
        encoded_chunks = _encode_chunks(chunks, rng)
        stats.chunks_created = len(encoded_chunks)

        # Build bootstrap loader AST (respects eval_mode)
        loader_ast = _build_loader(encoded_chunks, rng, config.eval_mode)
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
    """Split payload into N chunks at line boundaries.

    Splitting at line boundaries (not byte offsets) ensures every chunk
    is syntactically complete — no broken tokens, keywords, or strings.
    The emitter outputs one statement per line, so line boundaries are
    always safe split points.
    """
    lines = source.split('\n')
    total_lines = len(lines)

    if total_lines <= num_chunks:
        # Fewer lines than chunks — return each line as a chunk
        return [line + '\n' for line in lines if line]

    # Generate random split points at line boundaries
    points = sorted(rng.sample(range(1, total_lines), min(num_chunks - 1, total_lines - 1)))
    points = [0] + points + [total_lines]

    chunks = []
    for i in range(len(points) - 1):
        chunk_lines = lines[points[i]:points[i + 1]]
        chunk = '\n'.join(chunk_lines)
        if chunk:
            chunks.append(chunk)

    return chunks


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
    eval_mode: str = "ok",
) -> dict:
    """Build a bootstrap loader AST that chains chunk decoding.

    Execution method depends on eval_mode:
      ok         — eval "${concat}" — keeps functions in scope
      no-eval    — source <(printf '%s' "${concat}") — no eval token,
                   scope preserved via process substitution sourcing
      direct-exec — same as no-eval (source-based)

    Using eval/source instead of bash -c is critical: bash -c creates
    a child process where function definitions are scoped.  If the
    encode layer already wrapped individual commands in bash -c calls,
    those nested children can't see functions from the poly-shell
    bash -c parent.  eval/source execute in the current shell, so
    all function definitions remain visible.
    """
    body: list[dict] = []

    # Assign each decoded chunk to a variable
    chunk_vars = []
    for i, chunk in enumerate(encoded_chunks):
        var_name = f"_c{rng.randint(0x100, 0xffff):04x}"
        chunk_vars.append(var_name)

        body.append({
            "type": "assignment",
            "name": var_name,
            "value": f'"$({chunk["decode_expr"]})"',
            "pos": None,
        })

    # Concatenate all chunks
    concat_expr = "".join(f"${{{v}}}" for v in chunk_vars)

    if eval_mode == "ok":
        # eval keeps everything in the current shell
        exec_cmd = f'eval "{concat_expr}"'
    else:
        # source <(printf ...) — no eval token, scope preserved
        # printf '%s' ensures no interpretation of escape sequences
        exec_cmd = f"source <(printf '%s' \"{concat_expr}\")"

    body.append({
        "type": "command",
        "parts": [
            {"type": "word", "value": exec_cmd, "pos": None},
        ],
        "pos": None,
    })

    return {"type": "script", "body": body}
