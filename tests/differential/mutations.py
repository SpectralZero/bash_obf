"""Input-mutation matrix.

Each mutation is an orthogonal perturbation of a script's *execution input*,
applied identically to the original and obfuscated variants.  The obfuscator
must preserve behaviour under every one of them.

Mutations are expressed as (prologue, argv, stdin) rather than process-env
changes so that ``export``/``IFS``/``set`` reliably take effect across the WSL
``bash.exe`` boundary on Windows and on native Linux alike.

Tiers
-----
``faithful``  Input-handling that must always be preserved (argv, stdin, IFS,
              locale, HOME).  A divergence here is a real faithfulness bug.
``strict``    ``set -e``/``-u``/``pipefail`` wrappers that stress the obfuscator's
              own scaffolding (decoy vars, opaque predicates).  Divergences here
              may be genuine bugs *or* documented robustness limits.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class Mutation:
    name: str
    tier: str = "faithful"          # "faithful" | "strict"
    prologue: str = ""
    argv: Tuple[str, ...] = ()
    stdin: str = ""
    core: bool = False              # part of the fast default subset
    note: str = ""


_ALL: tuple[Mutation, ...] = (
    # ── faithful: argv ────────────────────────────────────────────────
    Mutation("baseline", core=True, note="no args, no stdin"),
    Mutation("arg_single", argv=("solo",), note="one positional arg"),
    Mutation("args_spaces", argv=("a b", "c\td", "  "), core=True,
             note="args containing spaces/tabs"),
    Mutation("args_glob", argv=("*", "?", "[abc]", "a*b"), core=True,
             note="glob metacharacters must not expand"),
    Mutation("args_many", argv=tuple(f"v{i}" for i in range(12)),
             note="many positional args ($# large)"),
    Mutation("args_weird", argv=("line\nbreak", "tab\there", "ünïcødé", "$HOME"),
             note="newline/tab/unicode/dollar in args"),
    Mutation("args_empty_elems", argv=("", "x", ""),
             note="empty-string positional args"),

    # ── faithful: stdin ───────────────────────────────────────────────
    Mutation("stdin_lines", stdin="alpha\nbeta\ngamma\n", core=True,
             note="multi-line stdin for read loops"),
    Mutation("stdin_no_final_newline", stdin="one\ntwo",
             note="last line without trailing newline"),
    Mutation("stdin_spaces", stdin="  leading and  trailing  \n\ttabbed\n",
             note="whitespace-sensitive stdin"),
    Mutation("stdin_empty", stdin="", note="empty stdin (immediate EOF)"),

    # ── faithful: environment ─────────────────────────────────────────
    Mutation("ifs_colon", prologue="IFS=:", core=True,
             note="custom IFS affects word splitting"),
    Mutation("ifs_newline", prologue="IFS=$'\\n'",
             note="newline-only IFS"),
    Mutation("ifs_empty", prologue='IFS=""',
             note="empty IFS disables splitting"),
    Mutation("lang_utf8", prologue="export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8",
             note="UTF-8 locale (collation/printf)"),
    Mutation("home_space", prologue="export HOME='/tmp/h h'",
             note="HOME containing a space"),

    # ── strict: set-flags ─────────────────────────────────────────────
    Mutation("set_e", tier="strict", prologue="set -e", core=True,
             note="errexit: any nonzero must abort identically"),
    Mutation("set_u", tier="strict", prologue="set -u",
             note="nounset: obfuscator must not read unset vars"),
    Mutation("set_pipefail", tier="strict", prologue="set -o pipefail",
             note="pipefail: pipeline exit status"),
    Mutation("set_euo", tier="strict", prologue="set -euo pipefail",
             note="the canonical strict-mode trio"),
)

FULL_MUTATIONS: tuple[Mutation, ...] = _ALL
CORE_MUTATIONS: tuple[Mutation, ...] = tuple(m for m in _ALL if m.core)
