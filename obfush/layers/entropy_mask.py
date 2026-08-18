"""
Layer 9: Entropy Camouflage & Anti-Fingerprinting

Defeats statistical entropy analysis by injecting low-entropy decoy code,
dispersing high-entropy chunks, and using arithmetic embedding instead
of base64.  Must run AFTER the encode layer.
"""

from __future__ import annotations

import random

from obfush.layers.base import Layer, LayerConfig, LayerStats
from obfush.utils.entropy_utils import shannon_entropy, estimate_decoy_needed
from obfush.utils.live_chain import LiveChainGenerator


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

        target = config.entropy_target

        # Calculate how much decoy to inject
        decoy_bytes = estimate_decoy_needed(
            current_source.encode(), target
        )

        if decoy_bytes > 0:
            decoy_gen = DecoyGenerator(rng, config.name_pool)
            byte_budget = max(
                0,
                int(config.source_size * config.max_size_ratio)
                - len(current_source.encode("utf-8")),
            )
            num_blocks = min(
                max(1, decoy_bytes // 180),
                byte_budget // 180,
            )

            if num_blocks > 0 and ast.get("type") == "script":
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
    """Generates realistic-looking bash code for entropy dilution.

    Uses the procedural DecoyCorpus for comment/log generation,
    producing 31,680+ unique strings instead of the original 54
    static phrases.  Seeded via the master RNG for reproducibility.
    """

    def __init__(self, rng: random.Random, name_pool=None) -> None:
        self.rng = rng
        self.name_pool = name_pool
        self._chains = LiveChainGenerator(rng, name_pool, marker="_decoy")
        # Procedural corpus — hard dependency, not optional.
        # If this import fails, it's a real bug.  The static 54-phrase
        # corpus is dead; silently falling back would undermine the
        # 31,680-phrase OPSEC guarantee.
        from obfush.utils.decoy_corpus import DecoyCorpus
        self._corpus = DecoyCorpus(rng)

    def generate(self) -> dict:
        """Generate one atomic live decoy chain."""
        generators = [
            self._comment_block,
            self._inline_comment,
            self._log_statement,
            self._live_chain,
        ]
        return self.rng.choice(generators)()

    def _live_chain(self) -> dict:
        return self._chains.generate()

    def _comment_block(self) -> dict:
        """Realistic-looking noop comment (: "...") — misleading context.

        Uses the procedural DecoyCorpus (31,680+ unique combos).
        """
        comment = self._corpus.generate_comment()
        return self._chains.generate(comment)

    def _inline_comment(self) -> dict:
        """Bare # comment line — looks like a real developer comment.

        Emitted as : "# ..." (noop with quoted comment) since raw
        # comments would be stripped by the emitter in some code paths.
        """
        comment = self._corpus.generate_inline_comment()
        return self._chains.generate(comment)

    def _log_statement(self) -> dict:
        """Logger-style statement — procedural corpus."""
        msg = self._corpus.generate_log_message()
        return self._chains.generate(msg)


def _is_shebang_node(node: dict) -> bool:
    """Check if a node represents a shebang line (#!)."""
    if node.get("type") == "word":
        val = node.get("value", "")
        return val.startswith("#!") or val.startswith("#!/")
    if node.get("type") == "command":
        parts = node.get("parts", [])
        if parts and parts[0].get("type") == "word":
            return parts[0].get("value", "").startswith("#!")
    return False


def _interleave_decoys(
    body: list[dict],
    decoy_gen: DecoyGenerator,
    num_blocks: int,
    rng: random.Random,
) -> list[dict]:
    """Interleave decoy blocks among real code.

    Two invariants:
      1. Shebang (#!) is always the FIRST node -- bash only honors
         it on line 1.  No decoys injected before it.
      2. The LAST real statement is always last -- its exit code
         determines the script's exit code.
    """
    if not body:
        return [decoy_gen.generate() for _ in range(num_blocks)]

    result: list[dict] = []

    # Protect shebang: if first node is #!, emit it first, remove from body
    shebang = None
    if _is_shebang_node(body[0]):
        shebang = body[0]
        body = body[1:]
        if not body:
            return [shebang] + [decoy_gen.generate() for _ in range(num_blocks)]

    if shebang:
        result.append(shebang)

    # Reserve the last real statement -- nothing goes after it
    *head, tail = body
    blocks_per_gap = max(1, num_blocks // (len(head) + 1)) if head else num_blocks

    # Inject some before first real statement (but after shebang)
    for _ in range(rng.randint(1, min(blocks_per_gap, max(1, num_blocks)))):
        result.append(decoy_gen.generate())
        num_blocks -= 1

    for i, node in enumerate(head):
        result.append(node)
        # Inject between real nodes
        inject_count = rng.randint(0, min(blocks_per_gap, num_blocks))
        for _ in range(inject_count):
            result.append(decoy_gen.generate())
            num_blocks -= 1

    # Inject remaining BEFORE the tail (not after it)
    for _ in range(max(0, num_blocks)):
        result.append(decoy_gen.generate())

    # Tail is always last -- preserves exit code
    result.append(tail)

    return result
