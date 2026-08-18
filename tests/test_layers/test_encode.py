"""Command encoding safety and runtime tests."""

import random
import subprocess

import pytest

from obfush.engine.ast_emitter import emit
from obfush.engine.ast_parser import parse_bash
from obfush.engine.normalizer import normalize
from obfush.layers.base import LayerConfig, LayerStats
from obfush.layers.encode import _encode_command, _is_subprocess_safe


def _command(source: str) -> dict:
    return normalize(parse_bash(source))["body"][0]


@pytest.mark.parametrize("source", [
    "printf hello",
    "echo hello",
    "curl https://example.invalid",
    "grep needle file.txt",
])
def test_literal_commands_are_subprocess_safe(source):
    command = _command(source)
    assert _is_subprocess_safe(command, source)


@pytest.mark.parametrize("source", [
    "cd /tmp",
    "export VALUE=changed",
    "source config.sh",
    "return 0",
    "worker_function argument",
    'printf "%s\\n" "$local_value"',
    "kill $$",
])
def test_shell_state_and_dynamic_commands_are_not_subprocess_safe(source):
    command = _command(source)
    assert not _is_subprocess_safe(command, source)


@pytest.mark.parametrize("mode", ["no-eval", "direct-exec"])
def test_unsafe_command_is_left_unchanged(mode):
    command = _command("cd /tmp")
    config = LayerConfig(1.0, 42, random.Random(42), mode)
    stats = LayerStats()

    result = _encode_command(command, config, stats)

    assert result is command
    assert stats.regions_encoded == 0
    assert stats.custom["subprocess_unsafe_skipped"] == "1"


@pytest.mark.parametrize("mode", ["ok", "no-eval", "direct-exec"])
@pytest.mark.parametrize("seed", range(6))
def test_encoded_literal_command_runs_in_real_bash(mode, seed):
    command = _command("printf encoded")
    config = LayerConfig(1.0, seed, random.Random(seed), mode)

    encoded = _encode_command(command, config, LayerStats())
    source = emit({"type": "script", "body": [encoded]})
    process = subprocess.run(
        ["bash"], input=source.encode("utf-8"), capture_output=True, timeout=10,
    )

    assert process.returncode == 0, process.stderr.decode("utf-8", errors="replace")
    assert process.stdout == b"encoded"
    assert process.stderr == b""
