"""Conservative CFF state dispatcher tests."""

import random
import subprocess

import pytest

from obfush.engine.ast_emitter import emit
from obfush.engine.ast_parser import parse_bash
from obfush.engine.core import EngineConfig, PolymorphicEngine
from obfush.engine.normalizer import normalize
from obfush.engine.security_analyzer import analyze_source
from obfush.layers.base import LayerConfig
from obfush.layers.cff import LayerImpl
from obfush.utils.name_pool import NamePool


def _transform(source: str, seed: int = 42, intensity: float = 1.0):
    ast = normalize(parse_bash(source))
    config = LayerConfig(
        intensity=intensity,
        seed=seed,
        rng=random.Random(seed),
        name_pool=NamePool(random.Random(seed)),
    )
    transformed, stats = LayerImpl().transform(ast, config)
    return emit(transformed), stats


def _run(source: str) -> subprocess.CompletedProcess:
    syntax = subprocess.run(
        ["bash", "-n"], input=source.encode("utf-8"), capture_output=True, timeout=10,
    )
    assert syntax.returncode == 0, f"{syntax.stderr.decode()}\n{source}"
    return subprocess.run(
        ["bash"], input=source.encode("utf-8"), capture_output=True, timeout=10,
    )


def test_cff_preserves_order_scope_and_final_status():
    source = """a=one
b=two
printf '%s|' "$a"
printf '%s' "$b"
false
"""
    output, stats = _transform(source)
    process = _run(output)
    analysis = analyze_source(output)
    assert process.returncode == 1
    assert process.stdout == b"one|two"
    assert process.stderr == b""
    assert analysis.cff_dispatcher_count == 1
    assert int(stats.custom["blocks_flattened"]) == 5
    assert int(stats.custom["router_states"]) >= 1


def test_cff_state_variable_is_removed_before_tail_command():
    source = "a=one\nb=two\nc=three\ncompgen -A variable\n"
    output, stats = _transform(source)
    state_name = output.split("=", 1)[0]
    process = _run(output)
    assert process.returncode == 0
    assert state_name.encode() not in process.stdout.splitlines()
    assert f"unset {state_name}" in output
    assert int(stats.custom["dispatchers_created"]) == 1


def test_cff_splits_long_runs_at_eight_blocks():
    source = "".join(f"v{index}={index}\n" for index in range(18)) + "printf done\n"
    output, stats = _transform(source)
    process = _run(output)
    assert process.returncode == 0
    assert process.stdout == b"done"
    assert int(stats.custom["dispatchers_created"]) == 3
    assert int(stats.custom["blocks_flattened"]) == 19


def test_cff_is_deterministic_and_seed_polymorphic():
    source = "a=1\nb=2\nprintf one\nprintf two\n"
    first, _ = _transform(source, seed=42)
    repeated, _ = _transform(source, seed=42)
    outputs = {_transform(source, seed=seed)[0] for seed in range(10)}
    assert first == repeated
    assert len(outputs) >= 5
    for output in outputs:
        process = _run(output)
        assert process.stdout == b"onetwo"


@pytest.mark.parametrize("sensitive", [
    "set -e\na=1\nb=2\nprintf ok\n",
    "set -x\na=1\nb=2\nprintf ok\n",
    "trap ':' EXIT\na=1\nb=2\nprintf ok\n",
    "a=1\nprintf '%s' $?\nb=2\nprintf ok\n",
    "a=1\nprintf '%s' \"$LINENO\"\nb=2\nprintf ok\n",
])
def test_cff_skips_status_debug_and_trap_sensitive_scripts(sensitive):
    output, stats = _transform(sensitive)
    assert "while ((" not in output
    assert stats.custom["skipped"] == "status-or-debug-sensitive"


@pytest.mark.parametrize("barrier", [
    "cd /tmp",
    "read value",
    "export value=one",
    "local value=one",
    "declare value=one",
    "return 0",
    "exit 0",
    "exec true",
    "wait",
])
def test_cff_does_not_include_unsafe_commands_in_dispatcher(barrier):
    source = f"a=1\nb=2\n{barrier}\nc=3\nd=4\nprintf ok\n"
    output, _ = _transform(source)
    if "while ((" in output:
        dispatcher = output.split("while ((", 1)[1].split("done", 1)[0]
        assert barrier not in dispatcher


def test_cff_router_states_are_reachable_and_terminate():
    source = "a=1\nb=2\nprintf one\nprintf two\nprintf three\n"
    output, stats = _transform(source)
    process = _run(output)
    assert process.returncode == 0
    assert process.stdout == b"onetwothree"
    assert ': "${' in output
    assert int(stats.custom["router_states"]) >= 1


def test_engine_size_budget_rolls_back_cff_for_tiny_script():
    source = "a=1\nb=2\nprintf ok\n"
    result = PolymorphicEngine(EngineConfig(
        seed=42,
        intensity=1.0,
        force_layers=["cff"],
        min_layers=1,
        max_size_ratio=1.0,
    )).run(source)
    assert result.layers_applied == []
    assert result.layer_stats["cff"].custom["rolled_back"] == "size-budget"
    assert result.output == source


def test_cff_requires_shared_name_pool():
    ast = normalize(parse_bash("a=1\nb=2\nprintf ok\n"))
    transformed, stats = LayerImpl().transform(
        ast, LayerConfig(1.0, 42, random.Random(42)),
    )
    assert stats.custom["skipped"] == "name-pool-unavailable"
    assert emit(transformed) == "a=1\nb=2\nprintf ok\n"
