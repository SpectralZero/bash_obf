"""
Entropy evaluator — measures and reports on the entropy profile of output.

Used post-transformation to verify the entropy target is met and to
produce reports for the verbose CLI output.
"""

from __future__ import annotations

from obfush.utils.entropy_utils import (
    shannon_entropy,
    windowed_entropy,
    entropy_in_range,
    estimate_decoy_needed,
    format_entropy_report,
)


class EntropyEvaluator:
    """Evaluates entropy characteristics of obfuscated output.

    Compares final script entropy against a configurable target
    and reports per-window distribution for debugging.
    """

    def __init__(self, target: float = 4.5, window_size: int = 256) -> None:
        self.target = target
        self.window_size = window_size

    def evaluate(self, data: bytes) -> dict:
        """Full entropy evaluation.

        Args:
            data: Obfuscated script content.

        Returns:
            Dict with overall entropy, windowed analysis, and verdict.
        """
        overall = shannon_entropy(data)
        windows = windowed_entropy(data, self.window_size)
        in_range = entropy_in_range(overall, self.target)

        high_regions = [(off, e) for off, e in windows if e > 5.5]
        avg_window = sum(e for _, e in windows) / len(windows) if windows else 0.0

        return {
            "overall_entropy": overall,
            "target": self.target,
            "in_range": in_range,
            "window_count": len(windows),
            "avg_window_entropy": avg_window,
            "high_entropy_regions": len(high_regions),
            "estimated_decoy_needed": estimate_decoy_needed(
                data, self.target
            ) if not in_range else 0,
        }

    def report(self, data: bytes) -> str:
        """Generate formatted entropy report.

        Args:
            data: Obfuscated script content.

        Returns:
            Human-readable report string.
        """
        return format_entropy_report(data, self.target, self.window_size)
