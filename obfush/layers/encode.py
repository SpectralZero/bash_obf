"""
Layer 6: Encoding

Selectively encodes command nodes. Subprocess modes only transform commands
whose shell-state and variable semantics survive execution in a child Bash.
"""

from __future__ import annotations

import base64
import random

from obfush.layers.base import Layer, LayerConfig, LayerStats
from obfush.utils.bash_keywords import COMMON_EXTERNALS


_SUBPROCESS_SAFE_BUILTINS = frozenset({
    ":", "echo", "printf", "true", "false", "test", "[",
})

_SHELL_STATE_COMMANDS = frozenset({
    ".", "alias", "break", "builtin", "cd", "command", "continue",
    "declare", "dirs", "disown", "enable", "eval", "exec", "exit",
    "export", "fc", "getopts", "hash", "history", "jobs", "local",
    "mapfile", "popd", "pushd", "read", "readarray", "readonly",
    "return", "set", "shift", "shopt", "source", "suspend", "trap",
    "typeset", "ulimit", "umask", "unalias", "unset", "wait",
})


class LayerImpl(Layer):
    name = "encode"
    description = "Encoding (base64, xor, hex) — respects --eval-mode"
    never_rollback = True

    def transform(self, ast: dict, config: LayerConfig) -> tuple[dict, LayerStats]:
        stats = LayerStats()

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
            and rng.random() < config.intensity * 0.7
            and not ast.get("_junk")
            and not ast.get("_encoded")):
        ast = _encode_command(ast, config, stats)

    # Recurse into both body AND parts — commands inside compound nodes
    # (opaque predicates, brace groups, etc.) must also be visited.
    for key in ("body", "parts"):
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
    if not cmd_str or len(cmd_str) < 3:
        return ast

    if mode in ("no-eval", "direct-exec") and not _is_subprocess_safe(ast, cmd_str):
        stats.custom["subprocess_unsafe_skipped"] = str(
            int(stats.custom.get("subprocess_unsafe_skipped", "0")) + 1
        )
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
    # Note: xor_base64 was removed because it required python3 at runtime,
    # which isn't guaranteed on minimal targets.  The hex method previously
    # used xxd which also isn't guaranteed on minimal systems (Alpine,
    # minimal containers, some WSL installs).  Both methods now use only
    # bash builtins + coreutils (base64, printf).
    method = rng.choice(["base64", "hex_printf", "octal_printf"])

    if method == "base64":
        encoded = base64.b64encode(cmd_str.encode()).decode()
        decode_cmd = f"eval \"$(printf '%s' '{encoded}' | base64 -d)\""

    elif method == "hex_printf":
        # Build a printf format string with \xNN escapes — bash-native,
        # no xxd dependency.  Inside printf's single-quoted argument,
        # one backslash is needed:  printf '\x65\x63\x68\x6f'  → "echo"
        hex_parts = "".join(f"\\x{b:02x}" for b in cmd_str.encode())
        decode_cmd = f"eval \"$(printf '{hex_parts}')\""

    else:
        octal_parts = "".join(f"\\{b:03o}" for b in cmd_str.encode())
        decode_cmd = f"eval \"$(printf '%b' '{octal_parts}')\""

    stats.regions_encoded += 1
    stats.nodes_modified += 1

    return {
        "type": "command",
        "parts": [{"type": "word", "value": decode_cmd, "raw": decode_cmd, "pos": None}],
        "pos": None,
        "_encoded": True,
    }


def _encode_no_eval(cmd_str: str, rng: random.Random, stats: LayerStats) -> dict:
    """Encode a subprocess-safe command without eval."""
    decode_cmd = _build_subprocess_decoder(cmd_str, rng)

    stats.regions_encoded += 1
    stats.nodes_modified += 1

    return {
        "type": "command",
        "parts": [{"type": "word", "value": decode_cmd, "raw": decode_cmd, "pos": None}],
        "pos": None,
        "_encoded": True,
    }


def _encode_direct_exec(cmd_str: str, rng: random.Random, stats: LayerStats) -> dict:
    """Encode a subprocess-safe command in an isolated Bash process."""
    decode_cmd = _build_subprocess_decoder(cmd_str, rng)

    stats.regions_encoded += 1
    stats.nodes_modified += 1

    return {
        "type": "command",
        "parts": [{"type": "word", "value": decode_cmd, "raw": decode_cmd, "pos": None}],
        "pos": None,
        "_encoded": True,
    }


def _build_subprocess_decoder(cmd_str: str, rng: random.Random) -> str:
    """Build one of three equivalent command reconstruction expressions."""
    method = rng.choice(("base64", "hex", "octal"))
    if method == "base64":
        encoded = base64.b64encode(cmd_str.encode()).decode()
        expression = f"printf '%s' '{encoded}' | base64 -d"
    elif method == "hex":
        escaped = "".join(f"\\x{byte:02x}" for byte in cmd_str.encode())
        expression = f"printf '%b' '{escaped}'"
    else:
        escaped = "".join(f"\\{byte:03o}" for byte in cmd_str.encode())
        expression = f"printf '%b' '{escaped}'"
    return f'bash -c "$({expression})"'


def _is_subprocess_safe(ast: dict, cmd_str: str) -> bool:
    """Conservatively decide whether an extra Bash process preserves behavior."""
    parts = ast.get("parts", [])
    if not parts or not isinstance(parts[0], dict) or parts[0].get("type") != "word":
        return False

    command = parts[0].get("value", "")
    if not isinstance(command, str) or not command or command in _SHELL_STATE_COMMANDS:
        return False
    if command not in COMMON_EXTERNALS and command not in _SUBPROCESS_SAFE_BUILTINS:
        return False

    # An inner Bash cannot see unexported variables/functions and gives shell
    # specials such as $$, $?, and PIPESTATUS different values.
    if "$" in cmd_str or "`" in cmd_str:
        return False

    return True
