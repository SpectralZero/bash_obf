"""
Shannon entropy computation and statistical analysis utilities.

Used by the entropy_mask layer and the entropy_evaluator to measure
and control the entropy profile of obfuscated output.
"""

from __future__ import annotations

import math
from collections import Counter


def shannon_entropy(data: bytes) -> float:
    """Compute Shannon entropy in bits per byte.

    Normal bash scripts: ~4.2–4.5 bits/byte
    Base64 encoded data: ~5.8–6.0 bits/byte
    Random/encrypted:    ~7.9–8.0 bits/byte

    Args:
        data: Raw bytes to analyse.

    Returns:
        Entropy in bits per byte (0.0–8.0).
    """
    if not data:
        return 0.0

    length = len(data)
    counts = Counter(data)

    entropy = 0.0
    for count in counts.values():
        probability = count / length
        if probability > 0:
            entropy -= probability * math.log2(probability)

    return entropy


def windowed_entropy(
    data: bytes,
    window_size: int = 256,
    step: int | None = None,
) -> list[tuple[int, float]]:
    """Compute entropy over sliding windows.

    Used to detect high-entropy regions (encoded blobs) within
    an otherwise normal-looking script.

    Args:
        data:        Raw bytes to analyse.
        window_size: Window size in bytes.
        step:        Step size (defaults to window_size // 2 for overlap).

    Returns:
        List of (offset, entropy) tuples.
    """
    if step is None:
        step = max(1, window_size // 2)

    results: list[tuple[int, float]] = []
    for i in range(0, len(data) - window_size + 1, step):
        window = data[i : i + window_size]
        results.append((i, shannon_entropy(window)))

    return results


def entropy_in_range(
    entropy: float,
    target: float,
    tolerance: float = 0.5,
) -> bool:
    """Check if entropy is within tolerance of target.

    Args:
        entropy:   Measured entropy value.
        target:    Desired entropy (e.g. 4.5).
        tolerance: Acceptable deviation (±).

    Returns:
        True if abs(entropy - target) <= tolerance.
    """
    return abs(entropy - target) <= tolerance


def estimate_decoy_needed(
    current_data: bytes,
    target_entropy: float,
    decoy_entropy: float = 4.3,
) -> int:
    """Estimate how many bytes of decoy code are needed to hit entropy target.

    Uses the property that mixing high-entropy data with low-entropy
    decoy dilutes the overall entropy.

    This is an approximation — the actual relationship is non-linear,
    so the entropy_mask layer should measure and iterate.

    Args:
        current_data:   The current script content.
        target_entropy: Desired final entropy (bits/byte).
        decoy_entropy:  Expected entropy of decoy code (~4.3 for bash).

    Returns:
        Estimated bytes of decoy code to add.  Returns 0 if current
        entropy is already at or below target.
    """
    current_entropy = shannon_entropy(current_data)
    current_size = len(current_data)

    if current_entropy <= target_entropy:
        return 0

    # Weighted average model:
    # target = (current_entropy * current_size + decoy_entropy * decoy_size)
    #          / (current_size + decoy_size)
    #
    # Solving for decoy_size:
    # target * (current_size + decoy_size) = current_entropy * current_size
    #                                        + decoy_entropy * decoy_size
    # target * decoy_size - decoy_entropy * decoy_size
    #     = current_entropy * current_size - target * current_size
    # decoy_size * (target - decoy_entropy)
    #     = current_size * (current_entropy - target)
    # decoy_size = current_size * (current_entropy - target)
    #              / (target - decoy_entropy)

    denominator = target_entropy - decoy_entropy
    if denominator >= 0:
        # Can't dilute — decoy has same or higher entropy than target
        # This shouldn't happen with realistic values
        return current_size * 5  # generous fallback

    decoy_size = current_size * (current_entropy - target_entropy) / abs(denominator)
    return max(0, int(decoy_size * 1.2))  # 20% margin


def format_entropy_report(
    data: bytes,
    target: float = 4.5,
    window_size: int = 256,
) -> str:
    """Generate a human-readable entropy analysis report.

    Args:
        data:        Script content to analyse.
        target:      Target entropy.
        window_size: Window size for sliding analysis.

    Returns:
        Formatted report string.
    """
    overall = shannon_entropy(data)
    windows = windowed_entropy(data, window_size)

    max_entropy = max((e for _, e in windows), default=0.0)
    min_entropy = min((e for _, e in windows), default=0.0)
    avg_entropy = sum(e for _, e in windows) / len(windows) if windows else 0.0

    high_regions = [(off, e) for off, e in windows if e > 5.5]

    in_target = entropy_in_range(overall, target)

    lines = [
        f"═══ Entropy Analysis ═══",
        f"Overall:     {overall:.3f} bits/byte",
        f"Target:      {target:.3f} ± 0.5",
        f"Status:      {'✓ IN RANGE' if in_target else '✗ OUT OF RANGE'}",
        f"",
        f"Window analysis ({window_size} byte windows):",
        f"  Min:       {min_entropy:.3f}",
        f"  Max:       {max_entropy:.3f}",
        f"  Average:   {avg_entropy:.3f}",
        f"  Windows:   {len(windows)}",
        f"  High (>5.5): {len(high_regions)}",
    ]

    if high_regions:
        lines.append(f"")
        lines.append(f"High-entropy regions:")
        for offset, ent in high_regions[:10]:
            lines.append(f"  offset {offset:6d}: {ent:.3f} bits/byte")
        if len(high_regions) > 10:
            lines.append(f"  ... and {len(high_regions) - 10} more")

    return "\n".join(lines)
