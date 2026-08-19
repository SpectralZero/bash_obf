"""Deterministic, combinatorial Bash-construct corpus.

Every case is *pure by construction* (or writes only to its own ``mktemp``
scratch that it removes) and prints a fully deterministic result to stdout, so
original-vs-obfuscated equivalence can be judged by comparing streams.

The corpus systematically combines the construct axes that hide faithfulness
bugs: quoting, arrays, parameter expansion, here-documents, arithmetic, test
constructs, control flow, process substitution, redirections and scoping —
each exercised alone and in a few high-value combinations.

Cases are emitted in a stable, sorted order.  ``core=True`` marks a compact
subset (spanning all axes) that the default pytest run executes under the full
mutation matrix; the nightly sweep runs the whole corpus.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass

from .classification import SideEffect


@dataclass(frozen=True)
class Case:
    name: str
    script: str
    side_effect: SideEffect = SideEffect.PURE
    reads_argv: bool = False
    reads_stdin: bool = False
    needs_bash: tuple[int, ...] | None = None
    core: bool = False
    note: str = ""


def _c(name, script, *, core=False, se=SideEffect.PURE,
       argv=False, stdin=False, nb=None, note=""):
    return Case(
        name=name,
        script=textwrap.dedent(script).strip("\n") + "\n",
        side_effect=se,
        reads_argv=argv,
        reads_stdin=stdin,
        needs_bash=nb,
        core=core,
        note=note,
    )


# ── quoting ──────────────────────────────────────────────────────────

def _quoting() -> list[Case]:
    out: list[Case] = []
    payloads = {"spaces": "a  b", "glob": "a*b?", "special": "x&y|z"}
    for key, val in payloads.items():
        out.append(_c(
            f"quote_single_{key}",
            fr"""
            v='{val}'
            printf '[%s]\n' "$v"
            """,
            core=(key == "glob"),
            note="single-quoted literal is preserved verbatim",
        ))
        out.append(_c(
            f"quote_double_{key}",
            fr"""
            v="{val}"
            printf '[%s]\n' "$v"
            """,
            note="double-quoted literal (no $, no backtick) is preserved",
        ))
    out += [
        _c("quote_ansi_c", r"""
           v=$'a\tb\nc'
           printf '%s' "$v" | cat -A
           printf '\n'
           """, core=True, note="ANSI-C $'...' expands \\t and \\n"),
        _c("quote_unquoted_splits", r"""
           s="a b c"
           set -- $s
           printf '%d:%s\n' "$#" "$2"
           """, note="unquoted expansion word-splits (=> 3:b)"),
        _c("quote_double_nosplit", r"""
           s="a b c"
           set -- "$s"
           printf '%d:[%s]\n' "$#" "$1"
           """, core=True, note="double-quoted expansion does not split"),
        _c("quote_glob_quoted_noexpand", r"""
           printf '%s\n' "a*" '?' "[x]"
           """, note="quoted glob chars must stay literal"),
        _c("quote_backtick_eq_dollar", r"""
           a=`printf 'x y'`
           b=$(printf 'x y')
           [ "$a" = "$b" ] && printf 'eq:[%s]\n' "$a"
           """, note="backtick and $() command-sub are equivalent"),
        _c("quote_nested_dollar_single", r"""
           printf '%s\n' 'literal $HOME and `cmd`'
           """, note="single quotes suppress all expansion"),
        _c("quote_escaped_dollar", r"""
           v=SECRET
           printf '%s\n' "\$v is literal, \${v} too"
           """, core=True, note="escaped $ must not expand"),
    ]
    return out


# ── arrays ───────────────────────────────────────────────────────────

def _arrays() -> list[Case]:
    return [
        _c("array_indexed_basic", r"""
           arr=(alpha beta gamma)
           printf 'n=%d first=%s last=%s\n' "${#arr[@]}" "${arr[0]}" "${arr[-1]}"
           """, core=True, note="indexed array count + index"),
        _c("array_at_vs_star", r"""
           arr=("a b" c d)
           printf 'AT:'; printf '<%s>' "${arr[@]}"; printf '\n'
           IFS=,
           printf 'STAR:%s\n' "${arr[*]}"
           """, core=True, note='"${a[@]}" preserves elems; "${a[*]}" joins on IFS'),
        _c("array_empty", r"""
           arr=()
           printf 'n=%d def=%s\n' "${#arr[@]}" "${arr[@]:-EMPTY}"
           """, note="empty array length and :- default"),
        _c("array_sparse", r"""
           arr=([2]=x [5]=y)
           printf 'n=%d idx=%s\n' "${#arr[@]}" "${!arr[*]}"
           printf 'v2=%s v5=%s\n' "${arr[2]}" "${arr[5]}"
           """, note="sparse indices and ${!arr[*]}"),
        _c("array_append", r"""
           arr=(a b)
           arr+=(c d)
           printf '%s\n' "${arr[*]}"
           """, note="+= append to array"),
        _c("array_slice", r"""
           arr=(0 1 2 3 4 5)
           printf '%s\n' "${arr[*]:2:3}"
           """, note="array slice offset:length"),
        _c("array_assoc", r"""
           declare -A m=([k1]=v1 [k2]=v2)
           printf '%s|%s|%d\n' "${m[k1]}" "${m[k2]}" "${#m[@]}"
           """, nb=(4, 0), core=True, note="associative array lookup (deterministic keys)"),
        _c("array_spaces_elems", r"""
           arr=("one two" "three")
           for e in "${arr[@]}"; do printf '<%s>\n' "$e"; done
           """, note="array elements with spaces preserved in for-loop"),
        _c("array_from_positional", r"""
           set -- "a b" c
           arr=("$@")
           printf 'n=%d e0=[%s]\n' "${#arr[@]}" "${arr[0]}"
           """, argv=False, note='arr=("$@") captures each positional distinctly'),
    ]


# ── parameter expansion ──────────────────────────────────────────────

def _expansion() -> list[Case]:
    return [
        _c("expand_length", r"""
           v=hello
           printf '%d\n' "${#v}"
           """, core=True),
        _c("expand_default", r"""
           printf '%s\n' "${undef:-fallback}"
           printf '%s\n' "${undef:=assigned}"
           printf '%s\n' "$undef"
           """, note=":- and := defaults"),
        _c("expand_alt", r"""
           v=set
           printf '[%s]\n' "${v:+ALT}"
           printf '[%s]\n' "${empty:+ALT}"
           """),
        _c("expand_substr", r"""
           v=abcdef
           printf '%s|%s\n' "${v:1:3}" "${v: -2}"
           """, core=True, note="substring incl. negative offset"),
        _c("expand_replace", r"""
           v=a-b-c-d
           printf '%s|%s\n' "${v/-/_}" "${v//-/_}"
           """, note="single vs global replacement"),
        _c("expand_trim", r"""
           v=path/to/file.txt
           printf '%s|%s|%s|%s\n' "${v%%.*}" "${v##*/}" "${v%/*}" "${v#*/}"
           """, core=True, note="prefix/suffix trimming"),
        _c("expand_case_mod", r"""
           v=MixedCase
           printf '%s|%s\n' "${v^^}" "${v,,}"
           """, nb=(4, 0), note="case modification ^^ ,,"),
        _c("expand_indirect", r"""
           target="deep value"
           ref=target
           printf '[%s]\n' "${!ref}"
           """, core=True, note="indirect expansion ${!ref}"),
        _c("expand_prefix_names", r"""
           zz_a=1; zz_b=2; zz_c=3
           printf '%s\n' "${!zz_@}"
           """, note="${!prefix@} name matching (sorted)"),
        _c("expand_arithmetic_index", r"""
           arr=(10 20 30 40)
           i=2
           printf '%s\n' "${arr[i+1]}"
           """, note="arithmetic inside array subscript"),
    ]


# ── here-documents / here-strings ────────────────────────────────────

def _heredoc() -> list[Case]:
    return [
        _c("heredoc_expand", r"""
           name=world
           cat <<EOF
           hello $name
           EOF
           """, core=True, note="unquoted heredoc expands variables"),
        _c("heredoc_quoted_delim", r"""
           name=world
           cat <<'EOF'
           hello $name and `date`
           EOF
           """, core=True, note="quoted delimiter suppresses expansion"),
        _c("heredoc_dash_tabs", "\tcat <<-EOF\n\t\tindented line\n\tEOF\n",
           note="<<- strips leading tabs"),
        _c("heredoc_to_file", r"""
           t=$(mktemp)
           cat <<EOF > "$t"
           line one
           line two
           EOF
           cat "$t"
           rm -f "$t"
           """, se=SideEffect.FILE_ONLY, core=True,
           note="heredoc redirected to a file, then read back"),
        _c("heredoc_here_string", r"""
           v="hello there"
           cat <<< "$v"
           read -r a b <<< "$v"
           printf '%s|%s\n' "$a" "$b"
           """, note="here-string <<< feeds stdin"),
        _c("heredoc_two_adjacent", r"""
           cat <<A; cat <<B
           first
           A
           second
           B
           """, note="two here-docs on one line"),
        _c("heredoc_while_read", r"""
           total=0
           while read -r n; do total=$((total + n)); done <<EOF
           3
           4
           5
           EOF
           printf 'sum=%d\n' "$total"
           """, note="heredoc feeding a while-read loop"),
    ]


# ── arithmetic ───────────────────────────────────────────────────────

def _arithmetic() -> list[Case]:
    return [
        _c("arith_dollar_paren", r"""
           printf '%d\n' "$(( 2 ** 10 % 7 ))"
           """, core=True),
        _c("arith_let", r"""
           let 'x = 6 * 7' || true
           printf '%d\n' "$x"
           """, note="let arithmetic"),
        _c("arith_double_paren", r"""
           (( y = 3 + 4 * 2 ))
           printf '%d\n' "$y"
           """, note="(( )) arithmetic command"),
        _c("arith_c_for", r"""
           for (( i = 0; i < 4; i++ )); do printf '%d' "$i"; done
           printf '\n'
           """, core=True, note="C-style for loop"),
        _c("arith_ternary", r"""
           a=5; b=3
           printf '%d\n' "$(( a > b ? a - b : b - a ))"
           """),
        _c("arith_bases", r"""
           printf '%d %d %d\n' "$(( 16#ff ))" "$(( 2#1010 ))" "$(( 8#17 ))"
           """, note="hex / binary / octal literals"),
        _c("arith_compound_assign", r"""
           n=10
           (( n += 5 )); (( n *= 2 )); (( n %= 7 ))
           printf '%d\n' "$n"
           """),
    ]


# ── test constructs ──────────────────────────────────────────────────

def _tests() -> list[Case]:
    return [
        _c("test_single_bracket", r"""
           x=hello
           if [ -n "$x" ] && [ "$x" = hello ]; then printf 'ok\n'; fi
           """, core=True),
        _c("test_double_bracket_glob", r"""
           f=report.txt
           if [[ "$f" == *.txt ]]; then printf 'match\n'; fi
           if [[ "$f" != *.log ]]; then printf 'nomatch\n'; fi
           """, core=True, note="[[ ]] pattern matching"),
        _c("test_builtin", r"""
           if test 3 -gt 2 && test -z ""; then printf 'ok\n'; fi
           """),
        _c("test_extglob", r"""
           shopt -s extglob
           s=abc
           if [[ "$s" == @(abc|def) ]]; then printf 'ext-ok\n'; fi
           case "$s" in +([a-c])) printf 'case-ok\n';; esac
           """, note="extended globs @(...) +(...)"),
        _c("test_regex", r"""
           s=abc123
           if [[ "$s" =~ ^([a-z]+)([0-9]+)$ ]]; then
               printf '%s|%s\n' "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}"
           fi
           """, core=True, note="=~ regex + BASH_REMATCH"),
        _c("test_arith_cond", r"""
           if (( 3 > 2 && 4 >= 4 )); then printf 'ok\n'; fi
           """),
        _c("test_file_ops", r"""
           t=$(mktemp)
           [ -f "$t" ] && printf 'exists\n'
           [ -s "$t" ] || printf 'empty\n'
           rm -f "$t"
           [ -e "$t" ] || printf 'gone\n'
           """, se=SideEffect.FILE_ONLY, note="file test operators"),
    ]


# ── control flow ─────────────────────────────────────────────────────

def _control() -> list[Case]:
    return [
        _c("flow_if_elif_else", r"""
           for n in 1 2 3; do
               if (( n == 1 )); then printf 'one\n'
               elif (( n == 2 )); then printf 'two\n'
               else printf 'many\n'; fi
           done
           """, core=True),
        _c("flow_case", r"""
           for x in apple banana cherry; do
               case "$x" in
                   a*) printf 'A:%s\n' "$x" ;;
                   b*) printf 'B:%s\n' "$x" ;;
                   *)  printf '?:%s\n' "$x" ;;
               esac
           done
           """, core=True, note="case with glob patterns"),
        _c("flow_case_fallthrough", r"""
           x=2
           case "$x" in
               [12]) printf 'low\n' ;;&
               2)    printf 'exactly-two\n' ;;
           esac
           """, nb=(4, 0), note=";;& fallthrough"),
        _c("flow_while_break_continue", r"""
           i=0
           while true; do
               i=$((i + 1))
               (( i == 2 )) && continue
               (( i >= 4 )) && break
               printf '%d\n' "$i"
           done
           """, core=True),
        _c("flow_until", r"""
           i=0
           until (( i >= 3 )); do printf '%d' "$i"; i=$((i + 1)); done
           printf '\n'
           """),
        _c("flow_nested_loops", r"""
           for a in 1 2; do
               for b in x y; do printf '%s%s ' "$a" "$b"; done
           done
           printf '\n'
           """),
        _c("flow_func_return_code", r"""
           is_even() { (( $1 % 2 == 0 )); }
           for n in 1 2 3 4; do
               if is_even "$n"; then printf '%d:even\n' "$n"; else printf '%d:odd\n' "$n"; fi
           done
           """, core=True, note="function used as a condition (return status)"),
    ]


# ── process substitution ─────────────────────────────────────────────

def _procsub() -> list[Case]:
    return [
        _c("procsub_input", r"""
           while read -r line; do printf 'got:%s\n' "$line"; done < <(printf 'x\ny\nz\n')
           """, core=True, note="< <(...) input process substitution"),
        _c("procsub_paste", r"""
           cat <(printf 'a\n') <(printf 'b\n')
           """, note="two input process substitutions concatenated"),
        _c("procsub_diff_style", r"""
           if diff <(printf '1\n2\n') <(printf '1\n2\n') >/dev/null; then
               printf 'same\n'
           fi
           """, se=SideEffect.FILE_ONLY, note="diff of two process substitutions"),
        _c("procsub_output_tee", r"""
           t=$(mktemp)
           printf 'payload\n' | tee >(cat > "$t") >/dev/null
           cat "$t"; rm -f "$t"
           """, se=SideEffect.FILE_ONLY, note=">(...) output process substitution"),
    ]


# ── redirections ─────────────────────────────────────────────────────

def _redirects() -> list[Case]:
    return [
        _c("redir_write_read", r"""
           t=$(mktemp)
           printf 'hello\n' > "$t"
           cat "$t"
           rm -f "$t"
           """, se=SideEffect.FILE_ONLY, core=True),
        _c("redir_append", r"""
           t=$(mktemp)
           printf 'a\n' > "$t"; printf 'b\n' >> "$t"
           cat "$t"; rm -f "$t"
           """, se=SideEffect.FILE_ONLY),
        _c("redir_stderr_split", r"""
           o=$(mktemp); e=$(mktemp)
           { printf 'to-out\n'; printf 'to-err\n' >&2; } 1>"$o" 2>"$e"
           printf 'OUT:'; cat "$o"; printf 'ERR:'; cat "$e"
           rm -f "$o" "$e"
           """, se=SideEffect.FILE_ONLY, core=True, note="separate 1> and 2> redirects"),
        _c("redir_combined", r"""
           t=$(mktemp)
           { printf 'x\n'; printf 'y\n'; } &> "$t"
           cat "$t"; rm -f "$t"
           """, se=SideEffect.FILE_ONLY, note="&> combined redirect"),
        _c("redir_noclobber", r"""
           t=$(mktemp)
           set -o noclobber
           printf 'first\n' > "$t"
           printf 'second\n' >| "$t"
           cat "$t"; rm -f "$t"
           """, se=SideEffect.FILE_ONLY, note=">| overrides noclobber"),
        _c("redir_group_to_file", r"""
           t=$(mktemp)
           {
               printf 'line1\n'
               printf 'line2\n'
           } > "$t"
           cat "$t"; rm -f "$t"
           """, se=SideEffect.FILE_ONLY, core=True, note="{ ...; } > file (compound redirect)"),
        _c("redir_fd_dup", r"""
           exec 3>&1
           printf 'via-fd3\n' >&3
           exec 3>&-
           """, note="fd duplication exec 3>&1"),
        _c("redir_readwrite", r"""
           t=$(mktemp)
           printf 'seed\n' > "$t"
           exec 4<> "$t"
           read -r line <&4
           printf 'read:%s\n' "$line"
           exec 4>&-
           rm -f "$t"
           """, se=SideEffect.FILE_ONLY, note="<> read-write fd"),
    ]


# ── scoping / declarations ───────────────────────────────────────────

def _scoping() -> list[Case]:
    return [
        _c("scope_local", r"""
           x=outer
           f() { local x=inner; printf 'in:%s\n' "$x"; }
           f
           printf 'out:%s\n' "$x"
           """, core=True, note="local does not leak to caller"),
        _c("scope_declare_int", r"""
           declare -i n
           n=3+4
           printf '%d\n' "$n"
           n=hello
           printf '%d\n' "$n"
           """, note="declare -i integer attribute"),
        _c("scope_readonly", r"""
           readonly r=constant
           printf '%s\n' "$r"
           r=changed 2>/dev/null || printf 'blocked\n'
           printf '%s\n' "$r"
           """, core=True, note="readonly prevents reassignment"),
        _c("scope_export_child", r"""
           export SHARED=visible
           bash -c 'printf "child:%s\n" "$SHARED"'
           """, note="export propagates to child shell"),
        _c("scope_dynamic", r"""
           inner() { printf 'sees:%s\n' "$dyn"; }
           outer() { local dyn=fromouter; inner; }
           outer
           """, note="dynamic scoping of locals"),
        _c("scope_nameref", r"""
           declare -n ref=real
           real=value
           printf '%s\n' "$ref"
           ref=updated
           printf '%s\n' "$real"
           """, nb=(4, 3), core=True, note="declare -n nameref"),
        _c("scope_func_stdout_capture", r"""
           make() { printf 'built-%s' "$1"; }
           v=$(make widget)
           printf '[%s]\n' "$v"
           """, note="capturing function stdout"),
        _c("scope_local_array", r"""
           f() { local -a a=(x y z); printf '%d:%s\n' "${#a[@]}" "${a[*]}"; }
           f
           """, note="local -a array declaration"),
    ]


# ── positional / stdin-driven (mutation-sensitive) ───────────────────

def _io() -> list[Case]:
    return [
        _c("io_argc_argv", r"""
           printf 'argc=%d\n' "$#"
           i=1
           for a in "$@"; do printf 'arg%d=[%s]\n' "$i" "$a"; i=$((i + 1)); done
           """, argv=True, core=True, note='"$@" preserves each arg exactly'),
        _c("io_star_vs_at", r"""
           IFS=,
           printf 'star=[%s]\n' "$*"
           set -- "$@"
           printf 'count=%d\n' "$#"
           """, argv=True, note='$* joins on IFS; "$@" keeps split'),
        _c("io_shift", r"""
           printf 'before=%d\n' "$#"
           shift 2 2>/dev/null || shift $# 2>/dev/null || true
           printf 'after=%d first=[%s]\n' "$#" "${1:-none}"
           """, argv=True, core=True, note="shift adjusts positional params"),
        _c("io_read_loop", r"""
           count=0
           while IFS= read -r line; do
               count=$((count + 1))
               printf '%d:[%s]\n' "$count" "$line"
           done
           printf 'lines=%d\n' "$count"
           """, stdin=True, core=True, note="IFS= read -r preserves whitespace"),
        _c("io_read_fields", r"""
           if IFS=: read -r a b c; then
               printf 'a=%s b=%s c=%s\n' "$a" "$b" "$c"
           else
               printf 'noinput\n'
           fi
           """, stdin=True, note="field-splitting read with custom IFS"),
        _c("io_dollar_hash_status", r"""
           false; s1=$?
           true;  s2=$?
           printf 'after-false=%d after-true=%d\n' "$s1" "$s2"
           """, core=True, note="$? reflects last command status"),
    ]


# ── small combinations (cross-axis) ──────────────────────────────────

def _combos() -> list[Case]:
    return [
        _c("combo_array_heredoc_redirect", r"""
           t=$(mktemp)
           items=("a b" c d)
           {
               printf 'count=%d\n' "${#items[@]}"
               for it in "${items[@]}"; do printf 'item=[%s]\n' "$it"; done
           } > "$t"
           cat <<EOF >> "$t"
           trailer
           EOF
           cat "$t"; rm -f "$t"
           """, se=SideEffect.FILE_ONLY, core=True,
           note="array + compound redirect + heredoc append together"),
        _c("combo_func_local_arith_loop", r"""
           sum() {
               local total=0 n
               for n in "$@"; do (( total += n )); done
               printf '%d\n' "$total"
           }
           sum 1 2 3 4 5
           """, note="function + local + arithmetic + positional"),
        _c("combo_case_in_while_read", r"""
           while read -r tok; do
               case "$tok" in
                   num:*) printf 'N=%s\n' "${tok#num:}" ;;
                   str:*) printf 'S=%s\n' "${tok#str:}" ;;
                   *)     printf 'other=%s\n' "$tok" ;;
               esac
           done <<EOF
           num:42
           str:hello
           plain
           EOF
           """, note="case inside while-read over heredoc"),
        _c("combo_procsub_array_mapfile", r"""
           mapfile -t lines < <(printf 'one\ntwo\nthree\n')
           printf 'n=%d mid=%s\n' "${#lines[@]}" "${lines[1]}"
           """, nb=(4, 0), core=True, note="mapfile from process substitution into array"),
        _c("combo_nested_quotes_cmdsub", r"""
           name="the world"
           msg="hello, $(printf '%s' "$name")!"
           printf '%s\n' "$msg"
           """, note="nested quotes across command substitution"),
        _c("combo_trap_exit", r"""
           cleanup() { printf 'cleanup ran\n'; }
           trap cleanup EXIT
           printf 'main body\n'
           """, core=True, note="trap ... EXIT must still fire"),
        _c("combo_arith_array_indirect", r"""
           declare -a data=(100 200 300)
           key=data
           idx=1
           eval "printf 'via-indirect=%s\n' \"\${$key[idx]}\""
           printf 'direct=%s\n' "${data[idx]}"
           """, note="indirect array reference via eval"),
    ]


_GROUPS = (
    _quoting, _arrays, _expansion, _heredoc, _arithmetic,
    _tests, _control, _procsub, _redirects, _scoping, _io, _combos,
)


def generate() -> list[Case]:
    """Return the full corpus in a stable, de-duplicated, sorted order."""
    seen: dict[str, Case] = {}
    for group in _GROUPS:
        for case in group():
            if case.name in seen:
                raise ValueError(f"duplicate corpus case name: {case.name}")
            seen[case.name] = case
    return [seen[name] for name in sorted(seen)]


def sample(core_only: bool = True) -> list[Case]:
    """Compact subset (spanning all axes) for the fast default test run."""
    cases = generate()
    if core_only:
        return [c for c in cases if c.core]
    return cases
