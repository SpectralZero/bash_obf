"""Faithfulness regression tests — one differential test per fixed bug.

Each test obfuscates a minimal script that isolates a specific historical
faithfulness bug, executes BOTH the original and the obfuscated script in real
bash, and asserts identical stdout + exit code.  Where a bug lived in a
specific layer, that layer is forced so the regression is exercised directly.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from obfush.engine.ast_emitter import emit
from obfush.engine.ast_parser import parse_bash
from obfush.engine.core import EngineConfig, PolymorphicEngine

BASH = shutil.which("bash") or next(
    (p for p in (
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Windows\System32\bash.exe",
        "/bin/bash", "/usr/bin/bash",
    ) if os.path.isfile(p)),
    None,
)
requires_bash = pytest.mark.skipif(BASH is None, reason="bash not available")

LAYER_SEEDS = (1, 7, 42, 99, 1337, 2024)


def _run(script: str) -> tuple[bytes, int]:
    proc = subprocess.run(
        [BASH],
        input=script.encode("utf-8"),
        capture_output=True,
        timeout=20,
        env={**os.environ, "LC_ALL": "C"},
    )
    return proc.stdout, proc.returncode


def _obf(src: str, seed: int, layers=None, eval_mode="ok", intensity=0.8) -> str:
    cfg = EngineConfig(
        seed=seed, intensity=intensity, eval_mode=eval_mode,
        min_layers=1, force_layers=layers, verify=False,
    )
    return PolymorphicEngine(cfg).run(src).output


def _assert_equivalent(src, seeds=(1, 42, 1337), layers=None,
                       eval_mode="ok", intensity=0.8):
    exp_out, exp_rc = _run(src)
    for seed in seeds:
        obf = _obf(src, seed, layers, eval_mode, intensity)
        out, rc = _run(obf)
        assert (out, rc) == (exp_out, exp_rc), (
            f"divergence at seed={seed}\n--- obfuscated ---\n{obf}\n"
            f"got  stdout={out!r} rc={rc}\nwant stdout={exp_out!r} rc={exp_rc}"
        )


@requires_bash
def test_array_literal_stays_array():
    _assert_equivalent(
        'arr=(alpha beta gamma)\nprintf "%s|%s\\n" "${#arr[@]}" "${arr[1]}"\n'
    )


@requires_bash
def test_scalar_parens_stays_scalar():
    _assert_equivalent('x="(not an array)"\nprintf "%s\\n" "$x"\n')


@requires_bash
def test_compound_redirect_survives():
    _assert_equivalent(
        't=$(mktemp)\n{ printf "a\\n"; printf "b\\n"; } > "$t"\n'
        'cat "$t"\nrm -f "$t"\n'
    )


@requires_bash
def test_heredoc_with_redirect_round_trips():
    _assert_equivalent(
        't=$(mktemp)\ncat <<EOF > "$t"\nline one\nline two\nEOF\n'
        'cat "$t"\nrm -f "$t"\n'
    )


@requires_bash
def test_for_loop_variable_stays_bare():
    src = 'for dir in one two three; do printf "%s\\n" "$dir"; done\n'
    _assert_equivalent(src, seeds=LAYER_SEEDS, layers=["str-shred"], intensity=1.0)
    _assert_equivalent(src)


@requires_bash
def test_set_euo_pipefail_not_subshelled():
    src = ('set -euo pipefail\nc=0\nfor x in a b c; do ((c++)); done\n'
           'printf "done %d\\n" "$c"\n')
    exp_out, exp_rc = _run(src)
    assert exp_rc == 1 and exp_out == b"", "baseline: set -e should abort at ((c++))"
    _assert_equivalent(src, seeds=LAYER_SEEDS, layers=["flow-obfusc"], intensity=1.0)


@requires_bash
def test_local_array_declaration_not_shredded():
    src = 'f() { local -a a=(x y z); printf "%d\\n" "${#a[@]}"; }\nf\n'
    _assert_equivalent(src, seeds=LAYER_SEEDS, layers=["str-shred"], intensity=1.0)


@requires_bash
def test_escaped_dollar_preserved():
    src = 'var=SHOULD_NOT_APPEAR\nprintf "%s\\n" "\\${#var} and \\$HOME literal"\n'
    _assert_equivalent(src, seeds=LAYER_SEEDS, layers=["id-mangle"], intensity=1.0)
    _assert_equivalent(src)


@requires_bash
def test_quoted_indirect_expansion_no_wordsplit():
    _assert_equivalent(
        'ref=target\ntarget="a b c"\nprintf "[%s]\\n" "${!ref}"\n'
    )


@requires_bash
def test_id_mangle_quoting_context_preserves_literals():
    src = ('downloader=curl\n[ "$downloader" = curl ] && '
           'printf "%s\\n" "downloader variable preserved"\n')
    _assert_equivalent(src, seeds=LAYER_SEEDS, layers=["id-mangle"], intensity=1.0)


@requires_bash
def test_unparsable_script_falls_back_verbatim():
    # A ``case`` statement is not handled by the bashlex-based parser, so the
    # whole script falls back to a single opaque node emitted verbatim.  (The
    # C-style ``for (( ))`` form is handled via placeholders and is NOT opaque,
    # so it is unsuitable for exercising the opaque-fallback regression.)
    src = (
        'x=beta\ncase "$x" in\n'
        '  alpha) printf "A\\n" ;;\n'
        '  beta) printf "B\\n" ;;\n'
        '  *) printf "?\\n" ;;\n'
        'esac\n'
    )
    ast = parse_bash(src)
    body = ast.get("body", [])
    assert len(body) == 1 and body[0].get("opaque") is True, \
        "unparsable script should become a single opaque node"
    assert emit(ast).strip() == src.strip(), "opaque node must emit verbatim"
    _assert_equivalent(src, seeds=LAYER_SEEDS, intensity=1.0)


@requires_bash
def test_opaque_predicates_never_quoted():
    src = 'printf "ok\\n"\n'
    for seed in LAYER_SEEDS:
        obf = _obf(src, seed, layers=["flow-obfusc"], intensity=1.0)
        assert '"! [[' not in obf, f"quoted opaque predicate at seed={seed}:\n{obf}"
        chk = subprocess.run([BASH, "-n"], input=obf.encode(), capture_output=True)
        assert chk.returncode == 0, f"invalid bash at seed={seed}:\n{chk.stderr.decode()}"
    _assert_equivalent(src, seeds=LAYER_SEEDS, layers=["flow-obfusc"], intensity=1.0)


@requires_bash
def test_report_style_script_end_to_end():
    src = (
        '#!/usr/bin/env bash\nset -euo pipefail\n'
        'main() {\n'
        '    local out="$1"; shift || true\n'
        '    local -a items=("$@")\n'
        '    [[ ${#items[@]} -eq 0 ]] && items=(x y)\n'
        '    { printf "count=%d\\n" "${#items[@]}"\n'
        '      for it in "${items[@]}"; do printf "item=%s\\n" "$it"; done\n'
        '    } > "$out"\n'
        '    cat <<EOF > "$out.readme"\ngenerated\nEOF\n'
        '    cat "$out" "$out.readme"; rm -f "$out" "$out.readme"\n'
        '}\n'
        'main "$(mktemp)" a b c\n'
    )
    _assert_equivalent(src, seeds=LAYER_SEEDS)


@requires_bash
def test_positional_param_digit_not_constified():
    # opaque-const must not rewrite the digit of a positional parameter: "$1"
    # must stay "$1" and never become "$((1))" (which drops the argument).
    src = (
        'is_even() { (( $1 % 2 == 0 )); }\n'
        'for n in 1 2 3 4; do\n'
        '    if is_even "$n"; then printf "%d:even\\n" "$n"\n'
        '    else printf "%d:odd\\n" "$n"; fi\n'
        'done\n'
    )
    _assert_equivalent(src, seeds=LAYER_SEEDS, layers=["opaque-const"], intensity=1.0)
    _assert_equivalent(src)


@requires_bash
def test_brace_positional_param_not_constified():
    # "${10}" style positional params must also survive opaque-const.
    src = (
        'f() { printf "%s\\n" "${10}"; }\n'
        'f a b c d e f g h i tenth\n'
    )
    _assert_equivalent(src, seeds=LAYER_SEEDS, layers=["opaque-const"], intensity=1.0)
    _assert_equivalent(src)


# ── process substitution: never quoted; redirect operand keeps its space ──
# Two distinct emitter bugs are locked here:
#   1. `<(...)`/`>(...)` as a command argument was single-quoted into a literal
#      filename ('<(...)') by _shell_quote.
#   2. `< <(...)` / `> >(...)` collapsed the operator-operand space into `<<(` /
#      `>>(`, which bash misparses as a heredoc / append operator.

def _emit_nolayer(src: str) -> str:
    return emit(parse_bash(src))


@requires_bash
def test_process_substitution_not_quoted():
    # A process substitution used as a command argument must be emitted verbatim
    # (never quoted into the literal path '<(...)').
    emitted = _emit_nolayer("cat <(echo hello)\n")
    assert "<(echo" in emitted
    assert "'<(" not in emitted and '"<(' not in emitted
    _assert_equivalent("cat <(echo hello)\n", seeds=LAYER_SEEDS, intensity=1.0)


@requires_bash
def test_process_substitution_with_redirection():
    # diff <(...) <(...): two argument process substitutions in one command.
    _assert_equivalent(
        "diff <(printf '1\\n2\\n') <(printf '1\\n2\\n') && echo SAME\n",
        seeds=LAYER_SEEDS, intensity=1.0,
    )


@requires_bash
def test_process_substitution_redirect_operand_keeps_space():
    # `done < <(...)` must NOT collapse into `<<(` (a heredoc): the whitespace
    # between the redirection operator and the process substitution is required.
    src = (
        "while read -r l; do printf 'got:%s\\n' \"$l\"; done "
        "< <(printf 'x\\ny\\nz\\n')\n"
    )
    emitted = _emit_nolayer(src)
    assert "<<(" not in emitted
    assert "< <(" in emitted
    _assert_equivalent(src, seeds=LAYER_SEEDS, intensity=1.0)


@requires_bash
def test_process_substitution_output_redirect_keeps_space():
    # `> >(...)` must not collapse into `>>(` (append operator followed by `(`).
    emitted = _emit_nolayer("printf 'hi\\n' > >(cat)\n")
    assert ">>(" not in emitted
    assert "> >(" in emitted


@requires_bash
def test_process_substitution_mapfile_array():
    # mapfile -t arr < <(...) populates an array from a process substitution.
    _assert_equivalent(
        "mapfile -t lines < <(printf 'one\\ntwo\\nthree\\n')\n"
        "printf 'n=%d mid=%s\\n' \"${#lines[@]}\" \"${lines[1]}\"\n",
        seeds=LAYER_SEEDS, intensity=1.0,
    )
