"""Split-variable reconstruction and string layer behavior tests."""

import random
import re
import subprocess

import pytest

from obfush.engine.ast_emitter import emit
from obfush.engine.ast_parser import parse_bash
from obfush.engine.normalizer import normalize
from obfush.layers.base import LayerConfig
from obfush.layers.str_shred import LayerImpl
from obfush.utils.name_pool import NamePool
from obfush.utils.string_utils import (
    random_shred,
    to_split_variable_reconstruction,
)


def _evaluate(expression: str, prefix: str = "") -> subprocess.CompletedProcess:
    source = prefix + f"printf '%s' {expression}\n"
    return subprocess.run(
        ["bash"], input=source.encode("utf-8"), capture_output=True, timeout=10,
    )


@pytest.mark.parametrize("value", [
    "secret payload",
    "quotes ' \" dollar $ backtick ` slash \\",
    "line one\nline two",
    "snowman \u2603 and cafe \u00e9",
    "x",
])
@pytest.mark.parametrize("strict_prefix", ["", "set -eu\n"])
def test_split_variable_round_trips_in_real_bash(value, strict_prefix):
    pool = NamePool(random.Random(11))
    expression = to_split_variable_reconstruction(value, random.Random(42), pool)
    result = _evaluate(expression, strict_prefix)
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    assert result.stdout == value.encode("utf-8")
    assert result.stderr == b""


def test_split_variable_is_deterministic_and_seed_polymorphic():
    first = to_split_variable_reconstruction(
        "payload", random.Random(42), NamePool(random.Random(42)),
    )
    repeated = to_split_variable_reconstruction(
        "payload", random.Random(42), NamePool(random.Random(42)),
    )
    different = to_split_variable_reconstruction(
        "payload", random.Random(99), NamePool(random.Random(99)),
    )
    assert first == repeated
    assert first != different


def test_split_variable_does_not_mutate_existing_shell_variables():
    pool = NamePool(random.Random(42))
    expression = to_split_variable_reconstruction("payload", random.Random(42), pool)
    generated_names = re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)=\$'", expression)
    prefix = "sentinel=unchanged\n" + "\n".join(
        f"{name}=original" for name in generated_names
    ) + "\n"
    suffix = "\nprintf '|%s' \"$sentinel\"\n" + "\n".join(
        f"printf '|%s' \"${{{name}}}\"" for name in generated_names
    ) + "\n"
    process = subprocess.run(
        ["bash"],
        input=(prefix + f"printf '%s' {expression}" + suffix).encode("utf-8"),
        capture_output=True,
        timeout=10,
    )
    assert process.returncode == 0, process.stderr.decode("utf-8", errors="replace")
    assert process.stdout == (
        "payload|unchanged" + "|original" * len(generated_names)
    ).encode("utf-8")


def test_split_variable_rejects_trailing_newline():
    with pytest.raises(ValueError, match="trailing newlines"):
        to_split_variable_reconstruction(
            "payload\n", random.Random(42), NamePool(random.Random(42)),
        )


def test_random_shred_can_force_split_variable(monkeypatch):
    rng = random.Random(42)
    monkeypatch.setattr(rng, "choice", lambda methods: "split-variable")
    expression = random_shred(
        "payload", rng, "no-eval", NamePool(random.Random(42)),
    )
    assert "; printf '%s'" in expression
    result = _evaluate(expression)
    assert result.returncode == 0
    assert result.stdout == b"payload"


def test_random_shred_excludes_split_without_pool_or_with_trailing_newline(monkeypatch):
    observed = []

    class InspectRandom(random.Random):
        def choice(self, sequence):
            observed.append(tuple(sequence))
            return sequence[0]

    random_shred("payload", InspectRandom(42), "no-eval", None)
    random_shred("payload\n", InspectRandom(42), "no-eval", NamePool(random.Random(42)))
    assert all("split-variable" not in methods for methods in observed)


def test_layer_forced_split_reports_stats_and_executes(monkeypatch):
    import obfush.layers.str_shred as module

    original = module.random_shred

    def force_split(value, rng, eval_mode, name_pool=None):
        if name_pool is None:
            return original(value, rng, eval_mode, name_pool)
        if "%" in value or "\\n" in value:
            return original(value, rng, eval_mode, name_pool)
        return to_split_variable_reconstruction(value, rng, name_pool)

    monkeypatch.setattr(module, "random_shred", force_split)
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
    monkeypatch.setattr(module, "random_shred", original)
    assert process.returncode == 0, process.stderr.decode("utf-8", errors="replace")
    assert process.stdout == b"secret payload\n"
    assert stats.split_reconstructions >= 1
    assert "secret payload" not in output
    assert "eval" not in output
    assert "base64" not in output
    assert "_shred_setup" not in output


def test_format_specifier_strings_use_inline_reconstruction_without_split_setup():
    source = "value='secret payload'\nprintf '%s\\n' \"$value\"\n"
    ast = normalize(parse_bash(source))
    config = LayerConfig(
        intensity=1.0,
        seed=42,
        rng=random.Random(42),
        eval_mode="no-eval",
        name_pool=NamePool(random.Random(42)),
    )
    transformed, _ = LayerImpl().transform(ast, config)
    output = emit(transformed)
    process = subprocess.run(
        ["bash"], input=output.encode("utf-8"), capture_output=True, timeout=10,
    )
    assert process.returncode == 0
    assert process.stdout == b"secret payload\n"
