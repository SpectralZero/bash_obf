"""Entropy evaluator tests."""

from obfush.engine.entropy_evaluator import EntropyEvaluator


def test_evaluate_empty_data():
    result = EntropyEvaluator(target=4.5, window_size=16).evaluate(b"")
    assert result["overall_entropy"] == 0.0
    assert result["window_count"] == 0
    assert result["avg_window_entropy"] == 0.0
    assert result["high_entropy_regions"] == 0


def test_evaluate_high_entropy_data():
    data = bytes(range(256)) * 4
    result = EntropyEvaluator(target=4.5, window_size=256).evaluate(data)
    assert result["overall_entropy"] == 8.0
    assert not result["in_range"]
    assert result["window_count"] == 7
    assert result["high_entropy_regions"] == 7
    assert result["estimated_decoy_needed"] > 0


def test_report_is_formatted_string():
    report = EntropyEvaluator(target=4.5, window_size=32).report(b"echo hello\n" * 30)
    assert isinstance(report, str)
    assert "Entropy Analysis" in report
