"""Deterministic multi-file orchestration for the obfush CLI."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Callable

import xxhash

from obfush.engine.core import EngineConfig, PolymorphicEngine
from obfush.engine.security_analyzer import analyze_source


@dataclass(frozen=True)
class BatchItemResult:
    input_path: str
    output_path: str
    status: str
    seed: int | None
    source_bytes: int
    output_bytes: int
    elapsed_ms: float
    layers_applied: list[str]
    verified: bool
    error: str | None = None
    analysis: dict | None = None
    layer_timings_ms: dict[str, float] | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def discover_scripts(input_dir: Path, recursive: bool = True) -> list[Path]:
    """Return a stable list of regular .sh files beneath input_dir."""
    if not input_dir.is_dir():
        raise ValueError(f"Batch input is not a directory: {input_dir}")
    iterator = input_dir.rglob("*.sh") if recursive else input_dir.glob("*.sh")
    scripts = [path for path in iterator if path.is_file() and not path.is_symlink()]
    return sorted(scripts, key=lambda path: path.relative_to(input_dir).as_posix())


def derive_batch_seed(base_seed: int | None, relative_path: Path, source: str) -> int | None:
    """Derive independent deterministic seeds while preserving random mode."""
    if base_seed is None:
        return None
    payload = (
        base_seed.to_bytes(8, "big", signed=False)
        + relative_path.as_posix().encode("utf-8")
        + b"\0"
        + source.encode("utf-8")
    )
    return xxhash.xxh64(payload).intdigest()


def process_batch(
    input_dir: Path,
    output_dir: Path,
    config: EngineConfig,
    *,
    dry_run: bool = False,
    workers: int = 1,
    fail_fast: bool = False,
    write_output: Callable[[str, str], None],
) -> list[BatchItemResult]:
    """Process every script independently, retaining per-file failures."""
    input_dir = input_dir.resolve()
    output_dir = output_dir.resolve()
    if output_dir == input_dir or input_dir in output_dir.parents:
        raise ValueError("Batch output directory must not be inside the input directory")

    scripts = discover_scripts(input_dir)
    if not scripts:
        raise ValueError(f"No .sh files found in batch input: {input_dir}")
    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    jobs = [
        (str(source_path), str(input_dir), str(output_dir), config)
        for source_path in scripts
    ]
    if not fail_fast and workers == 1:
        processed = [_process_one(job) for job in jobs]
    elif not fail_fast:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            processed = list(executor.map(_process_one, jobs))
    else:
        processed = _process_fail_fast(jobs, workers)

    results: list[BatchItemResult] = []
    for item, output in processed:
        if item.status == "ok" and not dry_run:
            destination = Path(item.output_path)
            try:
                destination.parent.mkdir(parents=True, exist_ok=True)
                write_output(item.output_path, output)
            except Exception as exc:
                item = replace(
                    item,
                    status="error",
                    output_bytes=0,
                    error=f"{type(exc).__name__}: {exc}",
                    analysis=None,
                )
        results.append(item)
    return results


def _process_fail_fast(
    jobs: list[tuple[str, str, str, EngineConfig]],
    workers: int,
) -> list[tuple[BatchItemResult, str]]:
    """Process ordered windows and skip every input after the first failure."""
    processed: list[tuple[BatchItemResult, str]] = []
    for offset in range(0, len(jobs), workers):
        window = jobs[offset:offset + workers]
        if workers == 1:
            window_results = [_process_one(window[0])]
        else:
            with ProcessPoolExecutor(max_workers=workers) as executor:
                window_results = list(executor.map(_process_one, window))

        failure_index = next(
            (index for index, (item, _) in enumerate(window_results) if item.status == "error"),
            None,
        )
        if failure_index is None:
            processed.extend(window_results)
            continue

        processed.extend(window_results[:failure_index + 1])
        skipped_jobs = window[failure_index + 1:] + jobs[offset + len(window):]
        processed.extend((_skipped_result(job), "") for job in skipped_jobs)
        break
    return processed


def _skipped_result(job: tuple[str, str, str, EngineConfig]) -> BatchItemResult:
    source_path = Path(job[0])
    input_dir = Path(job[1])
    output_dir = Path(job[2])
    destination = output_dir / source_path.relative_to(input_dir)
    return BatchItemResult(
        input_path=str(source_path),
        output_path=str(destination),
        status="skipped",
        seed=None,
        source_bytes=0,
        output_bytes=0,
        elapsed_ms=0.0,
        layers_applied=[],
        verified=False,
        error="Skipped after earlier batch failure",
    )


def _process_one(job: tuple[str, str, str, EngineConfig]) -> tuple[BatchItemResult, str]:
    """Worker entry point kept at module scope for ProcessPool pickling."""
    source_path = Path(job[0])
    input_dir = Path(job[1])
    output_dir = Path(job[2])
    config = job[3]
    relative = source_path.relative_to(input_dir)
    destination = output_dir / relative
    source_bytes = 0
    try:
        source = source_path.read_text(encoding="utf-8")
        source_bytes = len(source.encode("utf-8"))
        if not source.strip():
            raise ValueError("Input script is empty")
        item_seed = derive_batch_seed(config.seed, relative, source)
        item_config = replace(config, seed=item_seed, dump_ast=None)
        engine_result = PolymorphicEngine(item_config).run(source)
        analysis = analyze_source(
            engine_result.output,
            original_size=source_bytes,
            baseline_source=source,
        )
        return BatchItemResult(
            input_path=str(source_path),
            output_path=str(destination),
            status="ok",
            seed=engine_result.seed,
            source_bytes=source_bytes,
            output_bytes=len(engine_result.output.encode("utf-8")),
            elapsed_ms=round(engine_result.elapsed_ms, 3),
            layers_applied=engine_result.layers_applied,
            verified=engine_result.verified,
            analysis=analysis.to_dict(),
            layer_timings_ms={
                name: round(stats.elapsed_ms, 3)
                for name, stats in engine_result.layer_stats.items()
            },
        ), engine_result.output
    except Exception as exc:
        return BatchItemResult(
            input_path=str(source_path),
            output_path=str(destination),
            status="error",
            seed=None,
            source_bytes=source_bytes,
            output_bytes=0,
            elapsed_ms=0.0,
            layers_applied=[],
            verified=False,
            error=f"{type(exc).__name__}: {exc}",
        ), ""
