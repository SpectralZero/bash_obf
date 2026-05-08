"""Tests for the procedural DecoyCorpus and output normalizer."""

import random
import pytest


class TestDecoyCorpus:
    """Verify the procedural corpus meets anti-clustering requirements."""

    def test_reproducibility_same_seed(self):
        """Same seed -> identical comment sequence."""
        from obfush.utils.decoy_corpus import DecoyCorpus

        rng1 = random.Random(42)
        rng2 = random.Random(42)
        c1 = DecoyCorpus(rng1)
        c2 = DecoyCorpus(rng2)

        comments1 = [c1.generate_comment() for _ in range(50)]
        comments2 = [c2.generate_comment() for _ in range(50)]
        assert comments1 == comments2, "Same seed must produce identical comments"

    def test_different_seeds_low_overlap(self):
        """Different seeds share < 10% of decoy comments.

        This is the actual operational threat model: an analyst
        comparing obfuscated artifacts across runs should not be
        able to cluster them by shared decoy strings.
        """
        from obfush.utils.decoy_corpus import DecoyCorpus

        n_comments = 50
        runs: list[set[str]] = []

        for seed in range(100):
            rng = random.Random(seed)
            corpus = DecoyCorpus(rng)
            comments = {corpus.generate_comment() for _ in range(n_comments)}
            runs.append(comments)

        # Check pairwise overlap between all consecutive pairs
        max_overlap = 0.0
        for i in range(len(runs) - 1):
            overlap = len(runs[i] & runs[i + 1]) / n_comments
            if overlap > max_overlap:
                max_overlap = overlap

        assert max_overlap < 0.10, (
            f"Max pairwise overlap was {max_overlap:.1%}, expected < 10%"
        )

    def test_inline_comment_formats(self):
        """Inline comments should start with # prefix patterns."""
        from obfush.utils.decoy_corpus import DecoyCorpus

        rng = random.Random(99)
        corpus = DecoyCorpus(rng)
        comments = [corpus.generate_inline_comment() for _ in range(100)]

        # All should start with #
        for c in comments:
            assert c.startswith("#"), f"Inline comment missing # prefix: {c!r}"

    def test_log_messages_have_level(self):
        """Log messages should contain a bracketed level."""
        from obfush.utils.decoy_corpus import DecoyCorpus

        rng = random.Random(7)
        corpus = DecoyCorpus(rng)
        for _ in range(50):
            msg = corpus.generate_log_message()
            assert msg.startswith("["), f"Log message missing level: {msg!r}"
            assert "]" in msg, f"Log message unclosed bracket: {msg!r}"


class TestNormalize:
    """Verify the canonical normalization module.

    All imports go through obfush.engine.normalize -- the single
    source of truth shared by the CI checker and the verifier.
    """

    def test_normalizes_tmp_pid_paths(self):
        """PID-containing /tmp/ paths should be normalized."""
        from obfush.engine.normalize import normalize_output

        text = "wrote to /tmp/obf_stress_12345 and /tmp/config_67890.json"
        norm, classes = normalize_output(text)
        assert "12345" not in norm
        assert "67890" not in norm
        assert "tmp_pid_path" in classes

    def test_normalizes_epoch_timestamps(self):
        from obfush.engine.normalize import normalize_output

        text = "started at 1715000000 ended at 1715003600"
        norm, classes = normalize_output(text)
        assert "1715000000" not in norm
        assert "epoch_timestamp" in classes

    def test_normalizes_iso_timestamps(self):
        from obfush.engine.normalize import normalize_output

        text = "log: 2024-11-15T10:30:00 event occurred"
        norm, classes = normalize_output(text)
        assert "2024-11-15T10:30:00" not in norm
        assert "iso_timestamp" in classes

    def test_normalizes_random_tmp_suffixes(self):
        from obfush.engine.normalize import normalize_output

        text = "tmpfile at /tmp/tmp.abcXYZ1234"
        norm, classes = normalize_output(text)
        assert "abcXYZ1234" not in norm
        assert "tmp_random_suffix" in classes

    def test_preserves_real_differences(self):
        """NEGATIVE TEST: normalizer must NOT equalize genuinely
        different outputs.  Without this, over-normalization passes
        silently and false-equivalence becomes a hidden bug class.
        """
        from obfush.engine.normalize import normalize_output

        original = "[PASS] function with arg\n[PASS] recursive function\nPassed: 5\nFailed: 0\n"
        broken   = "[PASS] function with arg\n[FAIL] recursive function\nPassed: 4\nFailed: 1\n"

        norm_orig, _ = normalize_output(original)
        norm_broken, _ = normalize_output(broken)

        assert norm_orig != norm_broken, (
            "Normalizer equalized genuinely different outputs -- "
            "this means false-equivalence bugs will hide"
        )

    def test_normalization_classes_empty_when_clean(self):
        """Clean output should trigger zero normalization classes."""
        from obfush.engine.normalize import normalize_output

        clean = "[PASS] basic test\nPassed: 1\nFailed: 0\n"
        norm, classes = normalize_output(clean)
        assert norm == clean, "Clean output should not be modified"
        assert classes == [], f"Expected no classes, got {classes}"

    def test_normalize_stdout_bytes(self):
        """Bytes-only wrapper round-trips correctly."""
        from obfush.engine.normalize import normalize_stdout

        raw = b"output at /tmp/test_54321\n"
        norm = normalize_stdout(raw)
        assert b"54321" not in norm

    def test_normalize_stderr_signal_noise(self):
        """Signal-delivery noise should be stripped from stderr."""
        from obfush.engine.normalize import normalize_stderr

        raw = b"Terminated\nreal error here\nKilled\n"
        norm = normalize_stderr(raw)
        text = norm.decode("utf-8")
        assert "Terminated" not in text
        assert "Killed" not in text
        assert "real error here" in text

    def test_normalize_preserves_real_stderr_diff(self):
        """Negative test: normalizer should NOT hide real errors."""
        from obfush.engine.normalize import normalize_stderr

        orig = b"syntax error near unexpected token\n"
        broken = b"command not found: foobar\n"
        assert normalize_stderr(orig) != normalize_stderr(broken)
