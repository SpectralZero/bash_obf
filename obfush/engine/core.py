"""
PolymorphicEngine — the main orchestrator.

Pipeline: parse → normalise → select layers → transform → verify → emit
"""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass
from typing import Any

from rich.console import Console
from rich.table import Table

from obfush.engine.seed import generate_seed, create_rng, derive_layer_seed
from obfush.engine.layer_selector import LayerSelector, LayerPlan
from obfush.layers import get_layer
from obfush.layers.base import LayerConfig, LayerStats
from obfush.logging_utils import get_logger
from obfush.utils.name_pool import NamePool


def _collect_ast_identifiers(ast: dict) -> set[str]:
    """Collect existing identifier fields before synthetic names are allocated."""
    identifiers: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key in ("name", "variable", "var_name"):
                value = node.get(key)
                if isinstance(value, str) and value.isidentifier():
                    identifiers.add(value)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(ast)
    return identifiers


def _trim_decoys_to_budget(
    ast: dict,
    output: str,
    source_size: int,
    max_size_ratio: float,
    emitter,
) -> tuple[str, int]:
    """Remove complete synthetic decoy nodes until output fits the byte budget."""
    budget = max(source_size, int(source_size * max_size_ratio))
    if len(output.encode("utf-8")) <= budget:
        return output, 0

    removable: list[tuple[list, dict]] = []

    def collect(node: Any, parent_list: list | None = None) -> None:
        if isinstance(node, dict):
            if parent_list is not None and (node.get("_junk") or node.get("_decoy")):
                removable.append((parent_list, node))
                return
            for value in node.values():
                collect(value)
        elif isinstance(node, list):
            for value in node:
                collect(value, node)

    collect(ast)
    removed = 0
    for parent, node in reversed(removable):
        try:
            parent.remove(node)
        except ValueError:
            continue
        removed += 1
        output = emitter(ast)
        if len(output.encode("utf-8")) <= budget:
            break

    return output, removed


@dataclass
class EngineConfig:
    """Top-level engine configuration (mirrors CLI options)."""
    seed: int | None = None
    intensity: float = 0.8
    force_layers: list[str] | None = None
    disable_layers: list[str] | None = None
    min_layers: int = 4
    eval_mode: str = "ok"
    entropy_target: float = 4.5
    verify: bool = False
    test_input: str | None = None
    verbose: bool = False
    dry_run: bool = False
    dump_ast: str | None = None
    max_size_ratio: float = 3.0
    log_level: str = "WARNING"

    def __post_init__(self) -> None:
        if self.max_size_ratio < 1.0:
            raise ValueError(
                f"max_size_ratio must be at least 1.0, got {self.max_size_ratio}"
            )
        if not 0.0 <= self.entropy_target <= 8.0:
            raise ValueError(
                f"entropy_target must be 0.0-8.0, got {self.entropy_target}"
            )
        if self.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"Unsupported log_level: {self.log_level}")


@dataclass
class EngineResult:
    """Result of an obfuscation run."""
    source: str
    output: str
    seed: int
    layers_applied: list[str]
    layer_stats: dict[str, LayerStats]
    elapsed_ms: float
    verified: bool = False


class PolymorphicEngine:
    """Main obfuscation engine.

    Orchestrates the full pipeline from source bash to obfuscated output.
    Every invocation with a different seed produces unique output.
    """

    def __init__(self, config: EngineConfig | None = None) -> None:
        self.config = config or EngineConfig()
        self.console = Console(stderr=True)
        self.logger = get_logger("engine")

    def run(self, source: str) -> EngineResult:
        """Execute the full obfuscation pipeline.

        Args:
            source: Original bash script source code.

        Returns:
            EngineResult with obfuscated output and metadata.
        """
        start_time = time.perf_counter()

        # Step 1: Seed
        if self.config.seed is not None:
            seed = self.config.seed
        else:
            seed = generate_seed(source)

        self.logger.info(
            "engine_started",
            extra={
                "event": "engine_started",
                "seed": seed,
                "source_bytes": len(source.encode("utf-8")),
            },
        )

        if self.config.verbose:
            self.console.print(f"[dim]Seed: {seed}[/dim]")

        # Step 1b: Strip comments (OPSEC)
        # Must run BEFORE parsing: removes operator comments, TODOs, author
        # tags, infrastructure hints.  Shebang is preserved.  This makes
        # comment leakage deterministic — bashlex would drop comments when
        # it parses successfully but preserve them in the opaque-blob
        # fallback, creating non-deterministic privacy.
        from obfush.engine.comment_strip import strip_comments
        source = strip_comments(source)

        if self.config.verbose:
            self.console.print("[dim]Comments stripped (OPSEC)[/dim]")

        # Step 2: Parse
        from obfush.engine.ast_parser import parse_bash
        ast = parse_bash(source)

        if self.config.dump_ast:
            import json
            with open(self.config.dump_ast, "w") as f:
                json.dump(ast, f, indent=2, default=str)
            self.console.print(f"[dim]AST dumped to {self.config.dump_ast}[/dim]")

        # Step 3: Normalise
        from obfush.engine.normalizer import normalize
        ast = normalize(ast)

        # Step 4: Select layers
        selector = LayerSelector(
            master_seed=seed,
            intensity=self.config.intensity,
            force_layers=self.config.force_layers,
            disable_layers=self.config.disable_layers,
            min_layers=self.config.min_layers,
            eval_mode=self.config.eval_mode,
        )
        plans = selector.select()

        if self.config.verbose:
            self._print_plan(plans)

        if self.config.dry_run:
            elapsed = (time.perf_counter() - start_time) * 1000
            return EngineResult(
                source=source, output=source, seed=seed,
                layers_applied=[p.name for p in plans],
                layer_stats={}, elapsed_ms=elapsed,
            )

        # Step 5: Transform
        all_stats: dict[str, LayerStats] = {}
        applied_layers: list[str] = []
        name_pool = NamePool(create_rng(derive_layer_seed(seed, "name-pool")))
        name_pool.register_existing(_collect_ast_identifiers(ast))
        from obfush.engine.ast_emitter import emit
        source_size = len(source.encode("utf-8"))
        # Scale budget for small scripts: they need proportionally more room
        # because even basic hex-escape encoding expands ~3-4x per string.
        effective_ratio = self.config.max_size_ratio
        if source_size < 2048:
            effective_ratio = max(effective_ratio, 5.0)
        size_budget = max(source_size, int(source_size * effective_ratio))
        for plan in plans:
            if self.config.verbose:
                self.console.print(f"[bold cyan]▸ Applying {plan.name}[/bold cyan] "
                                   f"(intensity={plan.intensity:.2f})")

            layer = get_layer(plan.name)
            rng = create_rng(plan.seed)
            layer_start = time.perf_counter()
            self.logger.debug(
                "layer_started",
                extra={
                    "event": "layer_started",
                    "layer": plan.name,
                    "intensity": plan.intensity,
                },
            )

            layer_config = LayerConfig(
                intensity=plan.intensity,
                seed=plan.seed,
                rng=rng,
                eval_mode=self.config.eval_mode,
                name_pool=name_pool,
                source_size=source_size,
                max_size_ratio=self.config.max_size_ratio,
                entropy_target=self.config.entropy_target,
            )

            # Layers mutate nested nodes in place. A shallow copy cannot restore
            # the tree when validation rejects a transformation.
            ast_before = copy.deepcopy(ast)
            ast, stats = layer.transform(ast, layer_config)
            all_stats[plan.name] = stats

            # Structural validation
            if not layer.validate(ast_before, ast):
                self.console.print(
                    f"[bold red]✗ Layer {plan.name} failed validation![/bold red]"
                )
                ast = ast_before  # rollback
                stats.custom["rolled_back"] = "validation"
            else:
                candidate = emit(ast)
                candidate, trimmed = _trim_decoys_to_budget(
                    ast,
                    candidate,
                    source_size,
                    effective_ratio,
                    emit,
                )
                if trimmed:
                    stats.custom["decoys_trimmed"] = str(trimmed)
                if len(candidate.encode("utf-8")) > size_budget:
                    if layer.never_rollback:
                        # Security-critical layer — keep it, accept the size.
                        # Decoys were already trimmed above; this is the minimum
                        # size needed for real obfuscation.
                        applied_layers.append(plan.name)
                        stats.custom["over_budget_kept"] = "security-critical"
                    else:
                        ast = ast_before
                        stats.custom["rolled_back"] = "size-budget"
                else:
                    applied_layers.append(plan.name)

            stats.elapsed_ms = (time.perf_counter() - layer_start) * 1000
            self.logger.debug(
                "layer_completed",
                extra={
                    "event": "layer_completed",
                    "layer": plan.name,
                    "elapsed_ms": round(stats.elapsed_ms, 3),
                    "rolled_back": stats.custom.get("rolled_back"),
                },
            )

            if self.config.verbose:
                self._print_stats(plan.name, stats)

        # Step 6: Emit
        output = emit(ast)
        output, removed_decoys = _trim_decoys_to_budget(
            ast,
            output,
            len(source.encode("utf-8")),
            effective_ratio,
            emit,
        )
        if removed_decoys:
            size_stats = all_stats.get("entropy-mask") or all_stats.get("junk-inject")
            if size_stats is not None:
                size_stats.custom["decoys_trimmed"] = str(removed_decoys)

        # Step 7: Verify (optional)
        verified = False
        if self.config.verify:
            from obfush.engine.verifier import Verifier
            verifier = Verifier(timeout=30)
            verified = verifier.verify(
                original_source=source,
                obfuscated_source=output,
                test_input=self.config.test_input,
            )
            status = "[bold green]✓ PASSED[/bold green]" if verified else "[bold red]✗ FAILED[/bold red]"
            self.console.print(f"Equivalence verification: {status}")

        elapsed = (time.perf_counter() - start_time) * 1000
        self.logger.info(
            "engine_completed",
            extra={
                "event": "engine_completed",
                "seed": seed,
                "elapsed_ms": round(elapsed, 3),
                "output_bytes": len(output.encode("utf-8")),
                "layers_applied": applied_layers,
                "verified": verified,
            },
        )

        if self.config.verbose:
            self._print_summary(seed, plans, elapsed, output)

        return EngineResult(
            source=source, output=output, seed=seed,
            layers_applied=applied_layers,
            layer_stats=all_stats, elapsed_ms=elapsed,
            verified=verified,
        )

    def _print_plan(self, plans: list[LayerPlan]) -> None:
        """Print the layer execution plan."""
        table = Table(title="Layer Execution Plan", show_header=True)
        table.add_column("Order", style="dim", width=5)
        table.add_column("Layer", style="bold cyan")
        table.add_column("Intensity", justify="right")
        for i, plan in enumerate(plans, 1):
            bar = "█" * int(plan.intensity * 10) + "░" * (10 - int(plan.intensity * 10))
            table.add_row(str(i), plan.name, f"{plan.intensity:.2f} {bar}")
        self.console.print(table)

    def _print_stats(self, name: str, stats: LayerStats) -> None:
        """Print per-layer stats."""
        parts = []
        if stats.nodes_modified:
            parts.append(f"modified={stats.nodes_modified}")
        if stats.identifiers_mangled:
            parts.append(f"mangled={stats.identifiers_mangled}")
        if stats.strings_shredded:
            parts.append(f"shredded={stats.strings_shredded}")
        if stats.split_reconstructions:
            parts.append(f"split={stats.split_reconstructions}")
        if stats.xor_reconstructions:
            parts.append(f"xor={stats.xor_reconstructions}")
        if stats.junk_blocks_injected:
            parts.append(f"junk={stats.junk_blocks_injected}")
        if stats.custom:
            for k, v in stats.custom.items():
                parts.append(f"{k}={v}")
        parts.append(f"time={stats.elapsed_ms:.2f}ms")
        if parts:
            self.console.print(f"  [dim]{', '.join(parts)}[/dim]")

    def _print_summary(
        self, seed: int, plans: list[LayerPlan], elapsed: float, output: str
    ) -> None:
        """Print final summary."""
        from obfush.utils.entropy_utils import shannon_entropy
        entropy = shannon_entropy(output.encode("utf-8"))
        self.console.print()
        self.console.print("[bold]═══ obfush Complete ═══[/bold]")
        self.console.print(f"  Seed:     {seed}")
        self.console.print(f"  Layers:   {len(plans)}")
        self.console.print(f"  Output:   {len(output)} bytes")
        self.console.print(f"  Entropy:  {entropy:.3f} bits/byte")
        self.console.print(f"  Time:     {elapsed:.1f} ms")
