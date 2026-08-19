"""Bash execution + stream canonicalisation for differential testing.

Executes a script (with an optional prologue, injected positional parameters,
and stdin) in real bash and returns captured stdout/stderr/exit.

Portability note (Windows/WSL):
    The WSL ``bash.exe`` interpreter does *not* translate a Windows path passed
    as an argument (the backslashes are eaten as escapes), so we execute with the
    process ``cwd`` set to the script's directory and pass only the *basename*.
    Positional parameters are injected via ``set --`` inside the script rather
    than through the OS argv, so exotic arguments (spaces, newlines, unicode,
    glob metacharacters) never traverse the fragile Windows→WSL argv boundary.
    stdin is delivered as a raw byte pipe, which WSL passes through unchanged.

Stream comparison de-locates bash diagnostics: obfuscation legitimately shifts
line numbers and the script's file name, so byte-exact stderr is impossible — a
de-located signature is the correct adversarial comparison (it still catches an
error appearing/disappearing or changing class between original and obfuscated).
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from typing import Sequence

from obfush.engine.normalize import normalize_output, normalize_stderr_text

# ── Bash discovery ───────────────────────────────────────────────────

def find_bash() -> str | None:
    """Locate a bash interpreter, mirroring the regression-suite heuristic."""
    found = shutil.which("bash")
    if found:
        return found
    for candidate in (
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Windows\System32\bash.exe",
        "/bin/bash",
        "/usr/bin/bash",
        "/usr/local/bin/bash",
    ):
        if os.path.isfile(candidate):
            return candidate
    return None


BASH = find_bash()


@lru_cache(maxsize=8)
def detect_bash_version(bash: str | None = None) -> tuple[int, ...] | None:
    """Return ``BASH_VERSINFO`` as a tuple, e.g. ``(5, 2)``.  ``None`` if unknown."""
    bash = bash or BASH
    if bash is None:
        return None
    try:
        proc = subprocess.run(
            [bash, "-c", 'printf "%s %s %s" "${BASH_VERSINFO[0]}" '
                         '"${BASH_VERSINFO[1]}" "${BASH_VERSINFO[2]}"'],
            capture_output=True,
            timeout=15,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    parts = proc.stdout.strip().split()
    try:
        return tuple(int(p) for p in parts if p != "")
    except ValueError:
        return None


BASH_VERSION = detect_bash_version(BASH)


# ── Execution ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Outcome:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False


def _argv_prologue(argv: Sequence[str]) -> str:
    """Render ``set -- ...`` so positional params are injected inside the script."""
    if not argv:
        return ""
    return "set -- " + " ".join(shlex.quote(a) for a in argv)


def run(
    script: str,
    argv: Sequence[str] = (),
    stdin: str = "",
    prologue: str = "",
    timeout: float = 20.0,
    bash: str | None = None,
) -> Outcome:
    """Execute ``script`` in bash and capture its streams.

    ``prologue`` (``set``-flags / ``export`` / ``IFS``) and ``argv`` (rendered as
    ``set --``) are injected verbatim ahead of the script, identically for the
    original and obfuscated variants.
    """
    bash = bash or BASH
    if bash is None:  # pragma: no cover - guarded by requires_bash at call sites
        raise RuntimeError("bash interpreter not available")

    pieces = [p for p in (_argv_prologue(argv), prologue.rstrip("\n"), script) if p]
    full = "\n".join(pieces)

    workdir = tempfile.mkdtemp(prefix="obfush_diff_")
    script_path = os.path.join(workdir, "case.sh")
    try:
        with open(script_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(full if full.endswith("\n") else full + "\n")
        try:
            proc = subprocess.run(
                [bash, "case.sh"],
                input=stdin.encode("utf-8"),
                capture_output=True,
                timeout=timeout,
                cwd=workdir,
                env={**os.environ, "LC_ALL": "C"},
            )
        except subprocess.TimeoutExpired:
            return Outcome("", "TIMEOUT", -1, timed_out=True)
        return Outcome(
            proc.stdout.decode("utf-8", "replace"),
            proc.stderr.decode("utf-8", "replace"),
            proc.returncode,
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ── Stream canonicalisation ──────────────────────────────────────────

# "prefix: line N: " (path/interpreter-agnostic; non-greedy up to first match)
_LOCATED_RE = re.compile(r"(?m)^.*?: line \d+: ")
# "something.sh: " leading a diagnostic line (syntax errors, etc.)
_SCRIPTNAME_RE = re.compile(r"(?m)^.*?\.sh: ")
# bare interpreter prefix
_BASH_PREFIX_RE = re.compile(r"(?m)^bash: ")
# residual line-number tokens embedded elsewhere
_INLINE_LINE_RE = re.compile(r"line \d+")
_TRAIL_WS_RE = re.compile(r"[ \t]+$", re.MULTILINE)


def canon_stdout(raw: str) -> str:
    """Canonical stdout: strip inherent non-determinism only."""
    text, _ = normalize_output(raw)
    return _TRAIL_WS_RE.sub("", text)


def canon_stderr(raw: str) -> str:
    """Canonical, de-located stderr signature for comparison."""
    text, _ = normalize_stderr_text(raw)
    text = _LOCATED_RE.sub("", text)
    text = _SCRIPTNAME_RE.sub("", text)
    text = _BASH_PREFIX_RE.sub("", text)
    text = _INLINE_LINE_RE.sub("line N", text)
    text = _TRAIL_WS_RE.sub("", text)
    return text.strip()


@dataclass(frozen=True)
class StreamDiff:
    stdout_match: bool
    exit_match: bool
    stderr_match: bool
    detail: str

    @property
    def hard_ok(self) -> bool:
        """Hard gate: stdout + exit code must match."""
        return self.stdout_match and self.exit_match

    @property
    def strict_ok(self) -> bool:
        """Strict gate: also require the de-located stderr signature to match."""
        return self.stdout_match and self.exit_match and self.stderr_match


def compare(original: Outcome, obfuscated: Outcome) -> StreamDiff:
    o_out, b_out = canon_stdout(original.stdout), canon_stdout(obfuscated.stdout)
    o_err, b_err = canon_stderr(original.stderr), canon_stderr(obfuscated.stderr)
    stdout_match = o_out == b_out
    exit_match = original.exit_code == obfuscated.exit_code
    stderr_match = o_err == b_err

    detail = ""
    if not stdout_match:
        import difflib
        diff = difflib.unified_diff(
            o_out.splitlines(keepends=True),
            b_out.splitlines(keepends=True),
            fromfile="original.stdout",
            tofile="obfuscated.stdout",
            n=2,
        )
        detail += "STDOUT DIFF:\n" + "".join(diff)[:1500]
    if not exit_match:
        detail += (
            f"\nEXIT: original={original.exit_code} "
            f"obfuscated={obfuscated.exit_code}"
        )
    if not stderr_match:
        detail += (
            f"\nSTDERR(orig)={o_err[:400]!r}\nSTDERR(obf)={b_err[:400]!r}"
        )
    if original.timed_out or obfuscated.timed_out:
        detail += (
            f"\nTIMEOUT: original={original.timed_out} "
            f"obfuscated={obfuscated.timed_out}"
        )
    return StreamDiff(stdout_match, exit_match, stderr_match, detail.strip())
