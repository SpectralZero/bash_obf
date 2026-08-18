"""Batch discovery, deterministic processing, and real Bash tests."""

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from obfush.batch import derive_batch_seed, discover_scripts, process_batch
from obfush.cli import _write_output_atomic, main
from obfush.engine.core import EngineConfig


def _write_scripts(root: Path) -> list[Path]:
    nested = root / "nested"
    nested.mkdir(parents=True)
    first = root / "first.sh"
    second = nested / "second.sh"
    first.write_text("#!/bin/bash\nprintf 'first\\n'\n", encoding="utf-8")
    second.write_text("#!/bin/bash\nvalue=second\nprintf '%s\\n' \"$value\"\n", encoding="utf-8")
    (root / "ignore.txt").write_text("not shell", encoding="utf-8")
    return [first, second]


def _run_script(path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash"],
        input=path.read_text(encoding="utf-8").encode("utf-8"),
        capture_output=True,
        timeout=10,
    )


def test_discover_scripts_is_recursive_stable_and_ignores_non_shell(tmp_path):
    scripts = _write_scripts(tmp_path)
    assert discover_scripts(tmp_path) == scripts
    assert discover_scripts(tmp_path, recursive=False) == [scripts[0]]


def test_batch_seed_is_path_and_content_specific():
    first = derive_batch_seed(42, Path("a.sh"), "echo one\n")
    assert first == derive_batch_seed(42, Path("a.sh"), "echo one\n")
    assert first != derive_batch_seed(42, Path("b.sh"), "echo one\n")
    assert first != derive_batch_seed(42, Path("a.sh"), "echo two\n")
    assert derive_batch_seed(None, Path("a.sh"), "echo one\n") is None


@pytest.mark.parametrize("workers", [1, 2])
def test_process_batch_preserves_paths_is_deterministic_and_executes(tmp_path, workers):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / f"output-{workers}"
    originals = _write_scripts(input_dir)
    config = EngineConfig(
        seed=42,
        intensity=0.5,
        force_layers=["id-mangle", "str-shred"],
        min_layers=1,
        eval_mode="no-eval",
    )

    first_results = process_batch(
        input_dir, output_dir, config, workers=workers, write_output=_write_output_atomic,
    )
    first_bytes = {
        path.relative_to(output_dir): path.read_bytes()
        for path in output_dir.rglob("*.sh")
    }
    second_results = process_batch(
        input_dir, output_dir, config, workers=workers, write_output=_write_output_atomic,
    )

    assert [item.status for item in first_results] == ["ok", "ok"]
    assert [item.seed for item in first_results] == [item.seed for item in second_results]
    assert first_bytes == {
        path.relative_to(output_dir): path.read_bytes()
        for path in output_dir.rglob("*.sh")
    }
    for original in originals:
        generated = output_dir / original.relative_to(input_dir)
        assert generated.exists()
        expected = _run_script(original)
        actual = _run_script(generated)
        assert (actual.returncode, actual.stdout, actual.stderr) == (
            expected.returncode, expected.stdout, expected.stderr,
        )


def test_batch_dry_run_creates_no_output_directory(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    _write_scripts(input_dir)
    results = process_batch(
        input_dir,
        output_dir,
        EngineConfig(seed=42, force_layers=["id-mangle"], min_layers=1),
        dry_run=True,
        write_output=_write_output_atomic,
    )
    assert all(item.status == "ok" for item in results)
    assert not output_dir.exists()


def test_batch_rejects_output_inside_input_and_empty_input(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    config = EngineConfig(seed=42)
    with pytest.raises(ValueError, match="inside the input"):
        process_batch(
            input_dir, input_dir / "out", config, write_output=_write_output_atomic,
        )
    with pytest.raises(ValueError, match="No .sh files"):
        process_batch(
            input_dir, tmp_path / "output", config, write_output=_write_output_atomic,
        )


def test_batch_reports_partial_failure_without_writing_failed_file(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    (input_dir / "good.sh").write_text("echo good\n", encoding="utf-8")
    (input_dir / "empty.sh").write_text("\n", encoding="utf-8")
    results = process_batch(
        input_dir,
        output_dir,
        EngineConfig(seed=42, force_layers=["id-mangle"], min_layers=1),
        write_output=_write_output_atomic,
    )
    by_name = {Path(item.input_path).name: item for item in results}
    assert by_name["good.sh"].status == "ok"
    assert by_name["empty.sh"].status == "error"
    assert "empty" in by_name["empty.sh"].error.lower()
    assert (output_dir / "good.sh").exists()
    assert not (output_dir / "empty.sh").exists()


@pytest.mark.parametrize("workers", [1, 2])
def test_batch_fail_fast_retains_prefix_and_skips_suffix(tmp_path, workers):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / f"output-{workers}"
    input_dir.mkdir()
    (input_dir / "a-good.sh").write_text("echo a\n", encoding="utf-8")
    (input_dir / "b-empty.sh").write_text("\n", encoding="utf-8")
    (input_dir / "c-good.sh").write_text("echo c\n", encoding="utf-8")
    (input_dir / "d-good.sh").write_text("echo d\n", encoding="utf-8")
    results = process_batch(
        input_dir,
        output_dir,
        EngineConfig(seed=42, force_layers=["id-mangle"], min_layers=1),
        workers=workers,
        fail_fast=True,
        write_output=_write_output_atomic,
    )
    assert [item.status for item in results] == ["ok", "error", "skipped", "skipped"]
    assert (output_dir / "a-good.sh").exists()
    assert not (output_dir / "b-empty.sh").exists()
    assert not (output_dir / "c-good.sh").exists()
    assert not (output_dir / "d-good.sh").exists()
    assert all(
        item.error == "Skipped after earlier batch failure"
        for item in results[2:]
    )


def test_cli_batch_json_contract_and_failure_exit(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    (input_dir / "good.sh").write_text("echo good\n", encoding="utf-8")
    (input_dir / "empty.sh").write_text("\n", encoding="utf-8")

    result = CliRunner().invoke(main, [
        "--batch", str(input_dir), str(output_dir),
        "--no-config", "--seed", "42", "--workers", "1",
        "--layers", "id-mangle", "--min-layers", "1", "--json-output",
    ])

    assert result.exit_code == 1, result.output
    metadata = json.loads(result.stdout)
    assert metadata["mode"] == "batch"
    assert metadata["succeeded"] == 1
    assert metadata["failed"] == 1
    assert len(metadata["files"]) == 2
    successful = next(item for item in metadata["files"] if item["status"] == "ok")
    assert successful["layer_timings_ms"] == {
        "id-mangle": pytest.approx(successful["layer_timings_ms"]["id-mangle"]),
    }


def test_cli_batch_json_reports_fail_fast_skips(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    (input_dir / "a-empty.sh").write_text("\n", encoding="utf-8")
    (input_dir / "b-good.sh").write_text("echo b\n", encoding="utf-8")
    result = CliRunner().invoke(main, [
        "--batch", str(input_dir), str(output_dir), "--no-config",
        "--seed", "42", "--fail-fast", "--json-output",
    ])
    assert result.exit_code == 1
    metadata = json.loads(result.stdout)
    assert metadata["fail_fast"]
    assert metadata["failed"] == 1
    assert metadata["skipped"] == 1
    assert [item["status"] for item in metadata["files"]] == ["error", "skipped"]


def test_cli_batch_usage_requires_one_output_positional(tmp_path):
    input_dir = tmp_path / "input"
    _write_scripts(input_dir)
    runner = CliRunner()
    missing = runner.invoke(main, ["--batch", str(input_dir), "--no-config"])
    extra = runner.invoke(main, [
        "--batch", str(input_dir), "one", "two", "--no-config",
    ])
    stdout_output = runner.invoke(main, [
        "--batch", str(input_dir), "-", "--no-config",
    ])
    assert missing.exit_code == 2
    assert "Batch usage" in missing.output
    assert extra.exit_code == 2
    assert "Batch usage" in extra.output
    assert stdout_output.exit_code == 2
    assert "filesystem directory" in stdout_output.output
