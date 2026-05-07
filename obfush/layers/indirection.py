"""
Layer 7: Indirection & Dynamic Dispatch

Obscures which command actually executes by routing through
variable dereferencing, function pointer maps, and arithmetic
index obfuscation.
"""

from __future__ import annotations

import random
from typing import Any

from obfush.layers.base import Layer, LayerConfig, LayerStats


class LayerImpl(Layer):
    name = "indirection"
    description = "Indirect dispatch & pointer chains"

    def transform(self, ast: dict, config: LayerConfig) -> tuple[dict, LayerStats]:
        stats = LayerStats()
        rng = config.rng
        dispatcher = IndirectionDispatcher(rng, config)
        ast = _indirect_walk(ast, config, dispatcher, stats)

        # Prepend dispatch setup code to script body
        setup = dispatcher.get_setup_nodes()
        if setup and ast.get("type") == "script":
            ast["body"] = setup + ast.get("body", [])

        return ast, stats

    def estimate_size_increase(self, config: LayerConfig) -> float:
        return 1.3 + config.intensity * 0.4


class IndirectionDispatcher:
    """Manages indirection tables and generates dispatch code."""

    def __init__(self, rng: random.Random, config: LayerConfig) -> None:
        self.rng = rng
        self.config = config
        self._var_dispatches: list[dict] = []  # setup assignment nodes
        self._func_maps: list[dict] = []       # function map declarations
        self._counter = 0

    def _next_id(self) -> str:
        self._counter += 1
        return f"_d{self.rng.randint(0x100, 0xffff):04x}"

    def indirect_command(self, cmd_name: str) -> tuple[str, list[dict]]:
        """Create an indirect reference for a command name.

        Returns (indirect_expression, setup_nodes).
        """
        if self.config.eval_mode == "ok" and self.rng.random() < 0.3:
            return self._eval_chain_indirect(cmd_name)
        else:
            return self._variable_indirect(cmd_name)

    def _variable_indirect(self, cmd_name: str) -> tuple[str, list[dict]]:
        """Simple variable dispatch: _cXX=cmd; "${_cXX}" args..."""
        var_name = self._next_id()
        # Value is the raw command name. The emitter will add appropriate
        # quoting if needed; embedding literal `"..."` would result in
        # the variable holding "cmd" (with quotes) which bash treats as
        # a command name including the quote characters.
        setup = {
            "type": "assignment",
            "name": var_name,
            "value": cmd_name,
            "pos": None,
        }
        self._var_dispatches.append(setup)
        return f'"${{{var_name}}}"', [setup]

    def _eval_chain_indirect(self, cmd_name: str) -> tuple[str, list[dict]]:
        """Eval-based indirection: _a=_b; _b=cmd; eval "${!_a}" """
        var_a = self._next_id()
        var_b = self._next_id()
        setup_b = {
            "type": "assignment",
            "name": var_b,
            "value": cmd_name,
            "pos": None,
        }
        setup_a = {
            "type": "assignment",
            "name": var_a,
            "value": var_b,
            "pos": None,
        }
        self._var_dispatches.extend([setup_b, setup_a])
        return f'"${{!{var_a}}}"', [setup_b, setup_a]

    def create_function_map(self, mappings: dict[str, str]) -> tuple[str, str, list[dict]]:
        """Create a function pointer map.

        Args:
            mappings: key → function_name mapping.

        Returns:
            (map_var_name, key_expression, setup_nodes)
        """
        map_name = self._next_id()
        pairs = " ".join(f'[{k}]={v}' for k, v in mappings.items())
        setup = {
            "type": "command",
            "parts": [
                {"type": "word", "value": "declare", "pos": None},
                {"type": "word", "value": "-A", "pos": None},
                {"type": "word", "value": f'{map_name}=({pairs})', "pos": None},
            ],
            "pos": None,
        }
        self._func_maps.append(setup)
        return map_name, list(mappings.keys())[0], [setup]

    def get_setup_nodes(self) -> list[dict]:
        """Get all setup nodes to prepend to the script."""
        return self._func_maps + self._var_dispatches


# Commands worth indirecting (external tools that reveal intent)
_INDIRECTABLE_COMMANDS = frozenset({
    "curl", "wget", "nc", "ncat", "socat",
    "ssh", "scp", "rsync",
    "base64", "xxd", "openssl",
    "cat", "grep", "awk", "sed",
    "chmod", "chown", "mkdir", "rm",
    "crontab", "systemctl",
    "python", "python3", "perl", "ruby",
    "bash", "sh",
    "tar", "gzip", "zip",
    "kill", "pkill",
    "nohup", "sleep",
})


def _indirect_walk(
    ast: dict,
    config: LayerConfig,
    dispatcher: IndirectionDispatcher,
    stats: LayerStats,
) -> dict:
    """Walk AST and apply indirection to commands."""
    if not isinstance(ast, dict):
        return ast

    rng = config.rng
    node_type = ast.get("type", "")
    stats.nodes_visited += 1

    # Indirect command names
    if node_type == "command" and not ast.get("_encoded") and not ast.get("_junk"):
        parts = ast.get("parts", [])
        if (parts and parts[0].get("type") == "word"
                and rng.random() < config.intensity * 0.5):
            cmd_name = parts[0].get("value", "")
            if cmd_name in _INDIRECTABLE_COMMANDS:
                indirect_expr, setup = dispatcher.indirect_command(cmd_name)
                parts[0]["value"] = indirect_expr
                stats.indirections_added += 1
                stats.nodes_modified += 1

    # Recurse
    for key in ("parts", "body", "test_parts"):
        val = ast.get(key)
        if isinstance(val, list):
            ast[key] = [
                _indirect_walk(i, config, dispatcher, stats)
                if isinstance(i, dict) else i
                for i in val
            ]
        elif isinstance(val, dict):
            ast[key] = _indirect_walk(val, config, dispatcher, stats)

    return ast
