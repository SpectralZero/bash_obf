"""Known-divergence registry — the auditable "expected failing" list.

This is the single source of truth for original-vs-obfuscated divergences that
are *accepted for now*, each with an explicit root-cause reason and an owner.
It is consumed by the differential pytest suite (as tolerant xfail) and by
``ci/differential_sweep.py`` (which separates *registered* from *unregistered*
divergences), so the two never drift.

Policy
------
* An entry is a **debt marker**, not a silencer: it must name the real cause and
  a plan, never "flaky" or "TODO".
* Prefer fixing the root cause.  Register only when a fix is deferred deliberately
  (e.g. it needs the quoting/expansion-metadata work, or a specific bash version).
* ``bash_max`` optionally scopes an entry to bash versions ``<= bash_max`` (for
  version-specific quirks surfaced by the multi-bash matrix).
* The sweep reports registered entries that no longer reproduce so the list can
  be pruned; accidental fixes should not silently rot the registry.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KnownDivergence:
    case: str                       # corpus case name or fixture filename
    mutation: str                   # mutation name, or "*" for any
    reason: str                     # root-cause explanation
    owner: str                      # who owns the fix
    since: str                      # ISO date the debt was recorded
    bash_max: tuple[int, ...] | None = None  # scope to bash <= this version

    def matches(self, case: str, mutation: str,
                bash_version: tuple[int, ...] | None = None) -> bool:
        if self.case != case:
            return False
        if self.mutation != "*" and self.mutation != mutation:
            return False
        if self.bash_max is not None and bash_version is not None:
            if bash_version > self.bash_max:
                return False
        return True


# Divergences surfaced by the adversarial sweep whose root-cause fixes are being
# sequenced deliberately (fix carefully, do not force).  Each names the real
# cause and the intended fix.  ``opaque-const`` corrupting ``$1`` was already
# fixed (see tests/test_faithfulness_regressions.py) and is intentionally absent.
KNOWN: tuple[KnownDivergence, ...] = (
    KnownDivergence(
        case="procsub_input", mutation="*",
        reason=(
            "process substitution <(...) is captured as a redirect-target word and "
            "single-quoted into a literal filename ( } <'<(printf ...)' ), so the "
            "loop reads a non-existent file. Fix: recognise <(...)/>(...) in the "
            "parser and emit them verbatim (raw, never quoted)."
        ),
        owner="core-team", since="2026-08-19"),
    KnownDivergence(
        case="combo_procsub_array_mapfile", mutation="*",
        reason=(
            "same root cause as procsub_input: mapfile < <(...) has its process "
            "substitution emitted as a quoted literal filename, so the array is empty."
        ),
        owner="core-team", since="2026-08-19"),
    KnownDivergence(
        case="heredoc_expand", mutation="*",
        reason=(
            "id-mangle renames a variable (name -> _x) in its assignment but does not "
            "rewrite the $name reference inside the UNQUOTED heredoc body, so it "
            "expands to empty. Fix: exclude from the rename set any identifier "
            "referenced in a heredoc body (or rewrite refs inside unquoted bodies). "
            "This is the quoting/expansion-metadata work."
        ),
        owner="core-team", since="2026-08-19"),
    KnownDivergence(
        case="io_dollar_hash_status", mutation="*",
        reason=(
            "encode/str-shred wraps commands as eval \"$(...|base64 -d)\"; the "
            "command-substitution pipeline resets $? before an encoded 'x=$?' reads "
            "it, so the captured status is 0 instead of the prior command's. Fix: "
            "never encode/shred a command whose text references $?. (Masked under "
            "set -e, where both variants abort at the prior command.)"
        ),
        owner="core-team", since="2026-08-19"),
    KnownDivergence(
        case="scope_readonly", mutation="*",
        reason=(
            "flow-obfusc wraps the bare assignment 'r=changed' in "
            "'if TRUE; then r=changed; fi || ...', changing exit-status propagation of "
            "the readonly-assignment failure (the || fires and set -e no longer "
            "aborts). Fix: do not compound-wrap bare assignments; treat a failed "
            "assignment like the set/shift shell-state commands already excluded."
        ),
        owner="core-team", since="2026-08-19"),
)


def is_known(case: str, mutation: str,
             bash_version: tuple[int, ...] | None = None) -> KnownDivergence | None:
    """Return the matching registry entry, or ``None`` if the pair is not accepted."""
    for entry in KNOWN:
        if entry.matches(case, mutation, bash_version):
            return entry
    return None
