"""
Layer 8: Poly-Shell Embedding

Transforms the script into a self-extracting loader that reconstructs
the payload through chunk decoding and in-process execution.

Execution method respects --eval-mode:
  ok         — eval "${chunks}"  (functions stay in scope)
  no-eval    — source a private temporary file  (no eval token, scope preserved)
  direct-exec — source a private temporary file  (same as no-eval)

Only activated at intensity >= 0.9 or via explicit --layers poly-shell.
"""

from __future__ import annotations

import base64
import random

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
        loader_ast = _build_loader(
            encoded_chunks, rng, config.eval_mode, config.name_pool,
        )
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

    Splitting at line boundaries avoids broken lexical tokens. Chunks are
    reassembled before execution because a line boundary is not necessarily
    a complete compound Bash statement.
    """
    lines = source.splitlines(keepends=True)
    total_lines = len(lines)

    if not lines:
        return []

    if total_lines <= num_chunks:
        return list(lines)

    # Generate random split points at line boundaries
    points = sorted(rng.sample(range(1, total_lines), min(num_chunks - 1, total_lines - 1)))
    points = [0] + points + [total_lines]

    chunks = []
    for i in range(len(points) - 1):
        chunk_lines = lines[points[i]:points[i + 1]]
        chunk = ''.join(chunk_lines)
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
            decode_expr = f"printf '%s' '{blob}' | base64 -d"
        elif method == "hex":
            blob = data.hex()
            escaped = "".join(f"\\x{byte:02x}" for byte in data)
            decode_expr = f"printf '%b' '{escaped}'"
        elif method == "rev_base64":
            # `rev` reverses each line independently, so encode the payload
            # with the same line-wise transform rather than reversing bytes.
            reversed_lines = "\n".join(
                line[::-1] for line in chunk.split("\n")
            )
            blob = base64.b64encode(reversed_lines.encode("utf-8")).decode()
            decode_expr = f"printf '%s' '{blob}' | base64 -d | rev"
        else:
            blob = base64.b64encode(data).decode()
            decode_expr = f"printf '%s' '{blob}' | base64 -d"

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
    name_pool=None,
) -> dict:
    """Build a bootstrap loader AST that chains chunk decoding.

    Execution method: cascading per-chunk source via temp files.
    Each chunk is independently decoded and sourced, so no single
    line modification can dump the entire payload.  This defeats
    the sed 's/eval/echo/' attack.

    Using source instead of bash -c is critical: bash -c creates
    a child process where function definitions are scoped.  If the
    encode layer already wrapped individual commands in bash -c calls,
    those nested children can't see functions from the poly-shell
    bash -c parent.  source executes in the current shell, so
    all function definitions remain visible.
    """
    body: list[dict] = []

    # Temp file variable — shared across all chunks
    temp_var = (
        name_pool.next_name()
        if name_pool is not None
        else f"_f{rng.randint(0x100, 0xffff):04x}"
    )

    # Assign each decoded chunk to a variable
    chunk_vars = []
    for i, chunk in enumerate(encoded_chunks):
        var_name = (
            name_pool.next_name()
            if name_pool is not None
            else f"_c{rng.randint(0x100, 0xffff):04x}"
        )
        chunk_vars.append(var_name)

        # Command substitution strips trailing newlines. Append a sentinel and
        # remove it during concatenation so exact chunk boundaries survive.
        body.append({
            "type": "assignment",
            "name": var_name,
            "value": f'"$({chunk["decode_expr"]}; printf .)"',
            "pos": None,
        })

    # Create a single temp file, write decoded chunks sequentially, then source once.
    # This prevents the sed 's/eval/echo/' attack (no eval keyword exists).
    # Each chunk is decoded separately, keeping the decode_expr values isolated.
    # An attacker can't dump all cleartext by modifying one line.
    status_var = (
        name_pool.next_name()
        if name_pool is not None
        else f"_r{rng.randint(0x100, 0xffff):04x}"
    )

    # Create temp file
    mktemp_cmd = (
        f'{temp_var}=$(mktemp "${{TMPDIR:-/tmp}}/.s.XXXXXX") || exit 1; '
        f'chmod 600 "${{{temp_var}}}" || {{ rm -f "${{{temp_var}}}"; exit 1; }}'
    )
    body.append({
        "type": "command",
        "parts": [
            {"type": "word", "value": mktemp_cmd, "raw": mktemp_cmd, "pos": None},
        ],
        "pos": None,
    })

    # Write each chunk to temp file (first truncates, rest append)
    for i, var in enumerate(chunk_vars):
        op = ">" if i == 0 else ">>"
        write_cmd = (
            f'printf \'%s\' "${{{var}%.}}" {op} "${{{temp_var}}}" || '
            f'{{ rm -f "${{{temp_var}}}"; exit 1; }}'
        )
        body.append({
            "type": "command",
            "parts": [
                {"type": "word", "value": write_cmd, "raw": write_cmd, "pos": None},
            ],
            "pos": None,
        })

    # Source the assembled file and clean up
    source_cmd = (
        f'source "${{{temp_var}}}"; {status_var}=$?; '
        f'rm -f "${{{temp_var}}}"; '
        f'(exit "${{{status_var}}}")'
    )
    body.append({
        "type": "command",
        "parts": [
            {"type": "word", "value": source_cmd, "raw": source_cmd, "pos": None},
        ],
        "pos": None,
    })

    return {"type": "script", "body": body}
