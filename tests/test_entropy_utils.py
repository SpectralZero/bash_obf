"""Entropy utility and configuration tests."""

import random

import pytest

from obfush.engine.core import EngineConfig
from obfush.layers.base import LayerConfig
from obfush.layers.entropy_mask import LayerImpl
from obfush.utils.entropy_utils import (
    entropy_in_range,
    estimate_decoy_needed,
    format_entropy_report,
    shannon_entropy,
    windowed_entropy,
)


def test_shannon_entropy_edge_cases():
    assert shannon_entropy(b"") == 0.0
    assert shannon_entropy(b"a" * 100) == 0.0
    assert shannon_entropy(bytes(range(256))) == pytest.approx(8.0)


def test_windowed_entropy_uses_overlap_and_explicit_step():
    data = bytes(range(64)) * 8
    assert [offset for offset, _ in windowed_entropy(data, 128)] == [0, 64, 128, 192, 256, 320, 384]
    assert [offset for offset, _ in windowed_entropy(data, 128, 128)] == [0, 128, 256, 384]


def test_entropy_range_is_inclusive():
    assert entropy_in_range(4.0, 4.5, 0.5)
    assert entropy_in_range(5.0, 4.5, 0.5)
    assert not entropy_in_range(5.01, 4.5, 0.5)


def test_decoy_estimate_uses_weighted_average_formula():
    data = bytes(range(256)) * 4
    current_entropy = shannon_entropy(data)
    expected = int(
        len(data) * (current_entropy - 6.0) / (6.0 - 4.3) * 1.2
    )

    assert estimate_decoy_needed(data, 6.0) == expected
    assert estimate_decoy_needed(data, 8.0) == 0


def test_decoy_estimate_handles_impossible_target():
    data = bytes(range(256))
    assert estimate_decoy_needed(data, 4.0, decoy_entropy=4.3) == len(data) * 5


def test_entropy_report_contains_measured_summary():
    report = format_entropy_report(b"echo hello\n" * 100, target=4.5, window_size=64)
    assert "Entropy Analysis" in report
    assert "Overall:" in report
    assert "Target:      4.500" in report


@pytest.mark.parametrize("target", [-0.1, 8.1])
def test_entropy_target_validation(target):
    with pytest.raises(ValueError, match="entropy_target"):
        EngineConfig(entropy_target=target)
    with pytest.raises(ValueError, match="entropy_target"):
        LayerConfig(0.5, 42, random.Random(42), entropy_target=target)


def test_entropy_mask_uses_configured_target(monkeypatch):
    captured = {}

    def estimate(data, target):
        captured["target"] = target
        return 0

    monkeypatch.setattr("obfush.layers.entropy_mask.estimate_decoy_needed", estimate)
    ast = {
        "type": "script",
        "body": [{
            "type": "command",
            "parts": [{"type": "word", "value": "echo", "pos": None}],
        }],
    }
    config = LayerConfig(
        0.8, 42, random.Random(42), entropy_target=5.25,
    )

    LayerImpl().transform(ast, config)

    assert captured["target"] == 5.25
