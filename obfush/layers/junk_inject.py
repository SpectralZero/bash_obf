"""
Layer 4: Junk Injection (Dead Code)

Injects believable but useless code that executes harmlessly.
Never alters real variables or control flow. Appears as normal
operational code to a human analyst.
"""

from __future__ import annotations

import random
from typing import Any

from obfush.layers.base import Layer, LayerConfig, LayerStats


class LayerImpl(Layer):
    name = "junk-inject"
    description = "Dead code & timing jitter"

    def transform(self, ast: dict, config: LayerConfig) -> tuple[dict, LayerStats]:
        stats = LayerStats()
        rng = config.rng
        catalogue = JunkCatalogue(rng, config.intensity)

        ast = _inject_walk(ast, config, catalogue, stats, depth=0)
        return ast, stats

    def estimate_size_increase(self, config: LayerConfig) -> float:
        return 1.3 + config.intensity * 0.7  # up to 2x at max


class JunkCatalogue:
    """Generates diverse dead code blocks."""

    def __init__(self, rng: random.Random, intensity: float) -> None:
        self.rng = rng
        self.intensity = intensity
        self._counter = 0

    def _next_id(self) -> str:
        """Generate a unique junk variable suffix."""
        self._counter += 1
        return f"0x{self.rng.randint(0x100, 0xffff):04x}"

    def generate(self) -> dict:
        """Generate a random junk AST node."""
        generators = [
            self._assigned_never_read,
            self._noop_chain,
            self._dead_conditional,
            self._dead_function,
            self._timing_jitter,
            self._discarded_subshell,
        ]
        gen = self.rng.choice(generators)
        return gen()

    def _assigned_never_read(self) -> dict:
        """Variable assigned but never read: _junk_0x3f1="$(whoami || id -un)" """
        jid = self._next_id()
        values = [
            '"$(whoami 2>/dev/null || id -un 2>/dev/null)"',
            '"$(date +%s 2>/dev/null)"',
            '"$(hostname -s 2>/dev/null || echo localhost)"',
            '"$(uname -r 2>/dev/null)"',
            '"${RANDOM:-0}"',
            '"/tmp/.cache_${$}"',
            '"$(printf "%d" $((RANDOM % 256)))"',
        ]
        value = self.rng.choice(values)
        return {
            "type": "assignment",
            "name": f"_jnk_{jid}",
            "value": value,
            "pos": None,
            "_junk": True,
        }

    def _noop_chain(self) -> dict:
        """No-op chain: : "initialising..." && true && [[ 1 -eq 1 ]]"""
        messages = [
            "initialising...", "loading configuration", "checking dependencies",
            "validating input", "preparing environment", "sync complete",
            "cache warm", "module loaded", "ready", "standby",
        ]
        msg = self.rng.choice(messages)
        return {
            "type": "command",
            "parts": [
                {"type": "word", "value": ":", "pos": None},
                {"type": "word", "value": f'"{msg}"', "pos": None},
            ],
            "pos": None,
            "_junk": True,
        }

    def _dead_conditional(self) -> dict:
        """Dead conditional that never fires."""
        jid = self._next_id()
        return {
            "type": "compound",
            "kind": "if",
            "parts": [
                # Condition: always false
                {
                    "type": "test_expr",
                    "original_style": "[[",
                    "test_parts": [
                        {"type": "word", "value": "-n", "pos": None},
                        {"type": "word", "value": f'"${{_phantom_{jid}:-}}"', "pos": None},
                    ],
                    "parts": [],
                    "pos": None,
                },
                # Body: harmless
                {
                    "type": "command",
                    "parts": [
                        {"type": "word", "value": ":", "pos": None},
                    ],
                    "pos": None,
                },
            ],
            "pos": None,
            "_junk": True,
        }

    def _dead_function(self) -> dict:
        """Dead function that is never called."""
        jid = self._next_id()
        bodies = [
            [{"type": "command", "parts": [
                {"type": "word", "value": ":", "pos": None},
                {"type": "word", "value": '"unused function"', "pos": None},
            ], "pos": None}],
            [{"type": "command", "parts": [
                {"type": "word", "value": "return", "pos": None},
                {"type": "word", "value": "0", "pos": None},
            ], "pos": None}],
        ]
        return {
            "type": "function_def",
            "name": f"_fn_{jid}",
            "body": {
                "type": "compound",
                "kind": "{",
                "parts": self.rng.choice(bodies),
                "pos": None,
            },
            "pos": None,
            "_junk": True,
        }

    def _timing_jitter(self) -> dict:
        """Small timing jitter: sleep 0.N"""
        delay = self.rng.randint(1, 3)
        return {
            "type": "command",
            "parts": [
                {"type": "word", "value": "sleep", "pos": None},
                {"type": "word", "value": f"0.{delay}", "pos": None},
            ],
            "pos": None,
            "_junk": True,
        }

    def _discarded_subshell(self) -> dict:
        """Subshell that discards output: ( : "$(hostname)" ) """
        cmds = ['"$(hostname 2>/dev/null)"', '"$(date 2>/dev/null)"', '"$(id 2>/dev/null)"']
        return {
            "type": "compound",
            "kind": "(",
            "parts": [{
                "type": "command",
                "parts": [
                    {"type": "word", "value": ":", "pos": None},
                    {"type": "word", "value": self.rng.choice(cmds), "pos": None},
                ],
                "pos": None,
            }],
            "pos": None,
            "_junk": True,
        }


def _is_safe_injection_point(node: dict, parent: dict | None) -> bool:
    """Check if it's safe to inject junk before/after this node."""
    if not isinstance(node, dict):
        return False

    # Never inject inside pipelines
    if parent and parent.get("type") == "pipeline":
        return False

    # Never inject inside command substitutions
    if parent and parent.get("type") == "expansion":
        return False

    # Never inject inside test expressions
    if parent and parent.get("type") == "test_expr":
        return False

    # Don't inject right before a command with set -e implications
    if node.get("type") == "command":
        parts = node.get("parts", [])
        if parts and parts[0].get("type") == "word":
            cmd = parts[0].get("value", "")
            if cmd in ("set", "trap", "exit", "return", "exec"):
                return False

    return True


def _inject_walk(
    ast: dict,
    config: LayerConfig,
    catalogue: JunkCatalogue,
    stats: LayerStats,
    depth: int,
    parent: dict | None = None,
) -> dict:
    """Walk AST and inject junk at safe points."""
    if not isinstance(ast, dict):
        return ast

    # Process list-type children (body, parts)
    for key in ("body",):
        val = ast.get(key)
        if isinstance(val, list):
            new_list: list[dict] = []
            for item in val:
                if isinstance(item, dict):
                    # Chance to inject BEFORE this node
                    if (_is_safe_injection_point(item, ast)
                            and config.rng.random() < config.intensity * 0.3
                            and depth < 3):
                        junk = catalogue.generate()
                        new_list.append(junk)
                        stats.junk_blocks_injected += 1
                        stats.nodes_modified += 1

                    new_list.append(
                        _inject_walk(item, config, catalogue, stats, depth + 1, ast)
                    )

                    # Chance to inject AFTER this node
                    if (_is_safe_injection_point(item, ast)
                            and config.rng.random() < config.intensity * 0.2
                            and depth < 3):
                        junk = catalogue.generate()
                        new_list.append(junk)
                        stats.junk_blocks_injected += 1
                else:
                    new_list.append(item)
            ast[key] = new_list

    # For compound/script with 'parts' that are statement lists
    if ast.get("type") in ("script", "compound"):
        key = "parts" if ast.get("type") == "compound" else "body"
        val = ast.get(key)
        if isinstance(val, list) and key == "body":
            pass  # already handled above
        elif isinstance(val, list) and ast.get("type") == "compound" and ast.get("kind") in ("{", "("):
            new_list = []
            for item in val:
                if isinstance(item, dict):
                    if (_is_safe_injection_point(item, ast)
                            and config.rng.random() < config.intensity * 0.25
                            and depth < 3):
                        new_list.append(catalogue.generate())
                        stats.junk_blocks_injected += 1
                    new_list.append(
                        _inject_walk(item, config, catalogue, stats, depth + 1, ast)
                    )
                else:
                    new_list.append(item)
            ast[key] = new_list

    # Recurse into other children
    for key in ("parts", "body"):
        val = ast.get(key)
        if isinstance(val, dict):
            ast[key] = _inject_walk(val, config, catalogue, stats, depth + 1, ast)

    return ast
