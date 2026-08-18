"""Core engine regression tests."""

from obfush.engine.core import EngineConfig, PolymorphicEngine, _trim_decoys_to_budget
from obfush.engine.layer_selector import LayerPlan
from obfush.layers.base import LayerStats


class _RejectedNestedMutation:
    name = "rejected-mutation"

    def transform(self, ast, config):
        ast["body"][0]["parts"][0]["value"] = "corrupted"
        return ast, LayerStats(nodes_modified=1)

    def validate(self, ast_before, ast_after):
        return False


def test_failed_layer_rolls_back_nested_mutation(monkeypatch):
    """Validation failure restores nested nodes, not only the root dict."""
    monkeypatch.setattr(
        "obfush.engine.core.LayerSelector.select",
        lambda self: [LayerPlan("rejected-mutation", 1.0, 42)],
    )
    monkeypatch.setattr(
        "obfush.engine.core.get_layer",
        lambda name: _RejectedNestedMutation(),
    )

    result = PolymorphicEngine(EngineConfig(seed=42)).run("echo intact\n")

    assert "corrupted" not in result.output
    assert result.output == "echo intact\n"


def test_size_budget_trims_junk_and_decoy_nodes():
    ast = {
        "type": "script",
        "body": [
            {"type": "command", "parts": [{"type": "word", "value": "echo", "pos": None}, {"type": "word", "value": "ok", "pos": None}]},
            {"type": "command", "parts": [{"type": "word", "value": ":", "pos": None}, {"type": "word", "value": '"large decoy payload"', "pos": None}], "_decoy": True},
            {"type": "command", "parts": [{"type": "word", "value": ":", "pos": None}, {"type": "word", "value": '"more junk payload"', "pos": None}], "_junk": True},
        ],
    }

    def emit(current):
        from obfush.engine.ast_emitter import emit as real_emit
        return real_emit(current)

    output, removed = _trim_decoys_to_budget(ast, emit(ast), 8, 2.0, emit)

    assert output == "echo ok\n"
    assert removed == 2


def test_default_engine_caps_decoy_heavy_output():
    source = "#!/bin/bash\necho hello\n"
    result = PolymorphicEngine(
        EngineConfig(
            seed=42,
            intensity=1.0,
            force_layers=["junk-inject", "entropy-mask"],
            min_layers=1,
            max_size_ratio=3.0,
        )
    ).run(source)

    assert len(result.output.encode("utf-8")) <= len(source.encode("utf-8")) * 3


def test_layer_that_exceeds_size_budget_is_rolled_back(monkeypatch):
    class OversizedLayer:
        name = "oversized"
        never_rollback = False

        def transform(self, ast, config):
            ast["body"].append({
                "type": "command",
                "parts": [{"type": "word", "value": "x" * 10000, "pos": None}],
            })
            return ast, LayerStats(nodes_modified=1)

        def validate(self, ast_before, ast_after):
            return True

    monkeypatch.setattr(
        "obfush.engine.core.LayerSelector.select",
        lambda self: [LayerPlan("oversized", 1.0, 42)],
    )
    monkeypatch.setattr("obfush.engine.core.get_layer", lambda name: OversizedLayer())

    # Use a source larger than 2KB so the engine doesn't auto-scale the ratio.
    # Padding must be real commands, not comments: the engine strips comments
    # before sizing, which would otherwise shrink the source back under 2KB.
    source = "echo intact\n" + "echo pad\n" * 400
    result = PolymorphicEngine(
        EngineConfig(seed=42, max_size_ratio=2.0)
    ).run(source)

    assert result.output == source
    assert result.layers_applied == []
    assert result.layer_stats["oversized"].custom["rolled_back"] == "size-budget"
    assert result.layer_stats["oversized"].elapsed_ms >= 0


def test_engine_records_timing_for_every_planned_layer():
    result = PolymorphicEngine(EngineConfig(
        seed=42,
        intensity=0.5,
        force_layers=["id-mangle", "str-shred", "cmd-sub"],
        min_layers=1,
    )).run("value=hello\nprintf '%s\\n' \"$value\"\n")
    assert set(result.layer_stats) == {"id-mangle", "str-shred", "cmd-sub"}
    assert all(stats.elapsed_ms >= 0 for stats in result.layer_stats.values())
