"""Opaque arithmetic generation and layer integration tests."""

import random
import subprocess

import pytest

from obfush.engine.ast_emitter import emit
from obfush.engine.ast_parser import parse_bash
from obfush.engine.normalizer import normalize
from obfush.layers.base import LayerConfig
from obfush.layers.opaque_const import LayerImpl, generate_opaque


def _run(source: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash"], input=source.encode("utf-8"), capture_output=True, timeout=10,
    )


@pytest.mark.parametrize("target", [-1000, -1, 0, 1, 2, 42, 65535, 1_000_000_000])
@pytest.mark.parametrize("seed", range(20))
def test_generate_opaque_evaluates_to_target(target, seed):
    expression = generate_opaque(target, random.Random(seed))
    result = _run(f"printf '%s' {expression}\n")
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    assert result.stdout == str(target).encode("ascii")


def test_generate_opaque_is_deterministic_and_polymorphic():
    first = generate_opaque(42, random.Random(42))
    assert first == generate_opaque(42, random.Random(42))
    assert len({generate_opaque(42, random.Random(seed)) for seed in range(20)}) >= 4


def test_layer_rewrites_sleep_exit_and_return_arguments():
    source = "sleep 0\nf(){ return 7; }\nf\nprintf '%s' $?\nexit 0\n"
    ast = normalize(parse_bash(source))
    transformed, stats = LayerImpl().transform(
        ast, LayerConfig(1.0, 42, random.Random(42)),
    )
    output = emit(transformed)
    result = _run(output)
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    assert result.stdout == b"7"
    assert "$((" in output
    assert int(stats.custom["constants_obfuscated"]) >= 3


def test_layer_rewrites_numeric_test_and_arithmetic_constructs():
    source = """#!/bin/bash
value=7
if [[ $value -gt 5 ]]; then printf 'test-ok\\n'; fi
(( total = 10 + 5 * 3 ))
printf '%s\\n' "$total"
for (( i=0; i<3; i++ )); do printf '%s' "$i"; done
printf '\\n'
"""
    ast = normalize(parse_bash(source))
    transformed, stats = LayerImpl().transform(
        ast, LayerConfig(1.0, 42, random.Random(42)),
    )
    output = emit(transformed)
    result = _run(output)
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    assert result.stdout == b"test-ok\n25\n012\n"
    assert "$((" in output
    assert int(stats.custom["constants_obfuscated"]) >= 5


def test_layer_preserves_versions_ports_strings_and_array_subscripts():
    source = """#!/bin/bash
version='2.13.7'
url='http://127.0.0.1:8080/v2'
printf '%s|%s\\n' "$version" "$url"
"""
    ast = normalize(parse_bash(source))
    transformed, _ = LayerImpl().transform(
        ast, LayerConfig(1.0, 42, random.Random(42)),
    )
    output = emit(transformed)
    result = _run(output)
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    assert result.stdout == b"2.13.7|http://127.0.0.1:8080/v2\n"
    assert "2.13.7" in output
    assert "127.0.0.1:8080" in output


def test_layer_preserves_array_subscript_word_without_rewriting():
    ast = {
        "type": "script",
        "body": [{
            "type": "command",
            "parts": [
                {"type": "word", "value": "printf", "pos": None},
                {"type": "word", "value": "%s", "pos": None},
                {"type": "word", "value": "${items[2]}", "raw": "${items[2]}", "pos": None},
            ],
            "pos": None,
        }],
    }
    transformed, stats = LayerImpl().transform(
        ast, LayerConfig(1.0, 42, random.Random(42)),
    )
    assert transformed["body"][0]["parts"][2]["value"] == "${items[2]}"
    assert stats.custom == {}


def test_layer_works_under_strict_mode():
    source = 'set -eu\nvalue=42\n[[ $value -eq 42 ]]\nprintf \'%s\\n\' "$value"\n'
    ast = normalize(parse_bash(source))
    transformed, _ = LayerImpl().transform(
        ast, LayerConfig(1.0, 42, random.Random(42)),
    )
    result = _run(emit(transformed))
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    assert result.stdout == b"42\n"


def test_layer_skips_values_outside_safe_range():
    source = "exit 1000000001\n"
    ast = normalize(parse_bash(source))
    transformed, stats = LayerImpl().transform(
        ast, LayerConfig(1.0, 42, random.Random(42)),
    )
    output = emit(transformed)
    assert "1000000001" in output
    assert stats.custom == {}
