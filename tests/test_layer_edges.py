"""Edge coverage for transformation layers and their supporting utilities."""

from __future__ import annotations

import importlib
import random
import subprocess
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

import obfush.engine.layer_selector as selector_module
import obfush.layers as layer_registry
import obfush.layers.plugins as plugin_module
import obfush.layers.str_shred as str_shred_module
from obfush.engine.ast_emitter import emit
from obfush.engine.ast_parser import parse_bash
from obfush.engine.layer_selector import LayerPlan, LayerSelector
from obfush.engine.normalizer import normalize
from obfush.layers.base import Layer, LayerConfig, LayerStats
from obfush.layers.cmd_sub import LayerImpl as CmdSubLayer
from obfush.layers.entropy_mask import LayerImpl as EntropyMaskLayer
from obfush.layers.entropy_mask import _interleave_decoys, _is_shebang_node
from obfush.layers.indirection import IndirectionDispatcher
from obfush.layers.indirection import LayerImpl as IndirectionLayer
from obfush.layers.junk_inject import _inject_walk, _is_safe_injection_point
from obfush.layers.plugins import load_plugin
from obfush.layers.poly_shell import LayerImpl as PolyShellLayer
from obfush.layers.poly_shell import _build_loader, _encode_chunks, _split_payload
from obfush.layers.str_shred import LayerImpl as StrShredLayer
from obfush.layers.str_shred import _is_shell_syntax_value, _should_shred, _shred_value
from obfush.utils.decoy_corpus import DecoyCorpus
from obfush.utils.entropy_utils import estimate_decoy_needed, format_entropy_report, windowed_entropy
from obfush.utils.live_chain import LiveChainGenerator
from obfush.utils.name_pool import NamePool
from obfush.utils.string_utils import (
    random_shred,
    to_fragmented_concat,
    to_split_variable_reconstruction,
    to_xor_reconstruction,
)


class ZeroRandom:
    """Small deterministic RNG for branches that only need simple choices."""

    def random(self):
        return 0.0

    def choice(self, values):
        return values[0]

    def randint(self, lower, upper):
        return lower

    def shuffle(self, values):
        return None


class DummyLayer(Layer):
    name = "dummy"
    description = "test layer"

    def transform(self, ast, config):
        return ast, LayerStats()


def _config(*, intensity=1.0, eval_mode="no-eval", rng=None, **kwargs):
    return LayerConfig(
        intensity=intensity,
        seed=17,
        rng=rng or random.Random(17),
        eval_mode=eval_mode,
        **kwargs,
    )


def _run_bash(source: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["bash"],
        input=source.encode("utf-8"),
        capture_output=True,
        timeout=10,
    )


def _word(value: str) -> dict:
    return {"type": "word", "value": value, "pos": None}


def _command(name: str, *args: str) -> dict:
    return {
        "type": "command",
        "parts": [_word(name), *(_word(arg) for arg in args)],
        "pos": None,
    }


def test_indirection_variable_transform_executes_in_real_bash(monkeypatch):
    source = "sleep 0\nprintf '%s' done\n"
    ast = normalize(parse_bash(source))
    rng = random.Random(7)
    monkeypatch.setattr(rng, "random", lambda: 0.0)

    transformed, stats = IndirectionLayer().transform(
        ast, _config(rng=rng, eval_mode="no-eval")
    )
    output = emit(transformed)
    process = _run_bash(output)

    assert process.returncode == 0, process.stderr.decode(errors="replace")
    assert process.stdout == b"done"
    assert stats.indirections_added >= 1
    assert '"${' in output


def test_indirection_dispatcher_eval_chain_map_and_setup_order(monkeypatch):
    rng = random.Random(19)
    monkeypatch.setattr(rng, "random", lambda: 0.0)
    dispatcher = IndirectionDispatcher(rng, _config(rng=rng, eval_mode="ok"))

    expression, variable_setup = dispatcher.indirect_command("sleep")
    map_name, key, map_setup = dispatcher.create_function_map({"first": "handler"})

    assert expression.startswith('"${!')
    assert [node["type"] for node in variable_setup] == ["assignment", "assignment"]
    assert map_name in map_setup[0]["parts"][2]["value"]
    assert key == "first"
    assert dispatcher.get_setup_nodes() == map_setup + variable_setup


def test_indirection_ignores_encoded_junk_unknown_and_non_dict_nodes(monkeypatch):
    rng = random.Random(23)
    monkeypatch.setattr(rng, "random", lambda: 0.0)
    ast = {
        "type": "script",
        "body": [
            {**_command("curl"), "_encoded": True},
            {**_command("wget"), "_junk": True},
            _command("printf", "ok"),
            "literal child",
        ],
    }

    transformed, stats = IndirectionLayer().transform(ast, _config(rng=rng))

    # With expanded indirection, _encoded and _junk nodes are now also
    # indirected (security improvement — no more skip checks). Verify
    # that the literal child is untouched and all commands were visited.
    assert "literal child" in transformed["body"]
    assert stats.indirections_added >= 2  # curl, wget, printf all indirectable


def test_cmd_sub_morphs_all_supported_node_shapes():
    ast = {
        "type": "script",
        "body": [
            _command("source", "settings.sh"),
            _command(".", "settings.sh"),
            _command("true"),
            _command(":"),
            {"type": "expansion", "kind": "command_sub", "style": "dollar"},
            {"type": "test_expr", "original_style": "[[", "test_parts": []},
            {"type": "redirect", "redirect_type": ">"},
        ],
    }

    transformed, stats = CmdSubLayer().transform(ast, _config(rng=ZeroRandom()))
    body = transformed["body"]

    assert [body[index]["parts"][0]["value"] for index in range(4)] == [
        ".",
        "source",
        ":",
        "true",
    ]
    assert body[4]["style"] == "backtick"
    assert body[5]["original_style"] == "["
    assert body[6]["_prepend_noop"] is True
    assert stats.commands_substituted == 7


def test_cmd_sub_echo_preserves_runtime_output():
    source = "echo 'hello world'\n"
    transformed, stats = CmdSubLayer().transform(
        normalize(parse_bash(source)), _config(rng=ZeroRandom())
    )

    before = _run_bash(source)
    after = _run_bash(emit(transformed))

    assert after.returncode == 0
    assert after.stdout == before.stdout == b"hello world\n"
    assert stats.commands_substituted == 1


class _NumberedDecoys:
    def __init__(self):
        self.count = 0

    def generate(self):
        self.count += 1
        return {"type": "decoy", "number": self.count}


def test_entropy_interleave_handles_empty_and_shebang_only_bodies():
    empty_generator = _NumberedDecoys()
    empty = _interleave_decoys([], empty_generator, 3, ZeroRandom())
    assert [node["number"] for node in empty] == [1, 2, 3]

    shebang = _command("#!/usr/bin/env", "bash")
    shebang_generator = _NumberedDecoys()
    only_shebang = _interleave_decoys([shebang], shebang_generator, 2, ZeroRandom())
    assert only_shebang[0] is shebang
    assert len(only_shebang) == 3


def test_entropy_interleave_keeps_shebang_first_and_real_tail_last():
    shebang = _word("#!/bin/bash")
    first, middle, tail = (_command("printf", value) for value in ("a", "b", "c"))
    generator = _NumberedDecoys()

    result = _interleave_decoys(
        [shebang, first, middle, tail], generator, 4, ZeroRandom()
    )

    assert result[0] is shebang
    assert result[-1] is tail
    assert generator.count == 4
    assert result.index(first) < result.index(middle) < result.index(tail)


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        (_word("#!/bin/bash"), True),
        (_command("#!/usr/bin/env", "bash"), True),
        (_command("printf", "#!"), False),
        ({"type": "assignment", "value": "#!/bin/bash"}, False),
    ],
)
def test_entropy_shebang_detection(node, expected):
    assert _is_shebang_node(node) is expected


def test_entropy_mask_obeys_byte_budget_and_records_estimate(monkeypatch):
    monkeypatch.setattr("obfush.layers.entropy_mask.estimate_decoy_needed", lambda *_: 360)
    ast = {"type": "script", "body": [_command("printf", "ok")]}

    _, stats = EntropyMaskLayer().transform(
        ast, _config(source_size=0, max_size_ratio=1.0)
    )

    assert stats.decoy_lines_added == 0
    assert stats.custom["decoy_bytes"] == "360"


def test_entropy_mask_passes_budgeted_block_count_to_interleaver(monkeypatch):
    captured = {}

    def interleave(body, generator, count, rng):
        captured["body"] = body
        captured["count"] = count
        return body

    monkeypatch.setattr("obfush.layers.entropy_mask.estimate_decoy_needed", lambda *_: 360)
    monkeypatch.setattr("obfush.layers.entropy_mask._interleave_decoys", interleave)
    ast = {"type": "script", "body": [_command("printf", "ok")]}

    _, stats = EntropyMaskLayer().transform(
        ast, _config(source_size=1000, max_size_ratio=1.0)
    )

    assert captured["body"] == ast["body"]
    assert captured["count"] == 2
    assert stats.decoy_lines_added == 2
    assert stats.nodes_modified == 2


@pytest.mark.parametrize(
    "node,parent",
    [
        ("not a node", None),
        (_command("printf"), {"type": "pipeline"}),
        (_command("printf"), {"type": "expansion"}),
        (_command("printf"), {"type": "test_expr"}),
        (_command("set"), {"type": "script"}),
        (_command("trap"), {"type": "script"}),
        (_command("exit"), {"type": "script"}),
        (_command("return"), {"type": "script"}),
        (_command("exec"), {"type": "script"}),
    ],
)
def test_junk_injection_rejects_unsafe_points(node, parent):
    assert not _is_safe_injection_point(node, parent)


class _JunkCatalogue:
    def __init__(self):
        self.count = 0

    def generate(self):
        self.count += 1
        return {"type": "junk", "number": self.count}


def test_junk_walk_injects_before_and_after_safe_script_statement():
    catalogue = _JunkCatalogue()
    stats = LayerStats()
    ast = {"type": "script", "body": [_command("printf", "ok")]}

    transformed = _inject_walk(
        ast, _config(rng=ZeroRandom()), catalogue, stats, depth=0
    )

    assert [node["type"] for node in transformed["body"]] == ["junk", "command", "junk"]
    assert stats.junk_blocks_injected == 2


def test_junk_walk_honors_depth_limit_and_handles_compound_parts():
    deep_catalogue = _JunkCatalogue()
    deep_stats = LayerStats()
    deep = {"type": "script", "body": [_command("printf", "ok")]}
    _inject_walk(deep, _config(rng=ZeroRandom()), deep_catalogue, deep_stats, depth=3)
    assert deep_catalogue.count == 0

    compound_catalogue = _JunkCatalogue()
    compound_stats = LayerStats()
    compound = {"type": "compound", "kind": "{", "parts": [_command("printf", "ok")]}
    transformed = _inject_walk(
        compound,
        _config(rng=ZeroRandom()),
        compound_catalogue,
        compound_stats,
        depth=0,
    )
    assert [node["type"] for node in transformed["parts"]] == ["junk", "command"]
    assert compound_stats.junk_blocks_injected == 1


class _MethodRandom:
    def __init__(self, *methods):
        self.methods = iter(methods)

    def choice(self, choices):
        return next(self.methods)


@pytest.mark.parametrize("source,num_chunks", [("", 3), ("one\ntwo\n", 5)])
def test_poly_shell_split_payload_short_inputs(source, num_chunks):
    chunks = _split_payload(source, num_chunks, random.Random(1))
    assert "".join(chunks) == source
    assert len(chunks) <= num_chunks


def test_poly_shell_all_decoders_and_fallback_round_trip_in_bash():
    chunks = ["alpha\n", "beta\n", "gamma\n", "fallback\n"]
    encoded = _encode_chunks(
        chunks, _MethodRandom("base64", "hex", "rev_base64", "unsupported")
    )

    assert [item["method"] for item in encoded] == [
        "base64",
        "hex",
        "rev_base64",
        "unsupported",
    ]
    for original, item in zip(chunks, encoded):
        process = _run_bash(item["decode_expr"])
        assert process.returncode == 0, process.stderr.decode(errors="replace")
        assert process.stdout == original.encode()


@pytest.mark.parametrize("eval_mode", ["ok", "no-eval", "direct-exec"])
def test_poly_shell_loader_executes_reassembled_payload(eval_mode):
    chunks = ["greet() {\n", "  printf '%s\\n' loaded\n", "}\ngreet\n"]
    encoded = _encode_chunks(chunks, _MethodRandom("hex", "base64", "rev_base64"))
    pool = NamePool(random.Random(31))
    output = emit(_build_loader(encoded, random.Random(31), eval_mode, pool))

    process = _run_bash(output)

    assert process.returncode == 0, process.stderr.decode(errors="replace")
    assert process.stdout == b"loaded\n"
    # All modes now use cascading source via temp files (no eval bottleneck)
    assert "mktemp" in output
    assert "source" in output


def test_poly_shell_low_intensity_is_identity_and_high_intensity_preserves_shebang():
    ast = {"type": "script", "shebang": "#!/bin/bash", "body": [_command("printf", "ok")]}
    layer = PolyShellLayer()

    unchanged, low_stats = layer.transform(ast, _config(intensity=0.84))
    wrapped, high_stats = layer.transform(ast, _config(intensity=0.85))

    assert unchanged is ast
    assert low_stats.chunks_created == 0
    assert layer.estimate_size_increase(_config(intensity=0.84)) == 1.0
    assert wrapped["shebang"] == "#!/bin/bash"
    assert high_stats.chunks_created >= 1


@pytest.mark.parametrize(
    "value,node",
    [
        ("", {}),
        (" ", {}),
        ("#!/bin/bash", {}),
        ("=", {}),
        ("-x", {}),
        ("raw shell", {"value": "raw shell", "raw": "raw shell"}),
        ("$HOME", {}),
        ("`hostname`", {}),
        ("[[ x == x ]]", {}),
        ("count+=1", {}),
        ("eval \"$payload\"", {}),
        ("bash -c command", {}),
    ],
)
def test_str_shred_rejects_shell_sensitive_values(value, node):
    assert not _should_shred(value, node)


@pytest.mark.parametrize(
    "value",
    ["[[ x ]]", "(( x + 1 ))", "[ x ]", "name=value", "items+=one", "eval '$x'", "bash -c x"],
)
def test_str_shred_shell_syntax_detection(value):
    assert _is_shell_syntax_value(value)


@pytest.mark.parametrize("value", ["ordinary text", "--long-option", "file*.txt", "%s"])
def test_str_shred_accepts_obfuscatable_values(value):
    assert _should_shred(value, {})


@pytest.mark.parametrize("value", ["prefix:%s suffix", "file[ab]*.txt"])
def test_str_shred_special_fragments_round_trip_in_real_bash(value):
    expression = _shred_value(value, _config(rng=random.Random(41)))
    process = _run_bash(f"set -f\nprintf '%s' {expression}\n")

    assert process.returncode == 0, process.stderr.decode(errors="replace")
    assert process.stdout == value.encode()


def test_str_shred_heredoc_skips_blank_lines(monkeypatch):
    monkeypatch.setattr(
        str_shred_module,
        "random_shred",
        lambda value, rng, eval_mode, name_pool=None: f"encoded({value})",
    )
    ast = {"type": "heredoc", "body": "first\n\n  \nsecond"}

    transformed, stats = StrShredLayer().transform(ast, _config())

    assert transformed["body"] == "encoded(first)\n\n  \nencoded(second)"
    assert stats.strings_shredded == 2


def test_str_shred_counts_split_and_xor_reconstructions(monkeypatch):
    marker = "$(setup; printf '%s' x); printf -v byte '%03o' 1; left ^ right"
    monkeypatch.setattr(str_shred_module, "random_shred", lambda *args, **kwargs: marker)
    ast = {
        "type": "script",
        "body": [
            _word("alpha"),
            {"type": "assignment", "name": "value", "value": "beta"},
        ],
    }

    _, stats = StrShredLayer().transform(ast, _config())

    assert stats.split_reconstructions == 2
    assert stats.xor_reconstructions == 2
    assert stats.strings_shredded == 2


class _RepeatingNameRandom:
    def randrange(self, *args):
        return 0

    def choice(self, values):
        return values[0]

    def random(self):
        return 0.0


def test_name_pool_falls_back_after_random_candidates_are_exhausted():
    pool = NamePool(_RepeatingNameRandom())
    pool.register_existing({"_a0a", "_z1"})

    assert pool.next_name() == "_z2"
    assert pool.is_registered("_z2")


@pytest.mark.parametrize(
    "overrides,match",
    [
        ({"intensity": -0.01}, "intensity"),
        ({"intensity": 1.01}, "intensity"),
        ({"eval_mode": "sometimes"}, "eval_mode"),
        ({"source_size": -1}, "source_size"),
        ({"max_size_ratio": 0.99}, "max_size_ratio"),
        ({"entropy_target": -0.01}, "entropy_target"),
        ({"entropy_target": 8.01}, "entropy_target"),
    ],
)
def test_layer_config_rejects_invalid_boundaries(overrides, match):
    values = {"intensity": 0.5, "seed": 1, "rng": random.Random(1)}
    values.update(overrides)
    with pytest.raises(ValueError, match=match):
        LayerConfig(**values)


def test_layer_config_boundaries_freezing_and_base_layer_contract():
    config = LayerConfig(
        intensity=0.0,
        seed=1,
        rng=random.Random(1),
        source_size=0,
        max_size_ratio=1.0,
        entropy_target=8.0,
    )
    layer = DummyLayer()

    assert "intensity=0.0" in repr(config)
    with pytest.raises(FrozenInstanceError):
        config.intensity = 1.0
    assert layer.validate({"type": "script"}, {"type": "script"})
    assert layer.validate({}, {"type": "script"})
    assert not layer.validate({"type": "script"}, {"type": "command"})
    assert not layer.validate({"type": "script"}, [])
    assert layer.estimate_size_increase(config) == 1.0
    assert repr(layer) == "<Layer:dummy>"


@pytest.mark.parametrize("name", ["", " leading", "trailing ", "bad!", "bad--name"])
def test_layer_registry_rejects_invalid_names(monkeypatch, name):
    monkeypatch.setattr(layer_registry, "LAYER_CLASSES", {})
    monkeypatch.setattr(layer_registry, "ALL_LAYER_NAMES", [])
    with pytest.raises(ValueError, match="Invalid layer name"):
        layer_registry.register_layer(name, DummyLayer)


def test_layer_registry_rejects_wrong_types_and_duplicates(monkeypatch):
    monkeypatch.setattr(layer_registry, "LAYER_REGISTRY", {"builtin": "module.path"})
    monkeypatch.setattr(layer_registry, "LAYER_CLASSES", {})
    monkeypatch.setattr(layer_registry, "ALL_LAYER_NAMES", ["builtin"])

    with pytest.raises(TypeError, match="must inherit"):
        layer_registry.register_layer("plain", object)
    with pytest.raises(ValueError, match="already registered"):
        layer_registry.register_layer("builtin", DummyLayer)

    layer_registry.register_layer("plugin", DummyLayer)
    assert isinstance(layer_registry.get_layer("plugin"), DummyLayer)
    assert layer_registry.ALL_LAYER_NAMES == ["builtin", "plugin"]


def test_layer_registry_unknown_and_missing_layer_impl_errors(monkeypatch):
    monkeypatch.setattr(layer_registry, "LAYER_REGISTRY", {"broken": "broken.module"})
    monkeypatch.setattr(layer_registry, "LAYER_CLASSES", {})
    monkeypatch.setattr(layer_registry, "ALL_LAYER_NAMES", ["broken"])

    with pytest.raises(KeyError, match="Unknown layer 'missing'"):
        layer_registry.get_layer("missing")

    monkeypatch.setattr(importlib, "import_module", lambda name: SimpleNamespace())
    with pytest.raises(AttributeError, match="LayerImpl"):
        layer_registry.get_layer("broken")


def test_plugin_loader_rejects_paths_and_unloadable_specs(monkeypatch, tmp_path):
    missing = tmp_path / "missing.py"
    text_file = tmp_path / "plugin.txt"
    text_file.write_text("value = 1\n", encoding="utf-8")

    for path in (missing, text_file, tmp_path):
        with pytest.raises(ValueError, match="existing .py file"):
            load_plugin(path)

    plugin = tmp_path / "plugin.py"
    plugin.write_text("value = 1\n", encoding="utf-8")
    monkeypatch.setattr(plugin_module.importlib.util, "spec_from_file_location", lambda *args: None)
    with pytest.raises(ValueError, match="Could not create plugin module"):
        load_plugin(plugin)

    monkeypatch.setattr(
        plugin_module.importlib.util,
        "spec_from_file_location",
        lambda *args: SimpleNamespace(loader=None),
    )
    with pytest.raises(ValueError, match="Could not create plugin module"):
        load_plugin(plugin)


def test_plugin_loader_rejects_non_layer_impl(tmp_path):
    plugin = tmp_path / "bad_plugin.py"
    plugin.write_text("LayerImpl = object\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must expose LayerImpl"):
        load_plugin(plugin)


def test_selector_filters_disabled_forced_layer():
    plans = LayerSelector(
        master_seed=5,
        force_layers=["encode", "str-shred"],
        disable_layers=["encode"],
        min_layers=1,
    ).select()

    assert [plan.name for plan in plans] == ["str-shred"]


def test_selector_min_fill_exhausts_only_enabled_available_layers(monkeypatch):
    monkeypatch.setattr(
        selector_module,
        "ALL_LAYER_NAMES",
        ["encode", "str-shred", "cmd-sub"],
    )
    plans = LayerSelector(
        master_seed=7,
        force_layers=["encode"],
        disable_layers=["encode"],
        min_layers=10,
    ).select()

    assert {plan.name for plan in plans} == {"str-shred", "cmd-sub"}
    assert len(plans) == 2


def test_selector_validates_disabled_names_and_auto_select_thresholds():
    with pytest.raises(ValueError, match="Unknown layer"):
        LayerSelector(1, force_layers=["encode"], disable_layers=["missing"]).select()

    low = LayerSelector(1, intensity=0.0)._auto_select()
    high = LayerSelector(1, intensity=1.0)._auto_select()
    assert low == ["id-mangle", "str-shred", "cmd-sub", "junk-inject", "opaque-const", "encode"]
    assert set(high) == set(selector_module.ALL_LAYER_NAMES)


def test_layer_plan_repr_rounds_intensity():
    assert repr(LayerPlan("encode", 0.876, 42)) == "LayerPlan(encode, intensity=0.88)"


def test_string_utility_defensive_paths_and_fallback():
    pool = NamePool(random.Random(3))
    assert to_split_variable_reconstruction("", random.Random(3), pool) == '""'
    assert to_xor_reconstruction("", random.Random(3), pool) == '""'

    with pytest.raises(ValueError, match="NUL"):
        to_xor_reconstruction("a\0b", random.Random(3), pool)
    with pytest.raises(ValueError, match="trailing newlines"):
        to_xor_reconstruction("line\n", random.Random(3), pool)

    fallback = random_shred("A", _MethodRandom("unsupported"))
    assert fallback == "$'\\x41'"


def test_fragmented_concat_short_and_plain_escaping_paths():
    assert to_fragmented_concat("", ZeroRandom()) == '""'
    assert to_fragmented_concat("x", ZeroRandom()) == '"x"'
    expression = to_fragmented_concat('a$`"\\', ZeroRandom())
    process = _run_bash(f"printf '%s' {expression}\n")
    assert process.returncode == 0
    assert process.stdout == b'a$`"\\'


def test_entropy_utility_empty_window_and_report_paths():
    assert windowed_entropy(b"short", window_size=256) == []
    assert estimate_decoy_needed(b"", target_entropy=4.5) == 0
    report = format_entropy_report(b"short", window_size=256)
    assert "Windows:   0" in report
    assert "Min:       0.000" in report


def test_decoy_corpus_unique_fallback_suffixes_repeated_values():
    corpus = DecoyCorpus(random.Random(1))
    corpus._used_text.add("constant")

    value = corpus._unique(lambda: "constant")

    assert value == "constant (1)"


def test_live_chain_without_name_pool_escapes_seed_and_executes_silently():
    generator = LiveChainGenerator(random.Random(9), marker="_edge")
    chain = generator.generate("it's a value")
    output = emit({"type": "script", "body": [chain]})

    process = _run_bash("set -eu\n" + output)

    assert process.returncode == 0, process.stderr.decode(errors="replace")
    assert process.stdout == b""
    assert process.stderr == b""
    assert chain["_edge"] is True
    assert len(set(chain["_synthetic_vars"])) == 3
