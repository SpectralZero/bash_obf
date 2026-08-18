"""Layer 4: side-effect-contained live decoy injection."""

from __future__ import annotations

import random

from obfush.layers.base import Layer, LayerConfig, LayerStats
from obfush.utils.live_chain import LiveChainGenerator


class LayerImpl(Layer):
    name = "junk-inject"
    description = "Live decoy dependency chains"

    def transform(self, ast: dict, config: LayerConfig) -> tuple[dict, LayerStats]:
        stats = LayerStats()
        rng = config.rng
        catalogue = JunkCatalogue(rng, config.intensity, config.name_pool)

        ast = _inject_walk(ast, config, catalogue, stats, depth=0)
        return ast, stats

    def estimate_size_increase(self, config: LayerConfig) -> float:
        return 1.3 + config.intensity * 0.7  # up to 2x at max


class JunkCatalogue:
    """Generates atomic, side-effect-contained live decoy chains."""

    def __init__(self, rng: random.Random, intensity: float, name_pool=None) -> None:
        self.rng = rng
        self.intensity = intensity
        self.name_pool = name_pool
        self._chains = LiveChainGenerator(rng, name_pool, marker="_junk")

    def generate(self) -> dict:
        """Generate a random junk AST node."""
        generators = [
            self._chained_assignment,
            self._operational_chain,
            self._called_noop_function,
        ]
        gen = self.rng.choice(generators)
        return gen()

    def _chained_assignment(self) -> dict:
        return self._chains.generate()

    def _operational_chain(self) -> dict:
        messages = [
            "initialising...", "loading configuration", "checking dependencies",
            "validating input", "preparing environment", "sync complete",
            "cache warm", "module loaded", "ready", "standby",
        ]
        return self._chains.generate(self.rng.choice(messages))

    def _called_noop_function(self) -> dict:
        return self._chains.generate_function_chain()


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
                        stats.nodes_modified += 1
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
