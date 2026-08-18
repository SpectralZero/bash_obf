"""Shared identifier pool tests."""

import random

from obfush.engine.core import EngineConfig, PolymorphicEngine
from obfush.utils.name_pool import NamePool


def test_name_pool_is_deterministic_unique_and_collision_free():
    first = NamePool(random.Random(42))
    second = NamePool(random.Random(42))
    first.register_existing({"_fd", "_tmp", "_v1"})
    second.register_existing({"_fd", "_tmp", "_v1"})

    names_a = [first.next_name() for _ in range(500)]
    names_b = [second.next_name() for _ in range(500)]

    assert names_a == names_b
    assert len(names_a) == len(set(names_a))
    assert not {"_fd", "_tmp", "_v1"}.intersection(names_a)
    assert all(name.isidentifier() for name in names_a)


def test_engine_uses_shared_name_pool_without_legacy_decoy_prefixes():
    source = "#!/bin/bash\nvalue=one\nprintf '%s\\n' \"$value\"\n"
    result = PolymorphicEngine(
        EngineConfig(
            seed=7,
            intensity=1.0,
            force_layers=["id-mangle", "junk-inject", "entropy-mask"],
            min_layers=1,
            max_size_ratio=100.0,
        )
    ).run(source)

    assert "_jnk_" not in result.output
    assert "_fn_" not in result.output
    assert "_path_" not in result.output
    assert "_calc_" not in result.output
    assert "_ifaces_" not in result.output
