"""Repeatable engine-only benchmark collection."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, replace

from obfush.engine.core import EngineConfig, PolymorphicEngine
from obfush.engine.seed import generate_seed


@dataclass(frozen=True)
class TimingSummary:
    minimum_ms: float
    p50_ms: float
    p95_ms: float
    maximum_ms: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class BenchmarkResult:
    seed: int
    iterations: int
    warmup_iterations: int
    source_bytes: int
    output_bytes: int
    deterministic_output: bool
    output_sha256: str
    total: TimingSummary
    layers: dict[str, TimingSummary]

    def to_dict(self) -> dict:
        result = asdict(self)
        result["total"] = self.total.to_dict()
        result["layers"] = {
            name: summary.to_dict() for name, summary in self.layers.items()
        }
        return result


def percentile(values: list[float], quantile: float) -> float:
    """Return a linearly interpolated percentile from a non-empty sample."""
    if not values:
        raise ValueError("Cannot calculate percentile of an empty sample")
    if not 0.0 <= quantile <= 1.0:
        raise ValueError("quantile must be 0.0-1.0")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def summarize(values: list[float]) -> TimingSummary:
    """Summarize a timing sample with stable p50 and p95 calculations."""
    return TimingSummary(
        minimum_ms=round(min(values), 3),
        p50_ms=round(percentile(values, 0.50), 3),
        p95_ms=round(percentile(values, 0.95), 3),
        maximum_ms=round(max(values), 3),
    )


def benchmark_engine(
    source: str,
    config: EngineConfig,
    *,
    iterations: int = 5,
    warmup_iterations: int = 1,
) -> BenchmarkResult:
    """Benchmark deterministic engine runs, excluding verification and file I/O."""
    if iterations < 1:
        raise ValueError("iterations must be at least 1")
    if warmup_iterations < 0:
        raise ValueError("warmup_iterations must be non-negative")

    seed = config.seed if config.seed is not None else generate_seed(source)
    benchmark_config = replace(
        config,
        seed=seed,
        verify=False,
        verbose=False,
        dry_run=False,
        dump_ast=None,
    )
    for _ in range(warmup_iterations):
        PolymorphicEngine(benchmark_config).run(source)

    results = [
        PolymorphicEngine(benchmark_config).run(source)
        for _ in range(iterations)
    ]
    outputs = [result.output.encode("utf-8") for result in results]
    layer_samples: dict[str, list[float]] = {}
    for result in results:
        for name, stats in result.layer_stats.items():
            layer_samples.setdefault(name, []).append(stats.elapsed_ms)

    return BenchmarkResult(
        seed=seed,
        iterations=iterations,
        warmup_iterations=warmup_iterations,
        source_bytes=len(source.encode("utf-8")),
        output_bytes=len(outputs[0]),
        deterministic_output=all(output == outputs[0] for output in outputs[1:]),
        output_sha256=hashlib.sha256(outputs[0]).hexdigest(),
        total=summarize([result.elapsed_ms for result in results]),
        layers={name: summarize(values) for name, values in layer_samples.items()},
    )
