"""Benchmark statistics, determinism, and CLI tests."""

import json

import pytest
from click.testing import CliRunner

from obfush.benchmark import benchmark_engine, percentile, summarize
from obfush.cli import main
from obfush.engine.core import EngineConfig


def test_percentile_interpolates_and_validates():
    assert percentile([1.0], 0.95) == 1.0
    assert percentile([1.0, 2.0, 3.0, 4.0, 5.0], 0.50) == 3.0
    assert percentile([1.0, 2.0, 3.0, 4.0, 5.0], 0.95) == pytest.approx(4.8)
    with pytest.raises(ValueError, match="empty"):
        percentile([], 0.5)
    with pytest.raises(ValueError, match="quantile"):
        percentile([1.0], 1.1)


def test_summarize_reports_distribution():
    summary = summarize([5.0, 1.0, 4.0, 2.0, 3.0])
    assert summary.minimum_ms == 1.0
    assert summary.p50_ms == 3.0
    assert summary.p95_ms == 4.8
    assert summary.maximum_ms == 5.0


def test_benchmark_engine_is_deterministic_and_collects_layer_timings():
    source = "#!/bin/bash\nvalue=hello\nprintf '%s\\n' \"$value\"\n"
    result = benchmark_engine(
        source,
        EngineConfig(
            seed=42,
            intensity=0.5,
            force_layers=["id-mangle", "str-shred"],
            min_layers=1,
            verify=True,
        ),
        iterations=3,
        warmup_iterations=1,
    )
    assert result.seed == 42
    assert result.iterations == 3
    assert result.warmup_iterations == 1
    assert result.deterministic_output
    assert len(result.output_sha256) == 64
    assert result.source_bytes == len(source.encode("utf-8"))
    assert result.output_bytes > 0
    assert set(result.layers) == {"id-mangle", "str-shred"}
    assert all(summary.minimum_ms >= 0 for summary in result.layers.values())


@pytest.mark.parametrize(("iterations", "warmup"), [(0, 1), (1, -1)])
def test_benchmark_engine_validates_run_counts(iterations, warmup):
    with pytest.raises(ValueError):
        benchmark_engine(
            "echo hello\n",
            EngineConfig(seed=42),
            iterations=iterations,
            warmup_iterations=warmup,
        )


def test_cli_benchmark_json_writes_no_output_file(tmp_path):
    source = tmp_path / "input.sh"
    source.write_text("echo hello\n", encoding="utf-8")
    result = CliRunner().invoke(main, [
        "--benchmark", str(source), "--no-config", "--seed", "42",
        "--layers", "id-mangle", "--min-layers", "1",
        "--benchmark-iterations", "3", "--json-output",
    ])
    assert result.exit_code == 0, result.stderr
    metadata = json.loads(result.stdout)
    assert metadata["mode"] == "benchmark"
    assert metadata["iterations"] == 3
    assert metadata["warmup_iterations"] == 1
    assert metadata["deterministic_output"]
    assert "id-mangle" in metadata["layers"]
    assert list(tmp_path.iterdir()) == [source]


def test_cli_benchmark_human_table_is_on_stderr(tmp_path):
    source = tmp_path / "input.sh"
    source.write_text("echo hello\n", encoding="utf-8")
    result = CliRunner(mix_stderr=False).invoke(main, [
        "--benchmark", str(source), "--no-config", "--seed", "42",
        "--layers", "id-mangle", "--min-layers", "1",
        "--benchmark-iterations", "1",
    ])
    assert result.exit_code == 0
    assert result.stdout == ""
    assert "obfush Engine Benchmark" in result.stderr
    assert "p50 ms" in result.stderr


@pytest.mark.parametrize("args", [
    ["--benchmark"],
    ["--benchmark", "-"],
    ["--benchmark", "input.sh", "output.sh"],
])
def test_cli_benchmark_rejects_invalid_usage(tmp_path, args):
    (tmp_path / "input.sh").write_text("echo hello\n", encoding="utf-8")
    normalized = [str(tmp_path / value) if value.endswith(".sh") else value for value in args]
    result = CliRunner().invoke(main, [*normalized, "--no-config"])
    assert result.exit_code == 2


def test_cli_rejects_batch_benchmark_combination(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "input.sh").write_text("echo hello\n", encoding="utf-8")
    result = CliRunner().invoke(main, [
        "--batch", str(input_dir), "--benchmark", str(tmp_path / "output"), "--no-config",
    ])
    assert result.exit_code == 2
    assert "cannot be combined" in result.output
