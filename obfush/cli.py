"""
obfush CLI — Click entrypoint.

Usage:
    obfush [OPTIONS] INPUT_SCRIPT OUTPUT_SCRIPT
"""

from __future__ import annotations

import sys

import click
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from obfush import __version__
from obfush.engine.core import EngineConfig, PolymorphicEngine


console = Console(stderr=True)


ADVANCED_HELP = """
╔══════════════════════════════════════════════════════════════╗
║  obfush v{version} — Advanced Usage                          ║
║  Author: Spectral0x00                                        ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  DETECTION RESILIENCE GUIDE                                  ║
║  ─────────────────────────                                   ║
║  By default, high intensity uses eval. For environments      ║
║  where eval is monitored, use --eval-mode no-eval.           ║
║  This avoids all eval calls and relies on function pointer   ║
║  indirection. It is slightly less obfuscated but produces    ║
║  zero eval-based alerts.                                     ║
║                                                              ║
║  For entropy-sensitive targets, enable entropy-mask layer    ║
║  and set --entropy-target to a realistic value (e.g., 4.5). ║
║  This dilutes high-entropy encoded blobs with decoy code.   ║
║                                                              ║
║  NOTE: This tool protects source code, not runtime behaviour.║
║  System calls (connect, execve, write) remain visible to     ║
║  strace, eBPF, and EDR. Detecting those is the TEST goal.   ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
""".strip()


@click.command(
    context_settings={"help_option_names": ["-h", "--help"]},
    epilog="Red Team Internal Use Only — Spectral0x00",
)
@click.argument("input_script", type=click.Path(exists=True))
@click.argument("output_script", type=click.Path())
@click.option(
    "--seed", type=str, default=None,
    help="Deterministic seed (reproducible output).",
)
@click.option(
    "--intensity", type=float, default=0.8,
    help="0.0–1.0 obfuscation aggressiveness (default: 0.8).",
)
@click.option(
    "--layers", "force_layers", type=str, default=None,
    help="Comma-separated layers to force (overrides auto-select).",
)
@click.option(
    "--no-layer", "disable_layers", type=str, default=None,
    help="Comma-separated layers to disable.",
)
@click.option(
    "--min-layers", type=int, default=4,
    help="Minimum active layers (default: 4).",
)
@click.option(
    "--eval-mode",
    type=click.Choice(["ok", "no-eval", "direct-exec"]),
    default="ok",
    help="How to handle code evaluation (default: ok).",
)
@click.option(
    "--entropy-target", type=float, default=4.5,
    help="Target Shannon entropy (bit/byte). Default: 4.5.",
)
@click.option(
    "--verify", is_flag=True, default=False,
    help="Run equivalence check in sandbox after emit.",
)
@click.option(
    "--test-input", type=click.Path(exists=True), default=None,
    help="Stdin to feed both scripts during verify.",
)
@click.option(
    "--verbose", "-v", is_flag=True, default=False,
    help="Show per-layer statistics.",
)
@click.option(
    "--dry-run", is_flag=True, default=False,
    help="Print what would be done; don't write file.",
)
@click.option(
    "--dump-ast", type=click.Path(), default=None,
    help="Dump parsed AST to file (debug).",
)
@click.option(
    "--help-advanced", is_flag=True, default=False,
    help="Full Spectral0x00 documentation.",
)
@click.version_option(__version__, prog_name="obfush")
def main(
    input_script: str,
    output_script: str,
    seed: str | None,
    intensity: float,
    force_layers: str | None,
    disable_layers: str | None,
    min_layers: int,
    eval_mode: str,
    entropy_target: float,
    verify: bool,
    test_input: str | None,
    verbose: bool,
    dry_run: bool,
    dump_ast: str | None,
    help_advanced: bool,
) -> None:
    """obfush — Polymorphic Bash Obfuscation Engine v2.0

    Transforms INPUT_SCRIPT into an obfuscated OUTPUT_SCRIPT.
    Every invocation produces unique output.

    \b
    Layers:
      id-mangle      Variable & function name randomisation
      str-shred      String literal fragmentation
      cmd-sub        Syntax & command substitution
      junk-inject    Dead code & timing jitter
      flow-obfusc    Control flow restructuring
      encode         Encoding (base64, xor, hex)
      indirection    Indirect dispatch & pointer chains
      poly-shell     Multi-process self-extracting architecture
      entropy-mask   Statistical decoy injection
    """
    # Handle --help-advanced
    if help_advanced:
        console.print(Panel(
            ADVANCED_HELP.format(version=__version__),
            title="[bold cyan]obfush Advanced[/bold cyan]",
            border_style="cyan",
        ))
        raise SystemExit(0)

    # Banner
    if verbose:
        console.print(Panel(
            f"[bold cyan]obfush[/bold cyan] v{__version__} — "
            f"Polymorphic Bash Obfuscation Engine\n"
            f"[dim]Author: Spectral0x00 | Red Team Internal[/dim]",
            border_style="cyan",
        ))

    # Parse seed
    parsed_seed = None
    if seed is not None:
        try:
            parsed_seed = int(seed)
        except ValueError:
            # Hash the string seed
            import xxhash
            parsed_seed = xxhash.xxh64(seed.encode()).intdigest()

    # Parse layer lists
    parsed_force = None
    if force_layers:
        parsed_force = [l.strip() for l in force_layers.split(",")]

    parsed_disable = None
    if disable_layers:
        parsed_disable = [l.strip() for l in disable_layers.split(",")]

    # Validate intensity
    if not 0.0 <= intensity <= 1.0:
        console.print("[bold red]Error:[/bold red] --intensity must be 0.0–1.0")
        raise SystemExit(1)

    # Read input
    try:
        with open(input_script, "r", encoding="utf-8") as f:
            source = f.read()
    except Exception as e:
        console.print(f"[bold red]Error reading input:[/bold red] {e}")
        raise SystemExit(1)

    if not source.strip():
        console.print("[bold red]Error:[/bold red] Input script is empty")
        raise SystemExit(1)

    # Configure engine
    config = EngineConfig(
        seed=parsed_seed,
        intensity=intensity,
        force_layers=parsed_force,
        disable_layers=parsed_disable,
        min_layers=min_layers,
        eval_mode=eval_mode,
        entropy_target=entropy_target,
        verify=verify,
        test_input=test_input,
        verbose=verbose,
        dry_run=dry_run,
        dump_ast=dump_ast,
    )

    # Run engine
    engine = PolymorphicEngine(config)

    try:
        result = engine.run(source)
    except Exception as e:
        console.print(f"[bold red]Engine error:[/bold red] {e}")
        if verbose:
            import traceback
            console.print(traceback.format_exc())
        raise SystemExit(1)

    # Write output
    if not dry_run:
        try:
            with open(output_script, "w", encoding="utf-8") as f:
                f.write(result.output)
            if verbose:
                console.print(
                    f"\n[bold green]✓ Written to {output_script}[/bold green]"
                )
            else:
                console.print(
                    f"[green]✓[/green] {output_script} "
                    f"({len(result.output)} bytes, "
                    f"seed={result.seed}, "
                    f"layers={len(result.layers_applied)}, "
                    f"{result.elapsed_ms:.0f}ms)"
                )
        except Exception as e:
            console.print(f"[bold red]Error writing output:[/bold red] {e}")
            raise SystemExit(1)
    else:
        console.print("[yellow]Dry run — no file written[/yellow]")
        console.print(f"  Seed: {result.seed}")
        console.print(f"  Layers: {', '.join(result.layers_applied)}")

    # Entropy report
    if verbose and not dry_run:
        from obfush.engine.entropy_evaluator import EntropyEvaluator
        evaluator = EntropyEvaluator(target=entropy_target)
        report = evaluator.report(result.output.encode("utf-8"))
        console.print()
        console.print(Panel(report, title="Entropy Analysis", border_style="yellow"))


if __name__ == "__main__":
    main()
