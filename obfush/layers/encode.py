"""
Layer 6: Encoding

Selectively encodes regions of the script. Three modes:
  ok         — eval chains with base64/hex/xor (MAX obfuscation)
  no-eval    — indirect function dispatch, zero eval tokens
  direct-exec — exec bash -c "$(base64 -d <<< blob)"
"""

from __future__ import annotations

import base64
import random
from typing import Any

from obfush.layers.base import Layer, LayerConfig, LayerStats


class LayerImpl(Layer):
    name = "encode"
    description = "Encoding (base64, xor, hex) — respects --eval-mode"

    def transform(self, ast: dict, config: LayerConfig) -> tuple[dict, LayerStats]:
        stats = LayerStats()
        rng = config.rng

        # Select regions to encode based on intensity
        ast = _encode_walk(ast, config, stats)
        return ast, stats

    def estimate_size_increase(self, config: LayerConfig) -> float:
        return 1.5 + config.intensity


def _encode_walk(ast: dict, config: LayerConfig, stats: LayerStats) -> dict:
    """Walk AST and selectively encode regions."""
    if not isinstance(ast, dict):
        return ast

    rng = config.rng
    node_type = ast.get("type", "")
    stats.nodes_visited += 1

    # Encode command nodes (selective — not every command)
    if (node_type == "command"
            and rng.random() < config.intensity * 0.4
            and not ast.get("_junk")
            and not ast.get("_encoded")):
        ast = _encode_command(ast, config, stats)

    # Recurse
    for key in ("body",):
        val = ast.get(key)
        if isinstance(val, list):
            ast[key] = [_encode_walk(i, config, stats) if isinstance(i, dict) else i for i in val]
        elif isinstance(val, dict):
            ast[key] = _encode_walk(val, config, stats)

    return ast


def _encode_command(ast: dict, config: LayerConfig, stats: LayerStats) -> dict:
    """Encode a single command node."""
    from obfush.engine.ast_emitter import _emit_command

    rng = config.rng
    mode = config.eval_mode

    # Reconstruct the command as a string
    cmd_str = _emit_command(ast, 0)
    if not cmd_str or len(cmd_str) < 5:
        return ast

    if mode == "ok":
        return _encode_eval(cmd_str, rng, stats)
    elif mode == "no-eval":
        return _encode_no_eval(cmd_str, rng, stats)
    elif mode == "direct-exec":
        return _encode_direct_exec(cmd_str, rng, stats)
    else:
        return ast


def _encode_eval(cmd_str: str, rng: random.Random, stats: LayerStats) -> dict:
    """Encode using eval chain (eval_mode='ok')."""
    method = rng.choice(["base64", "hex", "xor_base64"])

    if method == "base64":
        encoded = base64.b64encode(cmd_str.encode()).decode()
        decode_cmd = f"eval \"$(echo '{encoded}' | base64 -d)\""

    elif method == "hex":
        hex_str = cmd_str.encode().hex()
        decode_cmd = f"eval \"$(echo '{hex_str}' | xxd -r -p)\""

    elif method == "xor_base64":
        key = rng.randint(1, 255)
        xored = bytes(b ^ key for b in cmd_str.encode())
        encoded = base64.b64encode(xored).decode()
        decode_cmd = (
            f"eval \"$(echo '{encoded}' | base64 -d | "
            f"python3 -c \"import sys; sys.stdout.buffer.write("
            f"bytes(b^{key} for b in sys.stdin.buffer.read()))\")\""
        )

    stats.regions_encoded += 1
    stats.nodes_modified += 1

    return {
        "type": "command",
        "parts": [{"type": "word", "value": decode_cmd, "pos": None}],
        "pos": None,
        "_encoded": True,
    }


def _encode_no_eval(cmd_str: str, rng: random.Random, stats: LayerStats) -> dict:
    """Encode without eval — uses arithmetic printf reassembly."""
    # Build arithmetic printf chain
    hex_parts = []
    for byte in cmd_str.encode():
        hex_parts.append(f"\\\\x{byte:02x}")

    printf_str = "".join(hex_parts)
    # Use bash -c with printf reconstruction (no eval)
    decode_cmd = f"bash -c \"$(printf '{printf_str}')\""

    stats.regions_encoded += 1
    stats.nodes_modified += 1

    return {
        "type": "command",
        "parts": [{"type": "word", "value": decode_cmd, "pos": None}],
        "pos": None,
        "_encoded": True,
    }


def _encode_direct_exec(cmd_str: str, rng: random.Random, stats: LayerStats) -> dict:
    """Encode with direct exec — launches new bash process."""
    encoded = base64.b64encode(cmd_str.encode()).decode()
    decode_cmd = f"bash -c \"$(echo '{encoded}' | base64 -d)\""

    stats.regions_encoded += 1
    stats.nodes_modified += 1

    return {
        "type": "command",
        "parts": [{"type": "word", "value": decode_cmd, "pos": None}],
        "pos": None,
        "_encoded": True,
    }
