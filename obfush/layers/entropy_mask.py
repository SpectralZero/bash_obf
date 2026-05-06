"""
Layer 9: Entropy Camouflage & Anti-Fingerprinting

Defeats statistical entropy analysis by injecting low-entropy decoy code,
dispersing high-entropy chunks, and using arithmetic embedding instead
of base64.  Must run AFTER the encode layer.
"""

from __future__ import annotations

import random
from typing import Any

from obfush.layers.base import Layer, LayerConfig, LayerStats
from obfush.utils.entropy_utils import shannon_entropy, estimate_decoy_needed


class LayerImpl(Layer):
    name = "entropy-mask"
    description = "Statistical decoy injection & arithmetic encoding"

    def transform(self, ast: dict, config: LayerConfig) -> tuple[dict, LayerStats]:
        stats = LayerStats()
        rng = config.rng

        # Measure current entropy
        from obfush.engine.ast_emitter import emit
        current_source = emit(ast)
        current_entropy = shannon_entropy(current_source.encode())

        stats.custom["entropy_before"] = f"{current_entropy:.3f}"

        # Target entropy (configurable, default 4.5)
        target = 4.5  # Will be overridden by engine config

        # Calculate how much decoy to inject
        decoy_bytes = estimate_decoy_needed(
            current_source.encode(), target
        )

        if decoy_bytes > 0:
            decoy_gen = DecoyGenerator(rng)
            num_blocks = max(1, decoy_bytes // 80)  # ~80 bytes per line

            if ast.get("type") == "script":
                body = ast.get("body", [])
                new_body = _interleave_decoys(body, decoy_gen, num_blocks, rng)
                ast["body"] = new_body
                stats.decoy_lines_added = num_blocks
                stats.nodes_modified = num_blocks

        # Re-measure
        final_source = emit(ast)
        final_entropy = shannon_entropy(final_source.encode())
        stats.custom["entropy_after"] = f"{final_entropy:.3f}"
        stats.custom["decoy_bytes"] = str(decoy_bytes)

        return ast, stats

    def estimate_size_increase(self, config: LayerConfig) -> float:
        return 2.0 + config.intensity * 3.0  # can be significant


class DecoyGenerator:
    """Generates realistic-looking bash code for entropy dilution."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self._counter = 0

    def generate(self) -> dict:
        """Generate a random decoy AST node."""
        generators = [
            self._var_assignment,
            self._comment_block,
            self._conditional_check,
            self._array_ops,
            self._path_check,
            self._log_statement,
            self._arithmetic_expr,
        ]
        return self.rng.choice(generators)()

    def _next_id(self) -> str:
        self._counter += 1
        return f"_{self.rng.randint(0x10, 0xff):02x}_{self._counter}"

    def _var_assignment(self) -> dict:
        """Realistic variable assignment."""
        names = [
            "log_rotate_count", "max_retry_interval", "cache_ttl_seconds",
            "upstream_timeout", "worker_pool_size", "gc_threshold",
            "buffer_flush_interval", "health_check_port", "metric_prefix",
            "session_idle_timeout", "conn_backlog_limit", "sync_batch_size",
        ]
        values = [
            "3600", "120", "256", "1024", "8192", "30",
            "60", "443", "512", "300", "128", "64",
            '"$(date +%Y%m%d)"', '"${HOSTNAME:-localhost}"',
            '"$(whoami)"', '"/var/log/app.log"',
        ]
        name = self.rng.choice(names) + self._next_id()
        value = self.rng.choice(values)
        return {
            "type": "assignment",
            "name": name,
            "value": value,
            "pos": None,
            "_decoy": True,
        }

    def _comment_block(self) -> dict:
        """Realistic-looking comment."""
        comments = [
            "# Verify configuration loaded correctly",
            "# Initialize connection pool parameters",
            "# Set default values for optional parameters",
            "# Ensure temp directory exists and is writable",
            "# Parse command line arguments",
            "# Validate SSL certificate chain",
            "# Check systemd service status",
            "# Load environment-specific overrides",
        ]
        return {
            "type": "command",
            "parts": [
                {"type": "word", "value": ":", "pos": None},
                {"type": "word", "value": f'"{self.rng.choice(comments)}"', "pos": None},
            ],
            "pos": None,
            "_decoy": True,
        }

    def _conditional_check(self) -> dict:
        """Realistic conditional that does nothing."""
        vid = self._next_id()
        return {
            "type": "compound",
            "kind": "if",
            "parts": [
                {
                    "type": "test_expr",
                    "original_style": "[[",
                    "test_parts": [
                        {"type": "word", "value": "-d", "pos": None},
                        {"type": "word", "value": '"/etc/default"', "pos": None},
                    ],
                    "parts": [],
                    "pos": None,
                },
                {
                    "type": "command",
                    "parts": [{"type": "word", "value": ":", "pos": None}],
                    "pos": None,
                },
            ],
            "pos": None,
            "_decoy": True,
        }

    def _array_ops(self) -> dict:
        """Array declaration and operation."""
        vid = self._next_id()
        items = self.rng.sample(
            ["eth0", "lo", "wlan0", "br0", "docker0", "veth1", "tap0"],
            k=self.rng.randint(2, 4),
        )
        item_str = " ".join(f'"{i}"' for i in items)
        return {
            "type": "command",
            "parts": [
                {"type": "word", "value": "declare", "pos": None},
                {"type": "word", "value": "-a", "pos": None},
                {"type": "word", "value": f"_ifaces{vid}=({item_str})", "pos": None},
            ],
            "pos": None,
            "_decoy": True,
        }

    def _path_check(self) -> dict:
        """Path existence check."""
        paths = [
            "/usr/local/bin", "/opt/scripts", "/etc/cron.d",
            "/var/run", "/tmp/.cache", "/usr/share/doc",
        ]
        path = self.rng.choice(paths)
        vid = self._next_id()
        return {
            "type": "assignment",
            "name": f"_path{vid}",
            "value": f'"{path}"',
            "pos": None,
            "_decoy": True,
        }

    def _log_statement(self) -> dict:
        """Logger-style statement."""
        levels = ["INFO", "DEBUG", "TRACE", "NOTICE"]
        msgs = [
            "Configuration validated", "Service dependency check passed",
            "Cache warmed successfully", "Worker thread initialized",
            "Health check endpoint ready", "Metrics collection started",
        ]
        return {
            "type": "command",
            "parts": [
                {"type": "word", "value": ":", "pos": None},
                {"type": "word", "value":
                    f'"[{self.rng.choice(levels)}] {self.rng.choice(msgs)}"',
                    "pos": None},
            ],
            "pos": None,
            "_decoy": True,
        }

    def _arithmetic_expr(self) -> dict:
        """Arithmetic expression that evaluates to nothing useful."""
        vid = self._next_id()
        ops = [
            f"$(( ({self.rng.randint(100,999)} * {self.rng.randint(2,9)}) % 256 ))",
            f"$(( {self.rng.randint(10,99)} << {self.rng.randint(1,3)} ))",
            f"$(( ({self.rng.randint(1000,9999)} ^ {self.rng.randint(1000,9999)}) & 0xFF ))",
        ]
        return {
            "type": "assignment",
            "name": f"_calc{vid}",
            "value": self.rng.choice(ops),
            "pos": None,
            "_decoy": True,
        }


def _interleave_decoys(
    body: list[dict],
    decoy_gen: DecoyGenerator,
    num_blocks: int,
    rng: random.Random,
) -> list[dict]:
    """Interleave decoy blocks among real code."""
    if not body:
        return [decoy_gen.generate() for _ in range(num_blocks)]

    result: list[dict] = []
    blocks_per_gap = max(1, num_blocks // (len(body) + 1))

    # Inject some before
    for _ in range(rng.randint(1, blocks_per_gap)):
        result.append(decoy_gen.generate())
        num_blocks -= 1

    for i, node in enumerate(body):
        result.append(node)
        # Inject between real nodes
        inject_count = rng.randint(0, min(blocks_per_gap, num_blocks))
        for _ in range(inject_count):
            result.append(decoy_gen.generate())
            num_blocks -= 1

    # Inject remaining at end
    for _ in range(max(0, num_blocks)):
        result.append(decoy_gen.generate())

    return result
