"""
Output normalization for equivalence checking.

Provides a single, canonical implementation of output normalization
used by both the CI equivalence checker and the engine verifier.
This prevents the two from drifting out of sync.

The class-tracking variant is the primary API — the bytes-only
wrappers are thin convenience methods for the verifier.
"""

from __future__ import annotations

import re


# ── Compiled patterns ────────────────────────────────────────────────

# Random temp suffixes: /tmp/tmp.XXXXXXXXXX
TMP_RANDOM_RE = re.compile(r"/tmp/tmp\.\w{6,12}")
# Epoch timestamps (10-digit, starting with 1[5-9])
TIMESTAMP_EPOCH_RE = re.compile(r"\b1[5-9]\d{8}\b")
# ISO-8601 timestamps
TIMESTAMP_ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}")
# Bash error-message paths (normalise script path, keep line number)
BASH_ERROR_PATH_RE = re.compile(
    r"((?:bash|sh): (?:line \d+: )?)/[^\s:]+(/[^\s:]*\.sh)"
)
# PID-containing /tmp/ paths
TMP_PID_RE = re.compile(r"/tmp/[a-zA-Z_]*\d{3,7}")
# Signal-delivery noise on stderr
SIGNAL_NOISE_RE = re.compile(
    r"^(Terminated|Killed|Hangup|Alarm clock|Broken pipe).*$",
    re.MULTILINE,
)
# Temp script paths in bash errors
TEMP_SCRIPT_RE = re.compile(r"/tmp/[^\s:]+\.sh")
# Excess blank lines left by noise stripping
EXCESS_NEWLINES_RE = re.compile(r"\n{3,}")


# ── Tracked normalization ────────────────────────────────────────────

class NormalizationResult:
    """Tracks which normalization classes fired during processing."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.classes_applied: list[str] = []

    def apply(self, name: str, pattern: re.Pattern, repl: str) -> None:
        new_text = pattern.sub(repl, self.text)
        if new_text != self.text:
            self.classes_applied.append(name)
            self.text = new_text


def normalize_output(raw: str) -> tuple[str, list[str]]:
    """Normalize output to remove inherent non-determinism.

    Returns (normalized_text, list_of_normalization_classes_applied).
    This is the canonical implementation — all callers should use this.
    """
    nr = NormalizationResult(raw)
    nr.apply("tmp_random_suffix", TMP_RANDOM_RE, "/tmp/tmp.NORM")
    nr.apply("epoch_timestamp", TIMESTAMP_EPOCH_RE, "EPOCH")
    nr.apply("iso_timestamp", TIMESTAMP_ISO_RE, "TIMESTAMP")
    nr.apply("bash_error_path", BASH_ERROR_PATH_RE, r"\1SCRIPT\2")
    nr.apply("tmp_pid_path", TMP_PID_RE, "/tmp/NORM_PID")
    return nr.text, nr.classes_applied


def normalize_stderr_text(raw: str) -> tuple[str, list[str]]:
    """More aggressive normalization for stderr.

    In addition to stdout normalization, strips signal-delivery
    noise and temp script paths in error messages.
    """
    nr = NormalizationResult(raw)
    nr.apply("tmp_random_suffix", TMP_RANDOM_RE, "/tmp/tmp.NORM")
    nr.apply("epoch_timestamp", TIMESTAMP_EPOCH_RE, "EPOCH")
    nr.apply("iso_timestamp", TIMESTAMP_ISO_RE, "TIMESTAMP")
    nr.apply("bash_error_path", BASH_ERROR_PATH_RE, r"\1SCRIPT\2")
    nr.apply("tmp_pid_path", TMP_PID_RE, "/tmp/NORM_PID")
    nr.apply("signal_noise", SIGNAL_NOISE_RE, "")
    nr.apply("temp_script_path", TEMP_SCRIPT_RE, "SCRIPT.sh")
    nr.apply("excess_newlines", EXCESS_NEWLINES_RE, "\n\n")
    return nr.text, nr.classes_applied


# ── Bytes-only convenience wrappers (for verifier) ───────────────────

def normalize_stdout(raw: bytes) -> bytes:
    """Bytes-in, bytes-out wrapper around normalize_output()."""
    text = raw.decode("utf-8", errors="replace")
    normalized, _ = normalize_output(text)
    return normalized.encode("utf-8")


def normalize_stderr(raw: bytes) -> bytes:
    """Bytes-in, bytes-out wrapper around normalize_stderr_text()."""
    text = raw.decode("utf-8", errors="replace")
    normalized, _ = normalize_stderr_text(text)
    return normalized.encode("utf-8")
