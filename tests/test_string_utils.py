"""String encoding primitive tests using a real Bash runtime."""

import random
import subprocess

import pytest

from obfush.utils.string_utils import (
    random_shred,
    to_arithmetic_printf_simple,
    to_base64_decode,
    to_fragmented_concat,
    to_hex_escape,
    to_octal_escape,
)


def _evaluate(expression: str) -> bytes:
    process = subprocess.run(
        ["bash"],
        input=f"printf '%s' {expression}\n".encode("utf-8"),
        capture_output=True,
        timeout=10,
    )
    assert process.returncode == 0, process.stderr.decode("utf-8", errors="replace")
    assert process.stderr == b""
    return process.stdout


@pytest.mark.parametrize("value", [
    "Hello world",
    "quotes ' \" and slash \\",
    "line one\nline two",
    "dollar $ and backtick ` stay literal",
    "",
])
@pytest.mark.parametrize("encoder", [to_hex_escape, to_octal_escape, to_arithmetic_printf_simple, to_base64_decode])
def test_string_encoders_round_trip_in_real_bash(value, encoder):
    assert _evaluate(encoder(value)) == value.encode("utf-8")


@pytest.mark.parametrize("seed", range(20))
def test_fragmented_concat_round_trips_across_seeds(seed):
    value = "quotes ' \" $ ` slash \\ and spaces"
    assert _evaluate(to_fragmented_concat(value, random.Random(seed))) == value.encode("utf-8")


@pytest.mark.parametrize("mode", ["ok", "no-eval", "direct-exec"])
@pytest.mark.parametrize("seed", range(20))
def test_random_shred_round_trips_all_active_methods(mode, seed):
    value = "payload with spaces"
    expression = random_shred(value, random.Random(seed), mode)
    assert isinstance(expression, str)
    assert _evaluate(expression) == value.encode("utf-8")


def test_no_eval_modes_never_select_base64():
    for mode in ("no-eval", "direct-exec"):
        for seed in range(100):
            assert "base64" not in random_shred("payload", random.Random(seed), mode)


def test_random_shred_with_name_pool_preserves_output_across_seeds():
    from obfush.utils.name_pool import NamePool

    for seed in range(100):
        expression = random_shred(
            "payload with spaces",
            random.Random(seed),
            "no-eval",
            NamePool(random.Random(seed)),
        )
        assert _evaluate(expression) == b"payload with spaces"


def test_random_shred_with_name_pool_covers_xor_method():
    from obfush.utils.name_pool import NamePool

    seen_xor = False
    for seed in range(500):
        expression = random_shred(
            "payload",
            random.Random(seed),
            "no-eval",
            NamePool(random.Random(seed)),
        )
        if "printf -v" in expression:
            seen_xor = True
            assert _evaluate(expression) == b"payload"
            break
    assert seen_xor
