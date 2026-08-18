"""Static anti-regression analyzer tests."""

import random

from obfush.engine.ast_emitter import emit
from obfush.engine.core import EngineConfig, PolymorphicEngine
from obfush.engine.security_analyzer import analyze_source
from obfush.utils.live_chain import LiveChainGenerator
from obfush.utils.name_pool import NamePool


def test_detects_executable_tokens_and_legacy_fingerprints():
    source = """#!/bin/bash
_path_ab_1=/tmp
eval "$(printf payload)"
xxd -r -p input
"""
    analysis = analyze_source(source, original_size=20)
    assert analysis.standalone_eval_count == 1
    assert analysis.xxd_command_count == 1
    assert analysis.legacy_fingerprint_count >= 1
    assert analysis.source_size_ratio == len(source.encode("utf-8")) / 20
    assert analysis.introduced_eval_count is None


def test_baseline_distinguishes_source_authored_and_introduced_tokens():
    baseline = "eval source_payload\nxxd input\n_path_ab_1=value\n"
    output = baseline + "eval generated_payload\nxxd other\n_calc_cd_2=value\n"
    analysis = analyze_source(output, baseline_source=baseline)
    assert analysis.baseline_eval_count == 1
    assert analysis.introduced_eval_count == 1
    assert analysis.baseline_xxd_command_count == 1
    assert analysis.introduced_xxd_command_count == 1
    assert analysis.introduced_legacy_fingerprint_count == 1


def test_reports_conservative_liveness_candidates():
    source = """live=one
copy="${live}"
: "${copy}"
dead=two
called() { :; }
called
unused() { :; }
"""
    analysis = analyze_source(source)
    assert "dead" in analysis.assigned_never_read_candidates
    assert "live" not in analysis.assigned_never_read_candidates
    assert "copy" not in analysis.assigned_never_read_candidates
    assert "unused" in analysis.uncalled_function_candidates
    assert "called" not in analysis.uncalled_function_candidates
    assert analysis.limitations


def test_live_chain_has_no_dead_or_uncalled_synthetic_candidates():
    generator = LiveChainGenerator(
        random.Random(42), NamePool(random.Random(42)), marker="_junk",
    )
    chains = [generator.generate() for _ in range(30)]
    source = emit({"type": "script", "body": chains})
    analysis = analyze_source(source)
    assert analysis.assigned_never_read_candidates == []
    assert analysis.uncalled_function_candidates == []


def test_duplicate_literals_are_reported_without_claiming_origin():
    source = "a='repeated literal value'\nb='repeated literal value'\n"
    analysis = analyze_source(source)
    assert analysis.duplicate_literal_group_count == 1
    assert analysis.duplicate_literal_occurrences == 1
    assert analysis.duplicate_literal_examples == ["repeated literal value"]


def test_no_eval_output_has_no_eval_or_legacy_fingerprint():
    source = "#!/bin/bash\nvalue=hello\nprintf '%s\\n' \"$value\"\n"
    result = PolymorphicEngine(EngineConfig(
        seed=42,
        intensity=1.0,
        eval_mode="no-eval",
        max_size_ratio=3.0,
    )).run(source)
    analysis = analyze_source(
        result.output,
        original_size=len(source.encode("utf-8")),
        baseline_source=source,
    )
    assert analysis.standalone_eval_count == 0
    assert analysis.xxd_command_count == 0
    assert analysis.legacy_fingerprint_count == 0
    # Engine auto-scales ratio to 5.0x for small scripts (< 2KB)
    effective_ratio = max(3.0, 5.0 if len(source.encode("utf-8")) < 2048 else 3.0)
    assert analysis.source_size_ratio <= effective_ratio
    assert analysis.introduced_eval_count == 0
    assert analysis.introduced_xxd_command_count == 0


def test_structure_digest_tracks_ast_shape_not_literal_values():
    first = analyze_source("echo one\n")
    second = analyze_source("echo two\n")
    third = analyze_source("echo one\necho two\n")
    assert first.source_sha256 != second.source_sha256
    assert first.structure_sha256 == second.structure_sha256
    assert first.structure_sha256 != third.structure_sha256


def test_different_seeds_produce_multiple_structure_shapes():
    source = "#!/bin/bash\nvalue=hello\nprintf '%s\\n' \"$value\"\n"
    structure_hashes = {
        analyze_source(PolymorphicEngine(EngineConfig(
            seed=seed,
            intensity=0.8,
            max_size_ratio=3.0,
        )).run(source).output).structure_sha256
        for seed in range(10)
    }
    assert len(structure_hashes) >= 2


def test_analyzer_counts_wrapped_opaque_constants():
    analysis = analyze_source("sleep $((((42 ^ 7) ^ 7) + 0))\nexit $(((25 - 25) + 0))\n")
    assert analysis.opaque_constant_count == 2
