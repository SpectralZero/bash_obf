"""CLI filesystem and stream behavior tests."""

import os
import json

import pytest
from click.testing import CliRunner

from obfush.cli import _write_output_atomic, main


def test_stdin_to_stdout_pipeline():
    runner = CliRunner()

    result = runner.invoke(
        main,
        ["-", "-", "--seed", "42", "--layers", "id-mangle", "--min-layers", "1"],
        input="echo hello\n",
    )

    assert result.exit_code == 0
    assert result.stdout.strip()
    assert "echo" in result.stdout


def test_max_size_ratio_rejects_values_below_one():
    runner = CliRunner()

    result = runner.invoke(main, ["-", "-", "--max-size-ratio", "0.5"], input="echo hi\n")

    assert result.exit_code != 0
    assert "0.5 is not in the range" in result.output


def test_stealth_preset_applies_profile(tmp_path):
    runner = CliRunner()
    destination = tmp_path / "output.sh"

    result = runner.invoke(
        main,
        ["-", str(destination), "--preset", "stealth", "--seed", "42", "--json-output"],
        input="echo hello\n",
    )

    assert result.exit_code == 0, result.output
    metadata = json.loads(result.stdout)
    assert metadata["preset"] == "stealth"
    assert set(metadata["layers_applied"]).issubset({
        "id-mangle", "str-shred", "cmd-sub", "entropy-mask",
    })
    assert destination.exists()


def test_explicit_options_override_preset(monkeypatch, tmp_path):
    captured = {}

    class Result:
        output = "echo hello\n"
        seed = 42
        layers_applied = ["id-mangle"]
        elapsed_ms = 1.25
        verified = False
        layer_stats = {}

    class Engine:
        def __init__(self, config):
            captured["config"] = config

        def run(self, source):
            return Result()

    monkeypatch.setattr("obfush.cli.PolymorphicEngine", Engine)
    runner = CliRunner()
    destination = tmp_path / "output.sh"

    result = runner.invoke(main, [
        "-", str(destination), "--preset", "godmode",
        "--intensity", "0.25", "--layers", "id-mangle",
        "--min-layers", "1", "--eval-mode", "no-eval", "--json-output",
    ], input="echo hello\n")

    assert result.exit_code == 0, result.output
    config = captured["config"]
    assert config.intensity == 0.25
    assert config.force_layers == ["id-mangle"]
    assert config.min_layers == 1
    assert config.eval_mode == "no-eval"


def test_json_output_is_valid_and_script_goes_to_file(tmp_path):
    runner = CliRunner()
    destination = tmp_path / "output.sh"

    result = runner.invoke(
        main,
        ["-", str(destination), "--seed", "42", "--json-output", "--eval-mode", "no-eval"],
        input="echo hello\n",
    )

    assert result.exit_code == 0, result.output
    metadata = json.loads(result.stdout)
    assert metadata["seed"] == 42
    assert metadata["output_path"] == str(destination)
    assert metadata["output_bytes"] == len(destination.read_bytes())
    assert metadata["analysis"]["source_bytes"] == metadata["output_bytes"]
    assert metadata["analysis"]["legacy_fingerprint_count"] == 0
    assert metadata["analysis"]["introduced_eval_count"] == 0
    assert set(metadata["layers_applied"]).issubset(metadata["layer_timings_ms"])
    assert set(metadata["layer_rollbacks"]).isdisjoint(metadata["layers_applied"])
    assert destination.read_text(encoding="utf-8").strip()


def test_json_output_rejects_stdout_script_collision():
    runner = CliRunner()

    result = runner.invoke(main, ["-", "-", "--json-output"], input="echo hello\n")

    assert result.exit_code == 2
    assert "cannot be combined" in result.output


def test_atomic_write_replaces_existing_file(tmp_path):
    destination = tmp_path / "output.sh"
    destination.write_text("old", encoding="utf-8")

    _write_output_atomic(str(destination), "new\n")

    assert destination.read_text(encoding="utf-8") == "new\n"
    assert not list(tmp_path.glob(".output.sh.*.tmp"))


def test_atomic_write_failure_preserves_existing_file(tmp_path, monkeypatch):
    destination = tmp_path / "output.sh"
    destination.write_text("old", encoding="utf-8")

    def reject_replace(source, target):
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", reject_replace)

    with pytest.raises(OSError, match="replace failed"):
        _write_output_atomic(str(destination), "new\n")

    assert destination.read_text(encoding="utf-8") == "old"
    assert not list(tmp_path.glob(".output.sh.*.tmp"))
