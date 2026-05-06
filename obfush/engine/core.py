"""
PolymorphicEngine — the main orchestrator.

Pipeline: parse → normalise → select layers → transform → verify → emit
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from rich.console import Console
from rich.table import Table

from obfush.engine.seed import generate_seed, create_rng, derive_layer_seed
from obfush.engine.layer_selector import LayerSelector, LayerPlan
from obfush.layers import get_layer
from obfush.layers.base import LayerConfig, LayerStats


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

        if self.config.verbose:
            self.console.print(f"[dim]Seed: {seed}[/dim]")

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
        for plan in plans:
            if self.config.verbose:
                self.console.print(f"[bold cyan]▸ Applying {plan.name}[/bold cyan] "
                                   f"(intensity={plan.intensity:.2f})")

            layer = get_layer(plan.name)
            rng = create_rng(plan.seed)

            layer_config = LayerConfig(
                intensity=plan.intensity,
                seed=plan.seed,
                rng=rng,
                eval_mode=self.config.eval_mode,
            )

            ast_before = ast.copy() if isinstance(ast, dict) else ast
            ast, stats = layer.transform(ast, layer_config)
            all_stats[plan.name] = stats

            # Structural validation
            if not layer.validate(ast_before, ast):
                self.console.print(
                    f"[bold red]✗ Layer {plan.name} failed validation![/bold red]"
                )
                ast = ast_before  # rollback

            if self.config.verbose:
                self._print_stats(plan.name, stats)

        # Step 6: Emit
        from obfush.engine.ast_emitter import emit
        output = emit(ast)

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

        if self.config.verbose:
            self._print_summary(seed, plans, elapsed, output)

        return EngineResult(
            source=source, output=output, seed=seed,
            layers_applied=[p.name for p in plans],
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
        if stats.junk_blocks_injected:
            parts.append(f"junk={stats.junk_blocks_injected}")
        if stats.custom:
            for k, v in stats.custom.items():
                parts.append(f"{k}={v}")
        if parts:
            self.console.print(f"  [dim]{', '.join(parts)}[/dim]")

    def _print_summary(
        self, seed: int, plans: list[LayerPlan], elapsed: float, output: str
    ) -> None:
        """Print final summary."""
        from obfush.utils.entropy_utils import shannon_entropy
        entropy = shannon_entropy(output.encode("utf-8"))
        self.console.print()
        self.console.print(f"[bold]═══ obfush Complete ═══[/bold]")
        self.console.print(f"  Seed:     {seed}")
        self.console.print(f"  Layers:   {len(plans)}")
        self.console.print(f"  Output:   {len(output)} bytes")
        self.console.print(f"  Entropy:  {entropy:.3f} bits/byte")
        self.console.print(f"  Time:     {elapsed:.1f} ms")
