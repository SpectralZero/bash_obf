"""Adversarial differential gate (corpus × mutation matrix).

Obfuscates each construct-corpus case and asserts the obfuscated script behaves
identically to the original (stdout + exit code) under the input-mutation matrix.
Divergences recorded in ``tests.differential.registry`` are tolerated as xfail;
everything else must be equivalent.

Runtime is bounded by default (core cases × {baseline, set -e} × one seed).  Set
``OBFUSH_FULL_DIFFERENTIAL=1`` for the full core-mutation matrix across seeds; the
exhaustive whole-corpus sweep lives in ``ci/differential_sweep.py``.
"""

from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from obfush.engine.core import EngineConfig, PolymorphicEngine  # noqa: E402
from tests.differential import (  # noqa: E402
    BASH,
    BASH_VERSION,
    CORE_MUTATIONS,
    compare,
    is_known,
    is_runnable,
    run,
    sample,
)

requires_bash = pytest.mark.skipif(BASH is None, reason="bash not available")

_FULL = bool(os.environ.get("OBFUSH_FULL_DIFFERENTIAL"))
_SEEDS = (1, 42, 1337) if _FULL else (1337,)
_MUTATIONS = (
    CORE_MUTATIONS if _FULL
    else tuple(m for m in CORE_MUTATIONS if m.name in ("baseline", "set_e"))
)
_CASES = sample(core_only=True)

_ORIG: dict[tuple[str, str], object] = {}


def _obfuscate(script: str, seed: int) -> str:
    cfg = EngineConfig(seed=seed, intensity=1.0, eval_mode="ok",
                       min_layers=4, verify=False)
    return PolymorphicEngine(cfg).run(script).output


def _orig(case, mut):
    key = (case.name, mut.name)
    if key not in _ORIG:
        _ORIG[key] = run(case.script, argv=mut.argv, stdin=mut.stdin,
                         prologue=mut.prologue)
    return _ORIG[key]


def _params():
    params = []
    for case in _CASES:
        if not is_runnable(case.side_effect, allow_file=True):
            continue
        if case.needs_bash and BASH_VERSION and BASH_VERSION < case.needs_bash:
            continue
        for mut in _MUTATIONS:
            params.append(pytest.param(case, mut, id=f"{case.name}@{mut.name}"))
    return params


@requires_bash
@pytest.mark.parametrize("case, mut", _params())
def test_obfuscation_preserves_behaviour(case, mut):
    original = _orig(case, mut)
    diverged = None
    for seed in _SEEDS:
        obf = _obfuscate(case.script, seed)
        out = run(obf, argv=mut.argv, stdin=mut.stdin, prologue=mut.prologue)
        diff = compare(original, out)
        if not diff.hard_ok:
            diverged = (seed, diff.detail)
            break

    known = is_known(case.name, mut.name, BASH_VERSION)
    if known:
        if diverged is None:
            pytest.skip(
                "known divergence no longer reproduces at "
                f"seeds={_SEEDS} — candidate for registry removal: {known.reason}"
            )
        pytest.xfail(known.reason)

    assert diverged is None, (
        f"{case.name} @ {mut.name} diverged at seed={diverged[0]}\n{diverged[1]}"
    )
