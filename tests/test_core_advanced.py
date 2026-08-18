"""Advanced core-engine orchestration and defensive behavior tests."""

from __future__ import annotations

import io
import json

import pytest
from rich.console import Console

from obfush.engine.core import EngineConfig, PolymorphicEngine
from obfush.engine.layer_selector import LayerPlan
from obfush.layers.base import LayerStats


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"max_size_ratio": 0.99}, "max_size_ratio"),
        ({"entropy_target": -0.01}, "entropy_target"),
        ({"entropy_target": 8.01}, "entropy_target"),
        ({"log_level": "TRACE"}, "log_level"),
    ],
)
def test_engine_config_rejects_unsafe_boundaries(options, message):
    with pytest.raises(ValueError, match=message):
        EngineConfig(**options)


def test_engine_generates_seed_when_none_is_configured(monkeypatch):
    monkeypatch.setattr("obfush.engine.core.generate_seed", lambda source: 8675309)
    monkeypatch.setattr("obfush.engine.core.LayerSelector.select", lambda self: [])

    result = PolymorphicEngine(EngineConfig()).run("echo generated\n")

    assert result.seed == 8675309
    assert result.output == "echo generated\n"


def test_dry_run_returns_clean_source_and_selected_plan(monkeypatch):
    plans = [LayerPlan("id-mangle", 0.75, 101), LayerPlan("str-shred", 0.5, 102)]
    monkeypatch.setattr("obfush.engine.core.LayerSelector.select", lambda self: plans)

    result = PolymorphicEngine(EngineConfig(seed=42, dry_run=True)).run(
        "#!/bin/bash\n# deployment detail\necho hello\n"
    )

    assert result.output.startswith("#!/bin/bash\n")
    assert "deployment detail" not in result.output
    assert result.output.endswith("echo hello\n")
    assert result.source == result.output
    assert result.layers_applied == ["id-mangle", "str-shred"]
    assert result.layer_stats == {}


def test_dump_ast_writes_parseable_debug_document(monkeypatch, tmp_path):
    destination = tmp_path / "parsed.json"
    monkeypatch.setattr("obfush.engine.core.LayerSelector.select", lambda self: [])

    PolymorphicEngine(EngineConfig(seed=42, dump_ast=str(destination))).run(
        "message=hello\nprintf '%s\\n' \"$message\"\n"
    )

    document = json.loads(destination.read_text(encoding="utf-8"))
    assert document["type"] == "script"
    assert document["body"]


class _ReportingLayer:
    def transform(self, ast, config):
        return ast, LayerStats(
            nodes_modified=1,
            identifiers_mangled=2,
            strings_shredded=3,
            split_reconstructions=4,
            xor_reconstructions=5,
            junk_blocks_injected=6,
            custom={"strategy": "test"},
        )

    def validate(self, ast_before, ast_after):
        return True


def test_verbose_run_reports_plan_layer_stats_and_summary(monkeypatch):
    monkeypatch.setattr(
        "obfush.engine.core.LayerSelector.select",
        lambda self: [LayerPlan("reporting", 0.6, 99)],
    )
    monkeypatch.setattr("obfush.engine.core.get_layer", lambda name: _ReportingLayer())
    stream = io.StringIO()
    engine = PolymorphicEngine(EngineConfig(seed=42, verbose=True))
    engine.console = Console(file=stream, force_terminal=False, width=120)

    result = engine.run("echo hello\n")
    report = stream.getvalue()

    assert result.layers_applied == ["reporting"]
    assert "Layer Execution Plan" in report
    assert "Applying reporting" in report
    assert "modified=1" in report
    assert "strategy=test" in report
    assert "obfush Complete" in report
    assert "Seed:     42" in report


@pytest.mark.parametrize("verification_result", [True, False])
def test_optional_verification_records_and_reports_result(
    monkeypatch, verification_result,
):
    observed = {}

    class StubVerifier:
        def __init__(self, timeout):
            observed["timeout"] = timeout

        def verify(self, *, original_source, obfuscated_source, test_input):
            observed.update(
                original=original_source,
                obfuscated=obfuscated_source,
                test_input=test_input,
            )
            return verification_result

    monkeypatch.setattr("obfush.engine.core.LayerSelector.select", lambda self: [])
    monkeypatch.setattr("obfush.engine.verifier.Verifier", StubVerifier)
    stream = io.StringIO()
    engine = PolymorphicEngine(
        EngineConfig(seed=42, verify=True, test_input="sample input")
    )
    engine.console = Console(file=stream, force_terminal=False)

    result = engine.run("echo hello\n")

    assert result.verified is verification_result
    assert observed == {
        "timeout": 30,
        "original": "echo hello\n",
        "obfuscated": "echo hello\n",
        "test_input": "sample input",
    }
    assert ("PASSED" if verification_result else "FAILED") in stream.getvalue()


def test_validation_failure_is_excluded_from_applied_layers(monkeypatch):
    class InvalidLayer:
        def transform(self, ast, config):
            ast.clear()
            return ast, LayerStats(nodes_modified=1)

        def validate(self, ast_before, ast_after):
            return False

    monkeypatch.setattr(
        "obfush.engine.core.LayerSelector.select",
        lambda self: [LayerPlan("invalid", 1.0, 42)],
    )
    monkeypatch.setattr("obfush.engine.core.get_layer", lambda name: InvalidLayer())

    result = PolymorphicEngine(EngineConfig(seed=42)).run("echo intact\n")

    assert result.output == "echo intact\n"
    assert result.layers_applied == []
    assert result.layer_stats["invalid"].custom["rolled_back"] == "validation"
