"""Known-divergence registry — the auditable "expected failing" list.

This is the single source of truth for original-vs-obfuscated divergences that
are *accepted for now*, each with an explicit root-cause label, reason and owner.
It is consumed by the differential pytest suite (as tolerant xfail) and by
``ci/differential_sweep.py`` (which separates *registered* from *unregistered*
divergences and groups registered ones by ``root_cause``), so the two never drift.

Policy
------
* An entry is a **debt marker**, not a silencer: it must name the real cause and
  a plan, never "flaky" or "TODO".
* ``root_cause`` is a short, stable label; several cases may share one when they
  have the *same* underlying bug (so the sweep reports N root causes, not N
  fixtures — the "make the number unambiguous" rule).
* Prefer fixing the root cause.  Register only when a fix is deferred deliberately
  (e.g. it needs the quoting/expansion-metadata work, or a specific bash version).
* ``bash_max`` optionally scopes an entry to bash versions ``<= bash_max`` (for
  version-specific quirks surfaced by the multi-bash matrix).
* The sweep reports registered entries that no longer reproduce so the list can
  be pruned; accidental fixes should not silently rot the registry.

Recently pruned (fixed at the root, now covered by regression tests):
* ``procsub_input`` / ``combo_procsub_array_mapfile`` — process substitution as a
  command argument was quoted into a literal filename (_shell_quote), and a
  process-sub redirect operand collapsed ``< <(`` into ``<<(``.  Both emitter
  bugs are fixed; see tests/test_faithfulness_regressions.py.
* opaque-const corrupting ``$1`` — fixed earlier, likewise absent here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KnownDivergence:
    case: str                       # corpus case name or fixture filename
    mutation: str                   # mutation name, or "*" for any
    root_cause: str                 # short stable label; groups cases by shared cause
    reason: str                     # root-cause explanation + fix plan
    owner: str                      # who owns the fix
    since: str                      # ISO date the debt was recorded
    priority: str = "medium"        # "high" | "medium" | "low" — fix-sequencing hint
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


# Divergences surfaced by the adversarial FULL-corpus sweep whose root-cause
# fixes are being sequenced deliberately (fix carefully, do not force).  Each
# names the real cause and the intended fix.  Grouped by ``root_cause`` so the
# sweep reports a small number of underlying bugs rather than a scary run count.
KNOWN: tuple[KnownDivergence, ...] = (
    # ── opaque-const context-blindness — FIXED (2026-08-19) ─────────────
    # arith_bases: _INTEGER_RE now excludes digits adjacent to '#', so a base-N
    # constant (16#ff, 2#1010, 8#17) keeps both its base and its digits.
    # Locked by tests/test_faithfulness_regressions.py.

    # ── flow-obfusc / encode wrapping a state mutation — FIXED (2026-08-19) ──
    # arith_double_paren: flow-obfusc no longer subshell-wraps (( var=... ))
    #   arithmetic-assignment commands, nor opaque-predicate-wraps state mutators.
    # scope_readonly: the encode layer no longer eval-wraps a bare assignment
    #   (which changed the exit status of a failed readonly reassignment).
    # Both locked by tests/test_faithfulness_regressions.py.

    # ── id-mangle: rename misses a reference site — FIXED (2026-08-19) ───
    # heredoc_expand / expand_arithmetic_index / expand_prefix_names: id-mangle
    # now rewrites references inside unquoted heredoc bodies and arithmetic array
    # subscripts, and EXCLUDES variables enumerated by a ${!prefix@}/${!prefix*}
    # expansion from renaming.  Locked by tests/test_faithfulness_regressions.py.

    # ── name positions must stay bare identifiers ───────────────────────
    KnownDivergence(
        case="combo_func_local_arith_loop", mutation="*",
        root_cause="name_position_mangled",
        reason=(
            "id-mangle/encode rewrites a NAME position into a quoted/encoded form: the "
            "for-loop variable becomes `for $'_k67' in ...` and the `local` name is "
            "base64-decoded -- both invalid ('_k67': not a valid identifier). Fix: never "
            "quote/encode identifiers in name positions (for VAR, local/declare NAME, "
            "read VAR)."
        ),
        owner="core-team", since="2026-08-19"),

    # ── quoting / word-split metadata — FIXED (2026-08-19) ──────────────
    # quote_unquoted_splits: _shell_quote no longer re-quotes a bare expansion the
    #   parser recorded as UNQUOTED (so `set -- $s` keeps word-splitting).
    # combo_nested_quotes_cmdsub: _escape_dq_body escapes " and \ only OUTSIDE a
    #   $(...)/`...` command substitution, so nested cmdsub quotes survive.
    # Both locked by tests/test_faithfulness_regressions.py.

    # ── positional parameters relocated into a function ─────────────────
    KnownDivergence(
        case="io_star_vs_at", mutation="*",
        root_cause="positional_params_scope",
        reason=(
            "junk-inject/flow relocates a command that reads $*/$@/$# into a FUNCTION "
            "body; inside a function those are the function's own positional params, "
            "not the script's, so \"$*\" expands empty. Fix: do not move commands "
            "referencing $@/$*/$#/$N into a function body (or forward \"$@\")."
        ),
        owner="core-team", since="2026-08-19"),

    # ── indirection builds an invalid array subscript ───────────────────
    KnownDivergence(
        case="combo_arith_array_indirect", mutation="*",
        root_cause="indirection_array_subscript",
        reason=(
            "indirection emits an invalid ${$var[idx]} form for an indirect array "
            "reference (bad substitution) and renames the array inconsistently between "
            "the eval'd indirect access and the direct ${data[idx]} access. Fix: do not "
            "apply ${!ref}/${$var} indirection to array-subscript expansions; keep array "
            "renames consistent across eval boundaries."
        ),
        owner="core-team", since="2026-08-19"),

    # ── emitter: two heredocs on one command line — FIXED (2026-08-19) ──
    # heredoc_two_adjacent: the parser derived the delimiter from the redirect
    # TARGET word (`<<A` -> "A") instead of defaulting to "EOF", so the body no
    # longer absorbs the terminator line.  Also fixes any non-EOF single heredoc.
    # Locked by tests/test_faithfulness_regressions.py.

    # ── test -> [[ ]] conversion drops an empty operand — FIXED (2026-08-19) ──
    # test_builtin: the emitter dropped an empty QUOTED word ( `test -z ""` ->
    # `test -z` ), losing the operand.  _emit_word now emits "" / '' for an empty
    # quoted word.  Locked by tests/test_faithfulness_regressions.py.

    # ── encode/pipeline resets $? before it is read — FIXED (2026-08-19) ──
    # io_dollar_hash_status: the encode layer no longer eval-wraps a command that
    # reads $? (the decode pipeline in eval "$(...|base64 -d)" reset it first) nor
    # a bare assignment.  Locked by tests/test_faithfulness_regressions.py.
)


# Inherent, low-priority limitations that are NOT ordinary fixture debt: they are
# not corpus cases (so is_known / the sweep gate do not reference them) and cannot
# be fixed without changing obfuscation semantics.  Documented here so they are
# tracked and not rediscovered.  Consulted by humans, not the gate.
KNOWN_LIMITATIONS: tuple[KnownDivergence, ...] = (
    KnownDivergence(
        case="procsub_output_flow_subshell", mutation="*",
        root_cause="output_procsub_subshell_race",
        reason=(
            "An OUTPUT process substitution combined with `wait` -- e.g. "
            "`printf ... > >(cat); wait` -- relies on the async writer being a child "
            "of the top-level shell so the top-level `wait` can reap it.  When "
            "flow-obfusc wraps the command in a subshell ( ( ... ) ), the writer "
            "becomes a grandchild that the outer `wait` cannot reap, so its output "
            "can race/be lost.  This is inherent to output process substitution + "
            "job control and is NOT fixable without changing semantics (it would "
            "require never subshell-wrapping any command containing `>(...)`, or "
            "rewriting the wait topology).  Rare in practice; input process "
            "substitution `<(...)` is unaffected.  Priority: low."
        ),
        owner="core-team", since="2026-08-19", priority="low"),
)



def is_known(case: str, mutation: str,
             bash_version: tuple[int, ...] | None = None) -> KnownDivergence | None:
    """Return the matching registry entry, or ``None`` if the pair is not accepted."""
    for entry in KNOWN:
        if entry.matches(case, mutation, bash_version):
            return entry
    return None


def root_cause_index() -> dict[str, list[str]]:
    """Map each ``root_cause`` label to the sorted list of cases that share it.

    Lets the sweep and reports collapse many failing (case, mutation, seed) runs
    into the small number of *distinct underlying bugs* they actually represent.
    """
    index: dict[str, list[str]] = {}
    for entry in KNOWN:
        cases = index.setdefault(entry.root_cause, [])
        if entry.case not in cases:
            cases.append(entry.case)
    for cases in index.values():
        cases.sort()
    return index
