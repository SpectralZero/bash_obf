# Changelog

This changelog records shipped or repository-complete behavior. The project is proprietary internal software; entries do not imply public availability or a configured publication channel.

## Unreleased

### Fixed

- Faithfulness bugs found via a new adversarial differential harness and locked with regression tests:
  - Process substitution: `<(...)`/`>(...)` command arguments were quoted into literal filenames, and `< <(...)` / `> >(...)` redirect operands collapsed into `<<(` / `>>(` (a heredoc/append token).
  - `opaque-const` corrupted positional parameters (`$1`, `${10}`) by rewriting the digit into opaque arithmetic.
  - `id-mangle` missed variable reference sites: arithmetic array subscripts (`${arr[i+1]}`), unquoted heredoc bodies, and variables enumerated by an indirect prefix expansion (`${!prefix@}`).
  - `flow-obfusc` subshell-wrapped `(( var=... ))` arithmetic assignments (losing the assignment) and opaque-wrapped state mutations.
  - `encode` changed the exit-status semantics of bare assignments (e.g. a failed readonly reassignment) and clobbered `$?` by `eval`-wrapping such commands.

### Added

- Adversarial differential-testing harness: a 93-case combinatorial construct corpus run under a 20-way input-mutation matrix, a side-effect classification/safety gate, and a known-divergence registry with root-cause grouping, plus an exhaustive sweep runner (`ci/differential_sweep.py`) that reports a grouped ROOT CAUSE SUMMARY.
- Deterministic `scripts/generate_man.py` generation of `docs/obfush.1` from plain Click help, with a regression test.
- Non-root Docker image exposing the `obfush` CLI.
- Manual-only container and Python release artifact workflows with no external publication or credential steps.
- Internal installation, release, architecture, threat-model, contribution, security, and layer-development guidance.
- Optional PyInstaller specification for authorized local executable builds.

### Policy

- Documented proprietary internal distribution and authorized-use requirements.
- Explicitly deferred all VM bytecode, opcode, interpreter, string-pool, junk-bytecode, and multi-process VM work.
- Recorded funding metadata as externally pending because no approved handle is known.

## 2.0.0-dev

- Development version represented by the current package metadata and runtime version.
- No external release or package publication is asserted by this entry.
