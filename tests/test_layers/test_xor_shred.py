"""Pure-Bash XOR string reconstruction tests."""

import random
import re
import subprocess

import pytest

from obfush.engine.ast_emitter import emit
from obfush.engine.ast_parser import parse_bash
from obfush.engine.core import EngineConfig, PolymorphicEngine
from obfush.engine.normalizer import normalize
from obfush.engine.security_analyzer import analyze_source
from obfush.layers.base import LayerConfig
from obfush.layers.str_shred import LayerImpl
from obfush.utils.name_pool import NamePool
from obfush.utils.string_utils import random_shred, to_xor_reconstruction


def _evaluate(expression: str, prefix: str = "") -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash"],
        input=(prefix + f"printf '%s' {expression}\n").encode("utf-8"),
        capture_output=True,
        timeout=10,
    )


@pytest.mark.parametrize("value", [
    "secret payload",
    "quotes ' \" dollar $ backtick ` slash \\",
    "line one\nline two",
    "snowman \u2603 and cafe \u00e9",
    "x",
])
@pytest.mark.parametrize("strict_prefix", ["", "set -eu\n"])
def test_xor_round_trips_in_real_bash(value, strict_prefix):
    expression = to_xor_reconstruction(
        value, random.Random(42), NamePool(random.Random(42)),
    )
    result = _evaluate(expression, strict_prefix)
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    assert result.stdout == value.encode("utf-8")
    assert result.stderr == b""


def test_xor_key_is_split_and_plaintext_is_absent():
    value = "highly recognizable secret"
    expression = to_xor_reconstruction(
        value, random.Random(42), NamePool(random.Random(42)),
    )
    assert value not in expression
    assert expression.count(" ^ ") >= 3
    assert "for " in expression
    assert "printf -v" in expression
    assert "base64" not in expression
    assert "xxd" not in expression
    assert "eval" not in expression


def test_xor_is_deterministic_and_seed_polymorphic():
    first = to_xor_reconstruction(
        "payload", random.Random(42), NamePool(random.Random(42)),
    )
    repeated = to_xor_reconstruction(
        "payload", random.Random(42), NamePool(random.Random(42)),
    )
    different = to_xor_reconstruction(
        "payload", random.Random(99), NamePool(random.Random(99)),
    )
    assert first == repeated
    assert first != different


def test_xor_runtime_variables_do_not_escape_subshell():
    expression = to_xor_reconstruction(
        "payload", random.Random(42), NamePool(random.Random(42)),
    )
    names = sorted(set(re.findall(r"\b(_[A-Za-z0-9_]+)=", expression)))
    prefix = "\n".join(f"{name}=original" for name in names) + "\n"
    suffix = "\n" + "\n".join(
        f"printf '|%s' \"${{{name}}}\"" for name in names
    ) + "\n"
    process = subprocess.run(
        ["bash"],
        input=(prefix + f"printf '%s' {expression}" + suffix).encode("utf-8"),
        capture_output=True,
        timeout=10,
    )
    assert process.returncode == 0
    assert process.stdout == ("payload" + "|original" * len(names)).encode("utf-8")


@pytest.mark.parametrize("value", ["payload\n", "nul\0value"])
def test_xor_rejects_unrepresentable_values(value):
    with pytest.raises(ValueError):
        to_xor_reconstruction(value, random.Random(42), NamePool(random.Random(42)))


def test_random_shred_can_force_xor(monkeypatch):
    rng = random.Random(42)
    monkeypatch.setattr(rng, "choice", lambda methods: "xor")
    expression = random_shred(
        "payload", rng, "no-eval", NamePool(random.Random(42)),
    )
    result = _evaluate(expression)
    assert result.returncode == 0
    assert result.stdout == b"payload"


def test_random_shred_excludes_xor_without_name_pool(monkeypatch):
    observed = []

    class InspectRandom(random.Random):
        def choice(self, sequence):
            observed.append(tuple(sequence))
            return sequence[0]

    random_shred("payload", InspectRandom(42), "no-eval", None)
    assert "xor" not in observed[0]


def test_layer_forced_xor_reports_stats_and_analyzer_metadata(monkeypatch):
    import obfush.layers.str_shred as module

    original = module.random_shred

    def force_xor(value, rng, eval_mode, name_pool=None):
        if name_pool is None or "%" in value or "\\n" in value:
            return original(value, rng, eval_mode, name_pool)
        return to_xor_reconstruction(value, rng, name_pool)

    monkeypatch.setattr(module, "random_shred", force_xor)
    source = "value='secret payload'\nprintf '%s\\n' \"$value\"\n"
    ast = normalize(parse_bash(source))
    config = LayerConfig(
        intensity=1.0,
        seed=42,
        rng=random.Random(42),
        eval_mode="no-eval",
        name_pool=NamePool(random.Random(42)),
    )
    transformed, stats = LayerImpl().transform(ast, config)
    output = emit(transformed)
    process = subprocess.run(
        ["bash"], input=output.encode("utf-8"), capture_output=True, timeout=10,
    )
    analysis = analyze_source(output)
    assert process.returncode == 0, process.stderr.decode("utf-8", errors="replace")
    assert process.stdout == b"secret payload\n"
    assert stats.xor_reconstructions >= 1
    assert analysis.xor_reconstruction_count >= 1
    assert "secret payload" not in output
    assert analysis.standalone_eval_count == 0
    assert analysis.xxd_command_count == 0
    assert analysis.legacy_fingerprint_count == 0


def test_xor_name_pool_uniqueness_across_many_expressions():
    pool = NamePool(random.Random(42))
    expressions = [
        to_xor_reconstruction(f"payload-{index}", random.Random(index), pool)
        for index in range(50)
    ]
    assigned = [
        name
        for expression in expressions
        for name in re.findall(r"\b(_[A-Za-z0-9_]+)=", expression)
    ]
    assert len(assigned) == len(set(assigned))


@pytest.mark.parametrize("mode", ["ok", "no-eval", "direct-exec"])
def test_engine_xor_capable_pipeline_preserves_behavior_across_seeds(mode):
    source = "#!/bin/bash\nvalue='secret payload with spaces'\nprintf '%s\\n' \"$value\"\n"
    expected = b"secret payload with spaces\n"
    saw_xor = False
    for seed in range(40):
        result = PolymorphicEngine(EngineConfig(
            seed=seed,
            intensity=1.0,
            force_layers=["str-shred"],
            min_layers=1,
            eval_mode=mode,
            max_size_ratio=100.0,
        )).run(source)
        process = subprocess.run(
            ["bash"],
            input=result.output.encode("utf-8"),
            capture_output=True,
            timeout=10,
        )
        assert process.returncode == 0, process.stderr.decode("utf-8", errors="replace")
        assert process.stdout == expected
        assert process.stderr == b""
        saw_xor = saw_xor or result.layer_stats["str-shred"].xor_reconstructions > 0
    assert saw_xor
