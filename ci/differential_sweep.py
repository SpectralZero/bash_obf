#!/usr/bin/env python3
"""Adversarial differential sweep for obfush.

Runs the combinatorial construct corpus through the obfuscator across seeds and
eval-modes, then executes the original vs. obfuscated variants under the input-
mutation matrix, comparing stdout + de-located stderr + exit code.

This is the "refute equivalence" engine described in the roadmap: it is designed
to *find* faithfulness bugs that a fixed-input, stdout-only check cannot.

Usage
-----
    python ci/differential_sweep.py [options]

    --full                 use the whole corpus + full mutation matrix
                           (default: the core subset)
    --seeds 1,42,1337      obfuscation seeds (default: 1,42,1337)
    --eval-modes ok        comma list of ok|no-eval|direct-exec (default: ok)
    --intensity 1.0        obfuscation intensity (default: 1.0)
    --tier all             faithful|strict|all (default: all)
    --allow-file           run FILE_ONLY cases too (default: on)
    --self-check           only verify the corpus is deterministic at baseline
    --max N                cap number of cases (debug)

Exit code 0 iff every non-registered (case, mutation, seed) pair is equivalent.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from obfush.engine.core import EngineConfig, PolymorphicEngine  # noqa: E402
from tests.differential import (  # noqa: E402
    CORE_MUTATIONS,
    FULL_MUTATIONS,
    canon_stderr,
    canon_stdout,
    compare,
    generate,
    is_known,
    is_runnable,
    run,
    sample,
)
from tests.differential.bashrt import BASH, BASH_VERSION  # noqa: E402


def obfuscate(script: str, seed: int, eval_mode: str, intensity: float) -> str:
    cfg = EngineConfig(
        seed=seed, intensity=intensity, eval_mode=eval_mode,
        min_layers=4, verify=False,
    )
    return PolymorphicEngine(cfg).run(script).output


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="obfush adversarial differential sweep")
    p.add_argument("--full", action="store_true")
    p.add_argument("--seeds", default="1,42,1337")
    p.add_argument("--eval-modes", default="ok")
    p.add_argument("--intensity", type=float, default=1.0)
    p.add_argument("--tier", choices=["faithful", "strict", "all"], default="all")
    p.add_argument("--allow-file", action="store_true", default=True)
    p.add_argument("--no-allow-file", dest="allow_file", action="store_false")
    p.add_argument("--self-check", action="store_true")
    p.add_argument("--max", type=int, default=0)
    return p.parse_args(argv)


def select_cases(full: bool, cap: int, allow_file: bool):
    cases = generate() if full else sample(core_only=True)
    runnable = []
    for c in cases:
        if not is_runnable(c.side_effect, allow_file=allow_file):
            continue
        if c.needs_bash and BASH_VERSION and BASH_VERSION < c.needs_bash:
            continue
        runnable.append(c)
    if cap:
        runnable = runnable[:cap]
    return runnable


def select_mutations(full: bool, tier: str):
    muts = FULL_MUTATIONS if full else CORE_MUTATIONS
    if tier != "all":
        muts = tuple(m for m in muts if m.tier == tier)
    return muts


def self_check(cases) -> int:
    """Verify each original case is deterministic and (ideally) succeeds at baseline.

    Determinism is judged on *canonicalised* streams — the same basis the sweep
    uses — so inherent, benign non-determinism (mktemp paths, PIDs) does not count
    as a corpus defect.
    """
    problems = 0
    for c in cases:
        a = run(c.script)
        b = run(c.script)
        sig_a = (canon_stdout(a.stdout), canon_stderr(a.stderr), a.exit_code)
        sig_b = (canon_stdout(b.stdout), canon_stderr(b.stderr), b.exit_code)
        if sig_a != sig_b:
            problems += 1
            print(f"  [NONDET] {c.name}: baseline output not reproducible")
            print(f"           rc {a.exit_code}/{b.exit_code}")
        elif a.exit_code != 0:
            print(f"  [note ] {c.name}: baseline exit={a.exit_code} "
                  f"stderr={canon_stderr(a.stderr)[:120]!r}")
    total = len(cases)
    ok = total - problems
    print(f"\n  self-check: {ok}/{total} cases deterministic at baseline")
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if BASH is None:
        print("bash not available; cannot run differential sweep", file=sys.stderr)
        return 2

    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    eval_modes = [m.strip() for m in args.eval_modes.split(",") if m.strip()]
    cases = select_cases(args.full, args.max, args.allow_file)
    mutations = select_mutations(args.full, args.tier)

    ver = ".".join(map(str, BASH_VERSION)) if BASH_VERSION else "unknown"
    print("+" + "-" * 62 + "+")
    print(f"|  obfush differential sweep   bash={ver:<10} cases={len(cases):<4}"
          f" muts={len(mutations):<3}      |")
    print(f"|  seeds={seeds}  eval={eval_modes}  intensity={args.intensity}"
          f"  tier={args.tier}".ljust(63) + "|")
    print("+" + "-" * 62 + "+\n")

    if args.self_check:
        return self_check(cases)

    # Pre-compute original outcomes once per (case, mutation) — reused across seeds.
    t0 = time.perf_counter()
    orig_cache: dict[tuple[str, str], object] = {}
    for c in cases:
        for m in mutations:
            orig_cache[(c.name, m.name)] = run(
                c.script, argv=m.argv, stdin=m.stdin, prologue=m.prologue,
            )

    divergences: list[dict] = []
    registered: list[dict] = []
    advisory: list[dict] = []       # stdout+exit agree but stderr signature differs
    engine_errors: list[dict] = []
    checks = 0

    for c in cases:
        for seed in seeds:
            for mode in eval_modes:
                try:
                    obf = obfuscate(c.script, seed, mode, args.intensity)
                except Exception as e:  # noqa: BLE001
                    engine_errors.append({"case": c.name, "seed": seed,
                                          "eval_mode": mode, "error": str(e)})
                    continue
                for m in mutations:
                    checks += 1
                    original = orig_cache[(c.name, m.name)]
                    obf_out = run(obf, argv=m.argv, stdin=m.stdin, prologue=m.prologue)
                    diff = compare(original, obf_out)
                    rec = {
                        "case": c.name, "mutation": m.name, "tier": m.tier,
                        "seed": seed, "eval_mode": mode,
                        "stdout_match": diff.stdout_match,
                        "exit_match": diff.exit_match,
                        "stderr_match": diff.stderr_match,
                        "detail": diff.detail,
                    }
                    # Hard gate: stdout + exit code.  stderr is advisory because
                    # obfuscation legitimately renames identifiers that appear in
                    # bash's own diagnostics (e.g. "r: readonly variable").
                    if diff.hard_ok:
                        if not diff.stderr_match:
                            advisory.append(rec)
                        continue
                    known = is_known(c.name, m.name, BASH_VERSION)
                    if known:
                        rec["reason"] = known.reason
                        registered.append(rec)
                    else:
                        divergences.append(rec)

    elapsed = time.perf_counter() - t0

    # Group unregistered divergences by (case, mutation) for a compact report.
    grouped: dict[tuple[str, str], list[dict]] = {}
    for d in divergences:
        grouped.setdefault((d["case"], d["mutation"]), []).append(d)

    for (case, mut), recs in sorted(grouped.items()):
        seeds_hit = sorted({r["seed"] for r in recs})
        flags = []
        r0 = recs[0]
        if not r0["stdout_match"]:
            flags.append("stdout")
        if not r0["exit_match"]:
            flags.append("exit")
        if not r0["stderr_match"]:
            flags.append("stderr")
        print(f"[DIVERGENCE] {case} @ {mut} ({r0['tier']})  "
              f"seeds={seeds_hit}  differs=[{','.join(flags)}]")
        print("    " + r0["detail"].replace("\n", "\n    ")[:900])
        print()

    Path("ci_output").mkdir(exist_ok=True)
    summary = {
        "bash_version": ver,
        "cases": len(cases),
        "mutations": len(mutations),
        "seeds": seeds,
        "eval_modes": eval_modes,
        "checks": checks,
        "divergences": len(divergences),
        "registered": len(registered),
        "advisory_stderr": len(advisory),
        "engine_errors": engine_errors,
        "grouped": [
            {"case": c, "mutation": m, "seeds": sorted({r["seed"] for r in recs})}
            for (c, m), recs in sorted(grouped.items())
        ],
        "advisory": [
            {"case": a["case"], "mutation": a["mutation"], "seed": a["seed"]}
            for a in advisory
        ],
        "details": divergences,
    }
    Path("ci_output/differential_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")

    # Advisory (stderr-only) differences, grouped compactly — not a failure.
    adv_groups = sorted({(a["case"], a["mutation"]) for a in advisory})
    if adv_groups:
        print("ADVISORY (stdout+exit match; stderr signature differs - often "
              "renamed identifiers in bash diagnostics):")
        for case, mut in adv_groups:
            print(f"  ~ {case} @ {mut}")
        print()

    print("+" + "-" * 62 + "+")
    print(f"  checks={checks}  unregistered-divergences={len(divergences)}"
          f"  registered={len(registered)}  advisory-stderr={len(advisory)}"
          f"  engine-errors={len(engine_errors)}")
    print(f"  distinct (case,mutation) failing: {len(grouped)}   "
          f"elapsed={elapsed:.1f}s")
    print("+" + "-" * 62 + "+")

    if engine_errors:
        print("\nENGINE ERRORS (obfuscation raised):")
        for e in engine_errors[:20]:
            print(f"  {e['case']} seed={e['seed']} {e['eval_mode']}: {e['error']}")

    return 1 if (divergences or engine_errors) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
