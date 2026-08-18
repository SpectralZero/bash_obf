"""Metadata and collision checks for split-variable reconstruction."""

import random

from obfush.engine.security_analyzer import analyze_source
from obfush.utils.name_pool import NamePool
from obfush.utils.string_utils import to_split_variable_reconstruction


def test_analyzer_counts_split_reconstructions():
    pool = NamePool(random.Random(42))
    first = to_split_variable_reconstruction("first payload", random.Random(42), pool)
    second = to_split_variable_reconstruction("second payload", random.Random(42), pool)
    analysis = analyze_source(f"printf '%s' {first}\nprintf '%s' {second}\n")
    assert analysis.split_reconstruction_count == 2


def test_split_names_are_unique_and_do_not_use_legacy_prefixes():
    pool = NamePool(random.Random(42))
    expressions = [
        to_split_variable_reconstruction(f"payload-{index}", random.Random(index), pool)
        for index in range(20)
    ]
    names = []
    for expression in expressions:
        setup = expression.split("$(", 1)[1].split("; printf", 1)[0]
        names.extend(part.split("=", 1)[0] for part in setup.split("; "))
    assert len(names) == len(set(names))
    analysis = analyze_source("\n".join(expressions))
    assert analysis.legacy_fingerprint_count == 0
