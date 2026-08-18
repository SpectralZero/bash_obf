"""YAML configuration discovery, validation, and precedence tests."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from obfush.cli import main
from obfush.config import ConfigError, discover_config, load_config


def test_discover_config_returns_global_then_nearest_project(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "project"
    nested = project / "src" / "tools"
    home.mkdir()
    nested.mkdir(parents=True)
    global_config = home / ".obfushrc"
    project_config = project / ".obfushrc"
    global_config.write_text("intensity: 0.4\n", encoding="utf-8")
    project_config.write_text("intensity: 0.7\n", encoding="utf-8")

    assert discover_config(nested, home) == [global_config, project_config]


def test_load_config_merges_normalizes_aliases_and_project_precedence(tmp_path):
    global_config = tmp_path / "global.yml"
    project_config = tmp_path / "project.yml"
    global_config.write_text(
        "preset: stealth\nintensity: 0.4\nlayers: [id-mangle, encode]\nworkers: 2\nfail_fast: true\n",
        encoding="utf-8",
    )
    project_config.write_text(
        "intensity: 0.7\nno-layer: poly-shell\neval-mode: no-eval\n",
        encoding="utf-8",
    )

    loaded = load_config([global_config, project_config])

    assert loaded == {
        "preset": "stealth",
        "intensity": 0.7,
        "force_layers": "id-mangle,encode",
        "workers": 2,
        "fail_fast": True,
        "disable_layers": "poly-shell",
        "eval_mode": "no-eval",
    }


@pytest.mark.parametrize("content", [
    "- not-a-mapping\n",
    "unknown_option: true\n",
    "intensity: 2\n",
    "entropy_target: nine\n",
    "max_size_ratio: 0.5\n",
    "workers: 0\n",
    "verify: yes-please\n",
    "fail_fast: yes-please\n",
    "layers: [id-mangle, missing]\n",
])
def test_invalid_configuration_is_rejected(tmp_path, content):
    config = tmp_path / "config.yml"
    config.write_text(content, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config([config])


def test_oversized_configuration_is_rejected(tmp_path):
    config = tmp_path / "config.yml"
    config.write_text("#" * 1_048_577, encoding="utf-8")
    with pytest.raises(ConfigError, match="too large"):
        load_config([config])


def test_config_test_input_resolves_relative_to_config_file(tmp_path):
    payload = tmp_path / "stdin.txt"
    payload.write_text("payload", encoding="utf-8")
    config = tmp_path / "config.yml"
    config.write_text("test_input: stdin.txt\n", encoding="utf-8")
    loaded = load_config([config])
    assert loaded["test_input"] == str(payload.resolve())


def test_config_test_input_must_exist(tmp_path):
    config = tmp_path / "config.yml"
    config.write_text("test_input: missing.txt\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="does not exist"):
        load_config([config])


def test_cli_config_preset_then_file_values_then_explicit_cli(monkeypatch, tmp_path):
    captured = {}

    class Result:
        output = "echo hello\n"
        seed = 42
        layers_applied = ["id-mangle"]
        elapsed_ms = 1.0
        verified = False

    class Engine:
        def __init__(self, config):
            captured["config"] = config

        def run(self, source):
            return Result()

    monkeypatch.setattr("obfush.cli.PolymorphicEngine", Engine)
    config = tmp_path / "config.yml"
    destination = tmp_path / "output.sh"
    config.write_text(
        "preset: stealth\nintensity: 0.6\nmin_layers: 3\nworkers: 2\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(main, [
        "-", str(destination), "--config", str(config),
        "--intensity", "0.25", "--eval-mode", "direct-exec",
    ], input="echo hello\n")

    assert result.exit_code == 0, result.output
    engine_config = captured["config"]
    assert engine_config.intensity == 0.25
    assert engine_config.min_layers == 3
    assert engine_config.eval_mode == "direct-exec"
    assert engine_config.force_layers == [
        "id-mangle", "str-shred", "cmd-sub", "entropy-mask",
    ]


def test_no_config_ignores_discovered_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    Path(".obfushrc").write_text("intensity: 2\n", encoding="utf-8")
    destination = tmp_path / "output.sh"

    result = CliRunner().invoke(
        main,
        ["-", str(destination), "--no-config", "--seed", "42"],
        input="echo hello\n",
    )

    assert result.exit_code == 0, result.output


def test_config_and_no_config_are_mutually_exclusive(tmp_path):
    config = tmp_path / "config.yml"
    config.write_text("intensity: 0.5\n", encoding="utf-8")
    result = CliRunner().invoke(main, [
        "-", str(tmp_path / "out.sh"), "--config", str(config), "--no-config",
    ], input="echo hello\n")
    assert result.exit_code == 2
    assert "cannot be combined" in result.output
