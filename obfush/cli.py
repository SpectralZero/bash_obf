"""
obfush CLI -- Click entrypoint.

Usage:
    obfush [OPTIONS] INPUT_SCRIPT OUTPUT_SCRIPT
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import click
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from obfush import __version__
from obfush.engine.core import EngineConfig, PolymorphicEngine
from obfush.layers import ALL_LAYER_NAMES


console = Console(stderr=True)


PRESETS: dict[str, dict[str, object]] = {
    "stealth": {
        "intensity": 0.5,
        "force_layers": "id-mangle,str-shred,cmd-sub,entropy-mask",
        "min_layers": 4,
        "eval_mode": "no-eval",
    },
    "standard": {
        "intensity": 0.8,
        "force_layers": None,
        "min_layers": 4,
        "eval_mode": "ok",
    },
    "paranoid": {
        "intensity": 0.95,
        "force_layers": ",".join(ALL_LAYER_NAMES),
        "min_layers": len(ALL_LAYER_NAMES),
        "eval_mode": "no-eval",
    },
    "godmode": {
        "intensity": 1.0,
        "force_layers": ",".join(ALL_LAYER_NAMES),
        "min_layers": len(ALL_LAYER_NAMES),
        "eval_mode": "ok",
    },
}

_CONFIGURABLE_OPTIONS = (
    "seed", "preset", "intensity", "force_layers", "disable_layers",
    "min_layers", "eval_mode", "entropy_target", "max_size_ratio",
    "verify", "test_input", "workers", "fail_fast",
    "log_level", "output_mode", "environment_key", "anti_debug",
)


def _run_setup() -> None:
    """Create a validated global configuration through an interactive prompt."""
    from obfush.config import validate_config

    destination = Path.home() / ".obfushrc"
    if destination.exists() and not click.confirm(
        f"{destination} exists. Replace it?", default=False,
    ):
        raise click.Abort()
    preset = click.prompt(
        "Preset", type=click.Choice(list(PRESETS)), default="standard",
    )
    intensity = click.prompt("Intensity", type=click.FloatRange(0.0, 1.0), default=0.8)
    eval_mode = click.prompt(
        "Evaluation mode",
        type=click.Choice(["ok", "no-eval", "direct-exec"]),
        default="ok",
    )
    verify = click.confirm("Verify transformed scripts by default?", default=False)
    values = validate_config({
        "preset": preset,
        "intensity": intensity,
        "eval_mode": eval_mode,
        "verify": verify,
    })
    destination.parent.mkdir(parents=True, exist_ok=True)
    _write_output_atomic(
        str(destination), yaml.safe_dump(values, sort_keys=True, default_flow_style=False),
    )
    if os.name != "nt":
        destination.chmod(0o600)
    click.echo(f"Configuration written to {destination}")


def _apply_preset(
    ctx: click.Context,
    preset: str | None,
    values: dict[str, object],
) -> dict[str, object]:
    """Apply preset defaults without overriding explicit command-line values."""
    if preset is None:
        return values
    profile = PRESETS[preset]
    for option, value in profile.items():
        if ctx.get_parameter_source(option) is click.core.ParameterSource.DEFAULT:
            values[option] = value
    return values


def _resolve_configuration(
    ctx: click.Context,
    cli_values: dict[str, object],
    file_values: dict[str, object],
) -> dict[str, object]:
    """Merge config and presets while preserving explicit CLI options."""
    resolved = dict(cli_values)
    explicit = {
        name
        for name in _CONFIGURABLE_OPTIONS
        if ctx.get_parameter_source(name) is click.core.ParameterSource.COMMANDLINE
    }
    cli_preset_explicit = "preset" in explicit
    effective_preset = (
        resolved.get("preset") if cli_preset_explicit
        else file_values.get("preset", resolved.get("preset"))
    )

    if effective_preset and not cli_preset_explicit:
        resolved.update(PRESETS[str(effective_preset)])
    for name, value in file_values.items():
        if name not in explicit:
            resolved[name] = value
    if effective_preset and cli_preset_explicit:
        for name, value in PRESETS[str(effective_preset)].items():
            if name not in explicit:
                resolved[name] = value
    resolved["preset"] = effective_preset
    for name in explicit:
        resolved[name] = cli_values[name]
    return resolved


def _read_source(path: str) -> str:
    """Read UTF-8 source from a path or stdin when path is '-'."""
    if path == "-":
        return click.get_text_stream("stdin").read()
    with open(path, "r", encoding="utf-8") as source_file:
        return source_file.read()


def _write_output_atomic(path: str, output: str) -> None:
    """Atomically replace a filesystem output with fully flushed UTF-8 data."""
    destination = Path(path)
    parent = destination.parent.resolve()
    fd, temporary_path = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as output_file:
            output_file.write(output)
            output_file.flush()
            os.fsync(output_file.fileno())
        os.replace(temporary_path, destination)
    except BaseException:
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass
        raise


def _write_output(path: str, output: str) -> None:
    """Write output to a path atomically or directly to stdout for '-'."""
    if path == "-":
        stream = click.get_text_stream("stdout")
        stream.write(output)
        stream.flush()
        return
    _write_output_atomic(path, output)


ADVANCED_HELP = """obfush v{version} -- Advanced Usage
Author: Spectral0x00 | Red Team Internal Use Only

EVAL-MODE GUIDE
---------------
  ok           Default. Uses eval chains for max obfuscation.
               Best when target environment doesn't audit eval.
  no-eval      Zero eval tokens. Uses bash -c + printf reassembly.
               Use when eval is monitored or grep'd.
  direct-exec  Uses an isolated bash -c process for commands that do not
               mutate parent-shell state. Contains zero eval calls.

  Tradeoff:    no-eval is ~10-15% less obfuscated than ok mode but
               leaves no static eval signature. direct-exec splits
               execution into two processes (forensically obvious
               but per-process source is clean).

LAYER ORDERING (DAG, enforced)
------------------------------
  id-mangle    must run before encode, str-shred, cmd-sub
               (otherwise assignment LHSes hide in encoded blobs
               while references get renamed -> mismatch)
  flow-obfusc  must run before encode, str-shred, cmd-sub
               (dependency analysis can't see vars in encoded blobs)
  entropy-mask runs LAST. Decoys are injected BEFORE the tail
               statement so the script's exit code is preserved.

OPSEC: COMMENT STRIPPING & DECOY INJECTION
------------------------------------------
  Pre-processing pass strips ALL comments from the source before
  parsing -- deterministic regardless of which parser path the
  script takes. Shebang and quoted '#' chars are preserved.

  entropy-mask then injects misleading decoy comments from a
  procedural corpus (40 actions x 36 components x 22 contexts =
  31,680 unique strings). No two obfuscated artifacts share the
  same decoy set; clustering analysis is defeated by construction.

ENTROPY TARGETING
-----------------
  Default: 4.5 bit/byte. Real bash scripts cluster at 4.2-4.8.
  Base64-encoded blobs jump to 5.8+ which ML scanners flag.

  obfush --entropy-target 4.5 input.sh output.sh
       -> entropy-mask injects low-entropy decoys until the global
          Shannon entropy hits the target (within +/- 0.2 bit/byte).

REPRODUCIBILITY
---------------
  --seed makes output deterministic. Same seed + same source =
  byte-for-byte identical output across machines.

  Useful for:  debugging a broken layer combination,
               sharing a reproducible artifact with teammates,
               regression testing.

EQUIVALENCE CONTRACT
--------------------
  Tested on 10 fixtures x 5 seeds = 50/50 byte-for-byte equivalent
  output (raw, no normalization required after entropy-mask
  tail-preservation fix).

  CI runs the equivalence check on every push (light matrix:
  3 SHA-derived seeds) and nightly (full matrix: 5 seeds x 3
  intensities x 3 eval-modes = 45 jobs). Failure artifacts are
  retained 30 days for triage.

  Bashlex limitation: scripts that use [[ ]] heavily, complex
  parameter expansion (${var//pat/replace}), or nested heredocs
  may hit the opaque-blob fallback path. Output is still correct
  but obfuscation depth is reduced for affected regions.

SCOPE
-----
  obfush protects SOURCE CODE, not runtime behaviour. System calls
  (connect, execve, write, openat) remain fully visible to strace,
  eBPF, and EDR. Detecting those is the TEST goal -- we don't fight
  it here. If you need runtime stealth, use a compiled implant.
""".strip()


def _show_advanced_help(ctx: click.Context, param: click.Parameter, value: bool) -> None:
    """Eager callback for --help-advanced: print panel and exit before
    Click validates the required positional INPUT/OUTPUT arguments."""
    if not value or ctx.resilient_parsing:
        return
    console.print(Panel(
        ADVANCED_HELP.replace("{version}", __version__),
        title="[bold cyan]obfush Advanced[/bold cyan]",
        border_style="cyan",
    ))
    ctx.exit(0)


@click.command(
    context_settings={"help_option_names": ["-h", "--help"]},
    epilog="Red Team Internal Use Only -- Spectral0x00",
)
@click.argument("input_script", required=False, type=click.Path(allow_dash=True))
@click.argument("output_script", required=False, type=click.Path(allow_dash=True))
@click.option("--gui", is_flag=True, default=False, help="Launch the local web dashboard.")
@click.option("--gui-host", default="127.0.0.1", show_default=True, help="GUI bind host.")
@click.option("--gui-port", type=click.IntRange(1, 65535), default=5000, show_default=True)
@click.option("--no-browser", is_flag=True, default=False, help="Do not open the GUI in a browser.")
@click.option("--setup", is_flag=True, default=False, help="Create the global ~/.obfushrc file.")
@click.option(
    "--plugin", "plugin_paths", multiple=True, type=click.Path(exists=True, dir_okay=False),
    help="Load a trusted local layer plugin (repeatable).",
)
@click.option(
    "--batch", "batch_dir", type=click.Path(exists=True, file_okay=False), default=None,
    help="Process all .sh files under a directory.",
)
@click.option(
    "--workers", type=click.IntRange(min=1), default=1, show_default=True,
    help="Worker processes used by batch mode.",
)
@click.option(
    "--fail-fast", is_flag=True, default=False,
    help="Stop batch processing after the earliest failing input.",
)
@click.option(
    "--config", "config_path", type=click.Path(exists=True, dir_okay=False), default=None,
    help="Use an explicit YAML configuration file.",
)
@click.option(
    "--no-config", is_flag=True, default=False,
    help="Disable global and project .obfushrc discovery.",
)
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], case_sensitive=False),
    default="WARNING",
    show_default=True,
    help="Write structured JSON logs to stderr.",
)
@click.option(
    "--benchmark", is_flag=True, default=False,
    help="Benchmark INPUT_SCRIPT without writing an output file.",
)
@click.option(
    "--benchmark-iterations", type=click.IntRange(min=1), default=5, show_default=True,
    help="Measured iterations used by --benchmark.",
)
@click.option(
    "--seed", type=str, default=None,
    help="Deterministic seed (reproducible output).",
)
@click.option(
    "--preset", type=click.Choice(list(PRESETS)), default=None,
    help="Configuration profile; explicit options take precedence.",
)
@click.option(
    "--intensity", type=float, default=0.8,
    help="0.0-1.0 obfuscation aggressiveness (default: 0.8).",
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
    "--entropy-target", type=click.FloatRange(min=0.0, max=8.0), default=4.5,
    help="Target Shannon entropy (bit/byte). Default: 4.5.",
)
@click.option(
    "--max-size-ratio", type=click.FloatRange(min=1.0), default=3.0,
    show_default=True, help="Maximum output/input byte ratio after decoy trimming.",
)
@click.option(
    "--json-output", is_flag=True, default=False,
    help="Write machine-readable run metadata to stdout.",
)
@click.option(
    "--output-mode", type=click.Choice(["script", "binary"]), default="script",
    show_default=True, help="Write an obfuscated shell script or Linux loader binary.",
)
@click.option(
    "--env-key", "environment_key", type=str, default=None,
    help="Bind binary output to this environment key (OBFUSH_ENV_KEY may override it).",
)
@click.option(
    "--no-anti-debug", "anti_debug", is_flag=True, default=False,
    help="Disable best-effort anti-debug checks in binary output.",
)
@click.option(
    "--checksum", is_flag=True, default=False,
    help="Write a SHA-256 sidecar next to binary output for external verification.",
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
    callback=_show_advanced_help, is_eager=True, expose_value=False,
    help="Show full Spectral0x00 documentation and exit.",
)
@click.version_option(__version__, prog_name="obfush")
@click.pass_context
def main(
    ctx: click.Context,
    input_script: str | None,
    output_script: str | None,
    gui: bool,
    gui_host: str,
    gui_port: int,
    no_browser: bool,
    setup: bool,
    plugin_paths: tuple[str, ...],
    batch_dir: str | None,
    workers: int,
    fail_fast: bool,
    config_path: str | None,
    no_config: bool,
    log_level: str,
    benchmark: bool,
    benchmark_iterations: int,
    seed: str | None,
    preset: str | None,
    intensity: float,
    force_layers: str | None,
    disable_layers: str | None,
    min_layers: int,
    eval_mode: str,
    entropy_target: float,
    max_size_ratio: float,
    json_output: bool,
    output_mode: str,
    environment_key: str | None,
    anti_debug: bool,
    checksum: bool,
    verify: bool,
    test_input: str | None,
    verbose: bool,
    dry_run: bool,
    dump_ast: str | None,
) -> None:
    """obfush -- Polymorphic Bash Obfuscation Engine v2.0

    Transforms INPUT_SCRIPT into an obfuscated OUTPUT_SCRIPT.
    Every invocation produces unique output (use --seed for reproducibility).

    Pre-processing strips all source comments deterministically (shebangs
    preserved). The 11-layer pipeline then runs in a compatibility-DAG
    order; entropy-mask runs last and never appends decoys after the
    script's tail statement (preserves exit codes).

    \b
    Layers (DAG-ordered, --layers selects which to enable):
      id-mangle      Renames DEFINED vars & functions. Skips free
                     references, builtins, env-style ALL_CAPS, and
                     PATH-affecting commands.
      str-shred      Hex/octal/fragment/arithmetic-printf/base64
                     encoding of literal strings. Skips values
                     containing $-expansions or shell syntax.
      cmd-sub        echo<->printf, true<->:, source<->., test-style
                     morphing.
      junk-inject    Side-effect-contained live dependency chains.
      flow-obfusc    Independent-block reordering (data-flow aware,
                     stdout-ordering aware), opaque predicates,
                     subshell wrapping (skips local/declare/export
                     so scope-binding commands stay in parent shell).
      opaque-const   Equivalent arithmetic for safe integer contexts.
      cff            Conservative straight-line state dispatch.
      encode         Wraps commands in eval/bash-c reconstruction chains.
                     Three modes: ok, no-eval, direct-exec.
      indirection    Variable & associative-array command dispatch.
      poly-shell     Multi-process self-extracting loader
                     (only at intensity >= 0.9).
      entropy-mask   Procedural decoy injection (31,680-combo corpus).
                     Runs LAST. Tail statement is sacred -- decoys
                     never appear after it.

    \b
    Quick examples:
      obfush --seed 1337 in.sh out.sh           # Reproducible
      obfush --batch scripts/ build/ --workers 4 # Recursive batch
      obfush --config .obfushrc in.sh out.sh    # YAML configuration
      obfush -v in.sh out.sh                    # Verbose stats
      obfush --eval-mode no-eval in.sh out.sh   # Zero eval tokens
      obfush --no-layer poly-shell in.sh out.sh # Skip a layer
      obfush --layers id-mangle,encode --min-layers 2 in.sh out.sh
      obfush --help-advanced                    # Full doc panel
    """
    # --help-advanced is handled by an eager Click callback; nothing to do here.

    if setup:
        if gui or input_script is not None or output_script is not None:
            raise click.UsageError("--setup cannot be combined with another execution mode")
        _run_setup()
        return
    if gui:
        if input_script is not None or output_script is not None:
            raise click.UsageError("--gui does not accept INPUT_SCRIPT or OUTPUT_SCRIPT")
        try:
            from obfush.gui import launch
        except ImportError as exc:
            raise click.ClickException("GUI dependencies are missing; install obfush[gui]") from exc
        launch(host=gui_host, port=gui_port, open_browser=not no_browser)
        return

    if plugin_paths:
        from obfush.layers.plugins import load_plugin

        for plugin_path in plugin_paths:
            try:
                load_plugin(plugin_path)
            except Exception as exc:
                raise click.UsageError(f"Could not load plugin {plugin_path}: {exc}") from exc

    from obfush.config import ConfigError, discover_config, load_config

    if config_path and no_config:
        raise click.UsageError("--config and --no-config cannot be combined")
    try:
        config_paths = (
            [Path(config_path)] if config_path
            else ([] if no_config else discover_config())
        )
        file_config = load_config(config_paths)
    except ConfigError as exc:
        raise click.UsageError(str(exc)) from exc

    configured = _resolve_configuration(ctx, {
        "seed": seed,
        "preset": preset,
        "intensity": intensity,
        "force_layers": force_layers,
        "disable_layers": disable_layers,
        "min_layers": min_layers,
        "eval_mode": eval_mode,
        "entropy_target": entropy_target,
        "max_size_ratio": max_size_ratio,
        "verify": verify,
        "test_input": test_input,
        "workers": workers,
        "fail_fast": fail_fast,
        "log_level": log_level,
        "output_mode": output_mode,
        "environment_key": environment_key,
        "anti_debug": not anti_debug,
    }, file_config)
    seed = None if configured["seed"] is None else str(configured["seed"])
    preset = configured["preset"] if isinstance(configured["preset"], str) else None
    intensity = float(configured["intensity"])
    force_layers = configured["force_layers"]
    disable_layers = configured["disable_layers"]
    min_layers = int(configured["min_layers"])
    eval_mode = str(configured["eval_mode"])
    entropy_target = float(configured["entropy_target"])
    max_size_ratio = float(configured["max_size_ratio"])
    verify = bool(configured["verify"])
    test_input = configured["test_input"] if isinstance(configured["test_input"], str) else None
    workers = int(configured["workers"])
    fail_fast = bool(configured["fail_fast"])
    log_level = str(configured["log_level"]).upper()
    output_mode = str(configured["output_mode"])
    environment_key = (
        configured["environment_key"] if isinstance(configured["environment_key"], str)
        else None
    )
    anti_debug = bool(configured["anti_debug"])

    from obfush.logging_utils import configure_logging, get_logger
    configure_logging(log_level)
    logger = get_logger("cli")
    logger.debug(
        "configuration_resolved",
        extra={
            "event": "configuration_resolved",
            "preset": preset,
            "config_files": [str(path) for path in config_paths],
            "log_level": log_level,
        },
    )

    if batch_dir and benchmark:
        raise click.UsageError("--batch and --benchmark cannot be combined")
    if batch_dir:
        if output_script is not None or input_script is None:
            raise click.UsageError("Batch usage: obfush --batch INPUT_DIR OUTPUT_DIR")
        if input_script == "-":
            raise click.UsageError("Batch OUTPUT_DIR must be a filesystem directory, not '-'")
        batch_output = input_script
        input_script = None
    elif benchmark:
        batch_output = None
        if input_script is None or output_script is not None:
            raise click.UsageError("Benchmark usage: obfush --benchmark INPUT_SCRIPT")
        if input_script == "-":
            raise click.UsageError("Benchmark INPUT_SCRIPT must be a file, not '-'")
        if not Path(input_script).is_file():
            raise click.UsageError(f"Input script does not exist: {input_script}")
    else:
        batch_output = None
        if input_script is None or output_script is None:
            raise click.UsageError("Single-file mode requires INPUT_SCRIPT and OUTPUT_SCRIPT")
        if input_script != "-" and not Path(input_script).is_file():
            raise click.UsageError(f"Input script does not exist: {input_script}")

    if json_output and output_script == "-":
        raise click.UsageError(
            "--json-output cannot be combined with OUTPUT_SCRIPT '-' because both use stdout."
        )
    if output_mode == "binary" and output_script == "-":
        raise click.UsageError("Binary output requires a filesystem OUTPUT_SCRIPT path")
    if output_mode == "binary" and environment_key == "":
        raise click.UsageError("--env-key must not be empty")

    # Banner
    if verbose:
        console.print(Panel(
            f"[bold cyan]obfush[/bold cyan] v{__version__} -- "
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
        parsed_force = [layer.strip() for layer in force_layers.split(",")]

    parsed_disable = None
    if disable_layers:
        parsed_disable = [layer.strip() for layer in disable_layers.split(",")]

    # Validate intensity
    if not 0.0 <= intensity <= 1.0:
        console.print("[bold red]Error:[/bold red] --intensity must be 0.0-1.0")
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
        max_size_ratio=max_size_ratio,
        log_level=log_level,
    )

    if batch_dir:
        if dump_ast:
            raise click.UsageError("--dump-ast is not supported in batch mode")
        from obfush.batch import process_batch

        try:
            batch_results = process_batch(
                Path(batch_dir),
                Path(batch_output),
                config,
                dry_run=dry_run,
                workers=workers,
                fail_fast=fail_fast,
                write_output=_write_output_atomic,
            )
        except Exception as exc:
            raise click.ClickException(str(exc)) from exc
        succeeded = sum(item.status == "ok" for item in batch_results)
        failed = sum(item.status == "error" for item in batch_results)
        skipped = sum(item.status == "skipped" for item in batch_results)
        if json_output:
            click.echo(json.dumps({
                "mode": "batch",
                "input_dir": str(Path(batch_dir).resolve()),
                "output_dir": str(Path(batch_output).resolve()),
                "preset": preset,
                "workers": workers,
                "fail_fast": fail_fast,
                "dry_run": dry_run,
                "succeeded": succeeded,
                "failed": failed,
                "skipped": skipped,
                "files": [item.to_dict() for item in batch_results],
            }, sort_keys=True))
        else:
            for item in batch_results:
                style = "green" if item.status == "ok" else "red"
                detail = item.output_path if item.status == "ok" else item.error
                console.print(f"[{style}]{item.status.upper()}[/{style}] {item.input_path}: {detail}")
            console.print(
                f"Batch complete: {succeeded} succeeded, {failed} failed, {skipped} skipped"
            )
        if failed:
            ctx.exit(1)
        return

    if benchmark:
        from obfush.benchmark import benchmark_engine

        try:
            source = _read_source(input_script)
            if not source.strip():
                raise ValueError("Input script is empty")
            benchmark_result = benchmark_engine(
                source,
                config,
                iterations=benchmark_iterations,
                warmup_iterations=1,
            )
        except Exception as exc:
            raise click.ClickException(str(exc)) from exc
        if json_output:
            click.echo(json.dumps({
                "mode": "benchmark",
                **benchmark_result.to_dict(),
            }, sort_keys=True))
        else:
            table = Table(title="obfush Engine Benchmark")
            table.add_column("Scope", style="bold cyan")
            table.add_column("Min ms", justify="right")
            table.add_column("p50 ms", justify="right")
            table.add_column("p95 ms", justify="right")
            table.add_column("Max ms", justify="right")
            rows = [("total", benchmark_result.total), *benchmark_result.layers.items()]
            for name, timing in rows:
                table.add_row(
                    name,
                    f"{timing.minimum_ms:.3f}",
                    f"{timing.p50_ms:.3f}",
                    f"{timing.p95_ms:.3f}",
                    f"{timing.maximum_ms:.3f}",
                )
            console.print(table)
            console.print(
                f"iterations={benchmark_result.iterations}, seed={benchmark_result.seed}, "
                f"deterministic={benchmark_result.deterministic_output}"
            )
        return

    # Read single-file input only after batch mode has returned.
    try:
        source = _read_source(input_script)
    except Exception as e:
        console.print(f"[bold red]Error reading input:[/bold red] {e}")
        raise SystemExit(1)

    if not source.strip():
        console.print("[bold red]Error:[/bold red] Input script is empty")
        raise SystemExit(1)

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

    # Build the optional native loader only after the script payload has passed
    # through the normal engine pipeline. The compiler package is lazy-loaded so
    # script mode keeps its existing platform requirements.
    binary_result = None
    if output_mode == "binary" and not dry_run:
        try:
            from obfush.compiler import build_binary

            binary_result = build_binary(
                result.output,
                output_script,
                seed=result.seed,
                anti_debug=anti_debug,
                environment_key=environment_key,
            )
        except Exception as exc:
            console.print(f"[bold red]Binary build error:[/bold red] {exc}")
            raise SystemExit(1) from exc
        if checksum:
            checksum_path = Path(f"{output_script}.sha256")
            _write_output_atomic(
                str(checksum_path),
                f"{binary_result.sha256}  {Path(output_script).name}\n",
            )

    # Write output
    if not dry_run:
        if output_mode == "script":
            try:
                _write_output(output_script, result.output)
            except Exception as e:
                console.print(f"[bold red]Error writing output:[/bold red] {e}")
                raise SystemExit(1) from e
        if verbose:
            console.print(
                f"\n[bold green][OK] Written to {output_script}[/bold green]"
            )
        elif not json_output:
            output_bytes = binary_result.output_bytes if binary_result else len(result.output)
            console.print(
                f"[green][OK][/green] {output_script} "
                f"({output_bytes} bytes, seed={result.seed}, "
                f"layers={len(result.layers_applied)}, {result.elapsed_ms:.0f}ms)"
            )
    else:
        if not json_output:
            console.print("[yellow]Dry run -- no file written[/yellow]")
            console.print(f"  Seed: {result.seed}")
            console.print(f"  Layers: {', '.join(result.layers_applied)}")

    if json_output:
        from obfush.engine.security_analyzer import analyze_source

        source_bytes = len(source.encode("utf-8"))
        output_bytes = len(result.output.encode("utf-8"))
        analysis = analyze_source(
            result.output,
            original_size=source_bytes,
            baseline_source=source,
        )
        click.echo(json.dumps({
            "seed": result.seed,
            "preset": preset,
            "layers_applied": result.layers_applied,
            "output_path": None if dry_run else output_script,
            "output_mode": output_mode,
            "source_bytes": source_bytes,
            "output_bytes": binary_result.output_bytes if binary_result else output_bytes,
            "size_ratio": (binary_result.output_bytes if binary_result else output_bytes) / source_bytes,
            "elapsed_ms": round(result.elapsed_ms, 3),
            "verified": result.verified,
            "dry_run": dry_run,
            "analysis": analysis.to_dict(),
            "layer_timings_ms": {
                name: round(stats.elapsed_ms, 3)
                for name, stats in getattr(result, "layer_stats", {}).items()
            },
            "layer_rollbacks": {
                name: stats.custom.get("rolled_back")
                for name, stats in getattr(result, "layer_stats", {}).items()
                if stats.custom.get("rolled_back")
            },
            "binary": binary_result.to_dict() if binary_result else None,
            "checksum_path": (
                f"{output_script}.sha256" if binary_result and checksum else None
            ),
        }, sort_keys=True))

    # Entropy report
    if verbose and not dry_run:
        from obfush.engine.entropy_evaluator import EntropyEvaluator
        evaluator = EntropyEvaluator(target=entropy_target)
        report = evaluator.report(result.output.encode("utf-8"))
        console.print()
        console.print(Panel(report, title="Entropy Analysis", border_style="yellow"))


if __name__ == "__main__":
    main()
