"""Live decoy dependency and runtime behavior tests."""

import random
import re
import subprocess

import pytest

from obfush.engine.ast_emitter import emit
from obfush.layers.entropy_mask import DecoyGenerator
from obfush.layers.junk_inject import JunkCatalogue
from obfush.utils.live_chain import LiveChainGenerator
from obfush.utils.name_pool import NamePool


def _assert_chain_liveness(chain: dict) -> None:
    output = emit({"type": "script", "body": [chain]})
    for variable in chain["_synthetic_vars"]:
        assignment = re.search(rf"(?m)^{re.escape(variable)}=", output)
        reference = re.search(rf"\$(?:{re.escape(variable)}\b|\{{{re.escape(variable)}(?:\}}|[:/#]))", output)
        assert assignment, output
        assert reference, output
        assert reference.start() > assignment.start(), output
    for function in chain["_synthetic_functions"]:
        assert output.count(function) >= 2, output


def test_generated_live_chains_reference_every_synthetic_identifier():
    pool = NamePool(random.Random(7))
    generator = LiveChainGenerator(random.Random(42), pool)

    chains = [generator.generate() for _ in range(200)]
    chains.extend(generator.generate(f"message {index}") for index in range(50))

    for chain in chains:
        _assert_chain_liveness(chain)


def test_entropy_and_junk_generators_only_emit_atomic_live_chains():
    pool = NamePool(random.Random(11))
    entropy = DecoyGenerator(random.Random(12), pool)
    junk = JunkCatalogue(random.Random(13), 1.0, pool)

    generated = [entropy.generate() for _ in range(100)]
    generated.extend(junk.generate() for _ in range(100))

    assert all(node.get("_live_chain") for node in generated)
    for node in generated:
        _assert_chain_liveness(node)


def test_function_chain_is_defined_and_called():
    generator = LiveChainGenerator(
        random.Random(42), NamePool(random.Random(42)), marker="_junk",
    )

    chain = generator.generate_function_chain()
    output = emit({"type": "script", "body": [chain]})

    function = chain["_synthetic_functions"][0]
    assert f"{function}()" in output
    assert re.search(rf"(?m)^{re.escape(function)}$", output)
    _assert_chain_liveness(chain)


@pytest.mark.parametrize("strict_mode", ["", "set -eu\n"])
def test_live_chains_execute_silently_in_real_bash(strict_mode):
    generator = LiveChainGenerator(
        random.Random(42), NamePool(random.Random(42)), marker="_junk",
    )
    body = [generator.generate() for _ in range(30)]
    script = "#!/bin/bash\n" + strict_mode + emit({"type": "script", "body": body})

    process = subprocess.run(
        ["bash"], input=script.encode("utf-8"), capture_output=True, timeout=10,
    )

    assert process.returncode == 0, process.stderr.decode("utf-8", errors="replace")
    assert process.stdout == b""
    assert process.stderr == b""
