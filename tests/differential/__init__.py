"""Adversarial differential-testing backbone for obfush.

This package is *test support code*, not shipped in the ``obfush`` wheel and
not subject to the coverage gate (``coverage.source = ["obfush"]``).

The goal is to refute equivalence, never to "prove" it: a large, deterministic,
combinatorial construct corpus is executed under an orthogonal input-mutation
matrix, and the original vs. obfuscated behaviour is compared on
stdout + stderr + exit code.  Anything that survives this is far more trustworthy
than a fixed-input, stdout-only check.

Modules
-------
bashrt          Bash discovery, version detection, execution + stream canonicalisation.
classification  Side-effect taxonomy (pure/file-only/networked/dangerous) + safety gate.
mutations       Input-mutation matrix (argv / stdin / env / IFS / LANG / HOME / set flags).
corpus          Deterministic, pure-by-construction combinatorial construct corpus.
registry        Known-divergence registry (xfail-style: reason + owner + optional bash bound).
"""

from __future__ import annotations

from .bashrt import (
    BASH,
    BASH_VERSION,
    Outcome,
    StreamDiff,
    canon_stderr,
    canon_stdout,
    compare,
    detect_bash_version,
    find_bash,
    run,
)
from .classification import SideEffect, classify, is_runnable
from .corpus import Case, generate, sample
from .mutations import CORE_MUTATIONS, FULL_MUTATIONS, Mutation
from .registry import KNOWN, KnownDivergence, is_known, root_cause_index

__all__ = [
    "BASH",
    "BASH_VERSION",
    "Outcome",
    "StreamDiff",
    "canon_stderr",
    "canon_stdout",
    "compare",
    "detect_bash_version",
    "find_bash",
    "run",
    "SideEffect",
    "classify",
    "is_runnable",
    "Case",
    "generate",
    "sample",
    "CORE_MUTATIONS",
    "FULL_MUTATIONS",
    "Mutation",
    "KNOWN",
    "KnownDivergence",
    "is_known",
    "root_cause_index",
]
