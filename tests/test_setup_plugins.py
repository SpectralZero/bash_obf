"""Tests for explicit local plugins and the first-run configuration wizard."""

from __future__ import annotations

from click.testing import CliRunner

from obfush.cli import main
from obfush.layers import get_layer
from obfush.layers.plugins import load_plugin


def test_setup_writes_restrictive_validated_config(monkeypatch, tmp_path):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--setup"],
        input="standard\n0.7\nno-eval\nn\n",
    )

    assert result.exit_code == 0, result.output
    config = tmp_path / ".obfushrc"
    assert config.exists()
    assert "intensity: 0.7" in config.read_text(encoding="utf-8")
    assert "eval_mode: no-eval" in config.read_text(encoding="utf-8")


def test_setup_does_not_overwrite_without_confirmation(monkeypatch, tmp_path):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    config = tmp_path / ".obfushrc"
    config.write_text("intensity: 0.2\n", encoding="utf-8")

    result = CliRunner().invoke(main, ["--setup"], input="n\n")

    assert result.exit_code != 0
    assert config.read_text(encoding="utf-8") == "intensity: 0.2\n"


def test_explicit_plugin_loads_layer_impl(tmp_path):
    plugin = tmp_path / "plugin.py"
    plugin.write_text(
        """from obfush.layers.base import Layer, LayerStats\n
class LayerImpl(Layer):
    name = 'test-plugin'
    description = 'test layer'
    def transform(self, ast, config):
        return ast, LayerStats()
""",
        encoding="utf-8",
    )

    loaded = load_plugin(plugin)

    assert loaded.name == "test-plugin"
    assert loaded.path == str(plugin.resolve())
    assert get_layer("test-plugin").name == "test-plugin"


def test_cli_rejects_plugin_without_layer_impl(tmp_path):
    plugin = tmp_path / "bad.py"
    plugin.write_text("value = 1\n", encoding="utf-8")

    result = CliRunner().invoke(
        main,
        ["--plugin", str(plugin), "-", "-"],
        input="echo ok\n",
    )

    assert result.exit_code == 2
    assert "Could not load plugin" in result.output


def test_cli_binary_checksum_metadata(monkeypatch, tmp_path):
    from obfush.compiler import BinaryBuildResult
    import hashlib
    from pathlib import Path

    class Result:
        output = "echo output\n"
        seed = 42
        layers_applied = ["id-mangle"]
        elapsed_ms = 1.0
        verified = False
        layer_stats = {}

    class Engine:
        def __init__(self, config):
            pass

        def run(self, source):
            return Result()

    artifact = b"binary"
    monkeypatch.setattr("obfush.cli.PolymorphicEngine", Engine)

    def build(payload, output_path, **kwargs):
        Path(output_path).write_bytes(artifact)
        return BinaryBuildResult(
            output_path=str(Path(output_path).resolve()),
            output_bytes=len(artifact),
            sha256=hashlib.sha256(artifact).hexdigest(),
            compiler="cc",
            backend="native",
            target="linux",
            static_linked=False,
            key_size=16,
            anti_debug_checks=[],
        )

    monkeypatch.setattr("obfush.compiler.build_binary", build)
    output = tmp_path / "loader"
    result = CliRunner().invoke(
        main,
        ["-", str(output), "--no-config", "--output-mode", "binary", "--checksum"],
        input="echo source\n",
    )

    assert result.exit_code == 0, result.output
    checksum = output.with_name("loader.sha256")
    assert checksum.read_text(encoding="utf-8").startswith(
        f"{hashlib.sha256(artifact).hexdigest()}  loader"
    )
