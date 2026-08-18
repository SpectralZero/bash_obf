"""
Layer 5: Control Flow Obfuscation

Reorders and disguises logic so the original structure cannot be recovered.
Must run BEFORE junk_inject and indirection (compatibility matrix).
"""

from __future__ import annotations

import random
import re

from obfush.layers.base import Layer, LayerConfig, LayerStats


class LayerImpl(Layer):
    name = "flow-obfusc"
    description = "Control flow restructuring"

    def transform(self, ast: dict, config: LayerConfig) -> tuple[dict, LayerStats]:
        stats = LayerStats()
        ast = _flow_walk(ast, config, stats)
        return ast, stats

    def estimate_size_increase(self, config: LayerConfig) -> float:
        return 1.4 + config.intensity * 0.6


# Declaration keywords whose arguments are scope-modifying variable bindings.
# Wrapping these in a subshell (...) would lose the binding in the parent scope.
_DECLARATION_KEYWORDS = frozenset({"local", "declare", "typeset", "readonly", "export"})
_LARGE_BODY_THRESHOLD = 200
_REORDER_WINDOW_SIZE = 50


def _flow_walk(ast: dict, config: LayerConfig, stats: LayerStats) -> dict:
    """Walk AST and apply control flow obfuscation."""
    if not isinstance(ast, dict):
        return ast

    rng = config.rng
    node_type = ast.get("type", "")
    stats.nodes_visited += 1

    # Classify the ORIGINAL command's shell-state effects *before* any
    # wrapping below reassigns `ast`.  Opaque-predicate wrapping turns a
    # command into an `if` compound, after which a post-hoc
    # `_mutates_shell_state(ast)` check would inspect the compound (and
    # wrongly return False), allowing the command to be subshell-wrapped and
    # its effect (e.g. `set -euo pipefail`, `shift`, `cd`) to be discarded.
    orig_is_command = node_type == "command"
    orig_mutates_state = orig_is_command and (
        _has_variable_escape(ast) or _mutates_shell_state(ast)
    )

    # ── Independent block reordering ──
    if node_type == "script":
        body = ast.get("body", [])
        if len(body) > 2 and rng.random() < config.intensity:
            max_group_size = (
                _REORDER_WINDOW_SIZE if len(body) > _LARGE_BODY_THRESHOLD else None
            )
            ast["body"] = _reorder_independent_blocks(
                body, rng, max_group_size=max_group_size,
            )
            if max_group_size is not None:
                stats.custom["reorder_window_size"] = max_group_size
            stats.blocks_reordered += 1
            stats.nodes_modified += 1

    # ── Opaque predicate wrapping ──
    # Skip nodes marked _no_wrap (compound-condition children — wrapping
    # them produces invalid bash like  if if [[ ... ]]; then ... fi; then).
    # Safe for state-mutating commands: `if <always-true>; then CMD; fi`
    # still runs CMD in the current shell.
    if (node_type == "command"
            and not ast.get("_no_wrap")
            and rng.random() < config.intensity * 0.3):
        ast = _wrap_opaque_predicate(ast, rng)
        stats.nodes_modified += 1

    # ── Subshell wrapping ──
    # Never subshell-wrap a state-mutating command: a subshell runs it in a
    # child process and silently discards the effect.  We use the pre-wrap
    # classification so opaque-predicate wrapping above cannot hide it.
    if (orig_is_command
            and not ast.get("_no_wrap")
            and rng.random() < config.intensity * 0.2
            and not orig_mutates_state):
        ast = _wrap_subshell(ast)
        stats.nodes_modified += 1

    # ── Function extraction ──
    if node_type == "script":
        body = ast.get("body", [])
        if len(body) > 3 and rng.random() < config.intensity * 0.4:
            ast["body"] = _extract_functions(body, rng)
            stats.nodes_modified += 1

    # ── Mark condition children before recursing into compound nodes ──
    # In compound if/while/until/for, certain child positions are conditions
    # that the shell evaluates for truthiness. Wrapping them in opaque
    # predicates or subshells corrupts the control-flow syntax.
    # NOTE: use ast.get("type"), NOT node_type — if the node was just wrapped
    # in an opaque predicate above, node_type is still "command" but ast is
    # now a compound.  We must mark the NEW compound's conditions too.
    if ast.get("type") == "compound":
        _mark_condition_children(ast)

    # Recurse
    for key in ("parts", "body", "test_parts"):
        val = ast.get(key)
        if isinstance(val, list):
            ast[key] = [_flow_walk(i, config, stats) if isinstance(i, dict) else i for i in val]
        elif isinstance(val, dict):
            ast[key] = _flow_walk(val, config, stats)

    return ast


_VAR_REF_RE = re.compile(r'\$\{?!?#?([a-zA-Z_]\w*)')

_BARRIER_COMMANDS = frozenset({
    "exit", "return", "break", "continue",
    "trap", "exec", "shift",
    ".", "source",                       # may load globals at unknown order
    "set", "shopt", "ulimit", "umask",   # global state
    "cd", "pushd", "popd",               # CWD-dependent
})

# Additional builtins that mutate parent-shell state (options, positional
# params, variables, traps).  Running any of these inside a subshell (...)
# would discard the effect in the parent shell.
_STATEFUL_BUILTINS = frozenset({
    "unset", "read", "eval", "mapfile", "readarray", "getopts", "let", "wait",
    "unalias", "alias", "disown", "hash", "enable",
})


def _mutates_shell_state(node: dict) -> bool:
    """True if a command changes parent-shell state and so must never be
    wrapped in a subshell or extracted into a called function.

    Covers option/trap/positional/dir/scope builtins:  set, shopt, shift,
    cd, trap, exec, export, readonly, declare, local, typeset, unset, read,
    eval, source/., ulimit, umask, getopts, etc.
    """
    if not isinstance(node, dict) or node.get("type") != "command":
        return False
    parts = node.get("parts") or []
    if not parts or not isinstance(parts[0], dict) or parts[0].get("type") != "word":
        return False
    cmd = parts[0].get("value", "")
    return (
        cmd in _BARRIER_COMMANDS
        or cmd in _DECLARATION_KEYWORDS
        or cmd in _STATEFUL_BUILTINS
    )


def _is_control_flow_barrier(node: dict) -> bool:
    """True if reordering past this node would break script semantics.

    Conservative: ANY command except pure variable assignments is a barrier,
    because most commands have I/O side effects whose order is observable
    (stdout, stderr, file writes, signals, network calls). Reordering only
    pure assignments is statically safe; everything else is risky.
    """
    if not isinstance(node, dict):
        return False
    if node.get("type") == "command":
        parts = node.get("parts") or []
        # Pure assignment block: every part is type=='assignment'
        if parts and all(
            isinstance(p, dict) and p.get("type") == "assignment"
            for p in parts
        ):
            return False  # safe to reorder
        # Any other command (echo, printf, cat, custom function, etc.)
        # has observable side effects — barrier.
        return True
    # Compound constructs (if / while / for / case / function / subshell etc.)
    if node.get("type") in ("compound", "function_def", "list", "pipeline"):
        return True
    return False


def _mark_condition_children(node: dict) -> None:
    """Mark children that serve as conditions so they are not wrapped.

    In bashlex-style compound nodes, parts include reservedword tokens
    ('if', 'then', 'do', etc.) interleaved with conditions and bodies.
    The condition is the command between the opening keyword and
    'then' / 'do'. Wrapping it produces invalid bash.

    In synthetic compound nodes (no reservedwords), the condition is
    conventionally parts[0] (for 'if', 'while', 'until') or not
    applicable (for '{', '(' groups).

    We take the conservative approach: any command child of a compound
    that appears BEFORE a 'then' or 'do' keyword is a condition and
    must not be individually wrapped.  We mark recursively because
    conditions are often wrapped in intermediate 'list' nodes.
    """
    kind = node.get("kind", "")
    parts = node.get("parts", [])
    if not parts:
        return

    # Only relevant for control-flow compounds
    if kind not in ("if", "while", "until", "for", "case", "select"):
        return

    # Detect whether parts include explicit reservedword tokens
    # (bashlex-style) or are synthetic (no keywords, just [condition, body])
    has_keywords = any(
        isinstance(p, dict) and p.get("type") == "word"
        and p.get("value", "") in ("if", "then", "do", "while", "until",
                                   "for", "elif", "else", "fi", "done",
                                   "case", "esac", "select")
        for p in parts
    )

    if has_keywords:
        # bashlex-style: mark every non-keyword child that appears before
        # the first 'then' or 'do' keyword as a condition child.
        seen_body_keyword = False
        for p in parts:
            if not isinstance(p, dict):
                continue
            val = p.get("value", "") if p.get("type") == "word" else ""
            if val in ("then", "do"):
                seen_body_keyword = True
                continue
            if val in ("elif",):
                # Reset: the next children until 'then' are a new condition
                seen_body_keyword = False
                continue
            if not seen_body_keyword:
                _deep_mark_no_wrap(p)
    else:
        # Synthetic: parts[0] is the condition for if/while/until
        if kind in ("if", "while", "until") and len(parts) >= 1:
            if isinstance(parts[0], dict):
                _deep_mark_no_wrap(parts[0])


def _deep_mark_no_wrap(node: dict) -> None:
    """Recursively set _no_wrap on a node and all its dict descendants."""
    node["_no_wrap"] = True
    for key in ("parts", "body", "test_parts"):
        val = node.get(key)
        if isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    _deep_mark_no_wrap(item)
        elif isinstance(val, dict):
            _deep_mark_no_wrap(val)


def _get_var_refs(node: dict) -> set[str]:
    """Collect all variable references (READS) from a node tree.

    Notes:
      - Assignment NAMEs are writes, not reads — we scan the assignment
        VALUE for $-references instead.
      - Word values are scanned with the same regex (covers the
        opaque-blob fallback case where bashlex couldn't parse).
    """
    refs: set[str] = set()

    def _walk(n: dict) -> None:
        if not isinstance(n, dict):
            return
        refs.update(n.get("var_refs", []))
        if n.get("type") == "assignment":
            value = n.get("value", "")
            if isinstance(value, str):
                refs.update(_VAR_REF_RE.findall(value))
        if n.get("type") == "expansion" and n.get("kind") == "parameter":
            v = n.get("value", "")
            if isinstance(v, str):
                refs.add(v)
        if n.get("type") == "word":
            value = n.get("value", "")
            if isinstance(value, str):
                refs.update(_VAR_REF_RE.findall(value))
        for key in ("parts", "body", "test_parts"):
            val = n.get(key)
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        _walk(item)
            elif isinstance(val, dict):
                _walk(val)
    _walk(node)
    return refs


def _get_var_writes(node: dict) -> set[str]:
    """Collect all variable assignments from a node tree.

    Detects both explicit assignment nodes AND word-style assignments
    in declaration commands (e.g. ``local url=${1}`` stores ``url`` as
    a word ``url=${1}`` rather than an assignment node).
    """
    writes: set[str] = set()

    def _walk(n: dict) -> None:
        if not isinstance(n, dict):
            return
        if n.get("type") == "assignment":
            writes.add(n.get("name", ""))
        # Declaration keywords: local/declare/export/readonly/typeset
        # Their word arguments are variable bindings that bashlex doesn't
        # always promote to assignment nodes.
        if n.get("type") == "command":
            parts = n.get("parts") or []
            if (parts and parts[0].get("type") == "word"
                    and parts[0].get("value", "") in _DECLARATION_KEYWORDS):
                for p in parts[1:]:
                    if p.get("type") == "assignment":
                        writes.add(p.get("name", ""))
                    elif p.get("type") == "word":
                        val = p.get("value", "")
                        if "=" in val:
                            name = val.split("=", 1)[0].lstrip("-")
                            if name and not name.startswith("-"):
                                writes.add(name)
                        elif val and not val.startswith("-"):
                            # bare  local varname  (no =value)
                            writes.add(val)
        for key in ("parts", "body", "test_parts"):
            val = n.get(key)
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        _walk(item)
            elif isinstance(val, dict):
                _walk(val)
    _walk(node)
    return writes


def _reorder_independent_blocks(
    body: list[dict],
    rng: random.Random,
    max_group_size: int | None = None,
) -> list[dict]:
    """Reorder independent blocks using linear aggregate dependency tracking."""
    # Build dependency info for each block
    blocks = []
    for node in body:
        writes = _get_var_writes(node)
        reads = _get_var_refs(node) - writes
        is_barrier = _is_control_flow_barrier(node)
        blocks.append({
            "node": node, "reads": reads, "writes": writes,
            "barrier": is_barrier,
        })

    # Find groups of independent blocks (no shared variables, no barrier)
    result: list[dict] = []
    independent_group: list[dict] = []
    group_reads: set[str] = set()
    group_writes: set[str] = set()
    group_has_barrier = False

    def flush_group() -> None:
        nonlocal independent_group, group_reads, group_writes, group_has_barrier
        if independent_group:
            rng.shuffle(independent_group)
            result.extend(block["node"] for block in independent_group)
        independent_group = []
        group_reads = set()
        group_writes = set()
        group_has_barrier = False

    for block in blocks:
        block_reads = block["reads"]
        block_writes = block["writes"]
        block_barrier = block["barrier"]
        if not isinstance(block_reads, set) or not isinstance(block_writes, set):
            continue
        if not isinstance(block_barrier, bool):
            block_barrier = bool(block_barrier)
        reached_window = (
            max_group_size is not None and len(independent_group) >= max_group_size
        )
        conflicts = (
            block_barrier
            or group_has_barrier
            or bool(block_reads & group_writes)
            or bool(block_writes & group_reads)
            or bool(block_writes & group_writes)
        )
        if reached_window or conflicts:
            flush_group()
        independent_group.append(block)
        group_reads.update(block_reads)
        group_writes.update(block_writes)
        group_has_barrier = group_has_barrier or block_barrier

    flush_group()

    return result


def _wrap_opaque_predicate(node: dict, rng: random.Random) -> dict:
    """Wrap a command in a procedurally-generated opaque predicate (always true)."""
    predicate = _generate_opaque_predicate(rng)

    # The test command is a condition of this synthetic if — mark it _no_wrap
    # so that recursion doesn't wrap it in yet another opaque predicate,
    # which would produce invalid bash:  if if [[ ... ]]; then ... fi; then
    #
    # The predicate is emitted VERBATIM (raw): some categories start with `!`
    # or contain `[[ ... ]]`/arithmetic that the word emitter would otherwise
    # wrap in double quotes, turning the test into a literal command name
    # (`if "! [[ 12 -eq 0 ]]"; then` → "command not found").  Setting raw also
    # keeps str-shred from fragmenting the predicate.
    test_cmd = {
        "type": "command",
        "parts": [{"type": "word", "value": predicate, "raw": predicate, "pos": None}],
        "pos": None,
        "_no_wrap": True,
    }

    return {
        "type": "compound",
        "kind": "if",
        "parts": [test_cmd, node],
        "pos": None,
        "_opaque": True,
    }


def _generate_opaque_predicate(rng: random.Random) -> str:
    """Generate a unique, analysis-resistant always-true predicate.

    Five categories of predicates, each with randomized operands.
    No two builds share the same predicate strings.
    """
    category = rng.randint(0, 4)

    if category == 0:
        # Randomized arithmetic identity — result is deterministic but
        # operands are randomized so pattern matching fails.
        a = rng.randint(2, 97)
        b = rng.randint(2, 97)
        c = a * b
        # $(( a * b )) always equals c
        return f'[[ $(( {a} * {b} )) -eq {c} ]]'

    elif category == 1:
        # String-based always-true predicate (valid bash, randomized).
        # NOTE: the previous implementation emitted `${#{N:-word}}`, which is
        # a bash "bad substitution" syntax error and broke any script whose
        # opaque wrapper landed on this branch.  These variants are all valid
        # bash and always true, while staying resistant to pattern matching.
        word = rng.choice([
            "/bin", "/usr", "/etc", "/tmp", "/dev", "/proc", "/sys",
            "/var", "/opt", "/lib", "/home", "/root", "/sbin",
        ])
        variant = rng.randint(0, 2)
        if variant == 0:
            # Prefix glob: a word always matches one of its own prefixes + '*'.
            prefix = word[:rng.randint(1, len(word))]
            return f'[[ "{word}" == {prefix}* ]]'
        if variant == 1:
            # Suffix glob: a word always matches '*' + one of its own suffixes.
            suffix = word[len(word) - rng.randint(1, len(word)):]
            return f'[[ "{word}" == *{suffix} ]]'
        # Byte-length check: printf writes exactly len(word) bytes.
        return f"[[ \"$(printf '%s' '{word}' | wc -c)\" -eq {len(word)} ]]"

    elif category == 2:
        # Environment/system checks — always true on Linux
        checks = [
            '[[ -d /proc/self ]]',
            '[[ -r /dev/null ]]',
            '[[ -e /dev/zero ]]',
            f'[[ $(( {rng.randint(1, 255)} & {rng.randint(1, 255)} | 1 )) -gt 0 ]]',
            f'[[ -n "${{BASH:-/bin/bash}}" ]]',
            f'[[ "${{BASH_VERSION:0:1}}" -gt 0 ]] 2>/dev/null || true && [[ 1 -eq 1 ]]',
        ]
        return rng.choice(checks)

    elif category == 3:
        # Negated false — less obvious than always-true
        a = rng.randint(100, 9999)
        b = rng.randint(1, 99)
        return f'! [[ $(( {a} % {b} + 1 )) -eq 0 ]]'

    else:
        # Mixed-operator arithmetic — harder for symbolic solvers
        x = rng.randint(1, 255)
        y = rng.randint(1, 255)
        result = (x | y) & 0xFF
        return f'[[ $(( ({x} | {y}) & 255 )) -eq {result} ]]'


def _has_variable_escape(node: dict) -> bool:
    """Check if a command modifies variables that escape its scope.

    Returns True for:
      - Any explicit assignment (name=value)
      - Declaration commands (local, declare, export, readonly, typeset)
        — even when bashlex stores the arguments as plain word nodes
        rather than assignment nodes.
    """
    # Fast path: declaration keywords always bind variables in the current
    # scope.  Wrapping in a subshell (...) would silently lose the binding.
    if node.get("type") == "command":
        parts = node.get("parts") or []
        if (parts and parts[0].get("type") == "word"
                and parts[0].get("value", "") in _DECLARATION_KEYWORDS):
            return True
    writes = _get_var_writes(node)
    return bool(writes)


def _wrap_subshell(node: dict) -> dict:
    """Wrap a command in a subshell."""
    return {
        "type": "compound",
        "kind": "(",
        "parts": [node],
        "pos": None,
    }


def _extract_functions(body: list[dict], rng: random.Random) -> list[dict]:
    """Extract random blocks into functions, then call them."""
    if len(body) < 4:
        return body

    # Pick 1-2 blocks to extract
    extractable = [
        i for i, node in enumerate(body)
        if (isinstance(node, dict)
            and node.get("type") == "command"
            and not _has_variable_escape(node)
            and not _mutates_shell_state(node))
    ]

    if not extractable:
        return body

    count = min(len(extractable), rng.randint(1, 2))
    chosen = rng.sample(extractable, count)

    new_body: list[dict] = []
    extracted_functions: list[dict] = []

    for i, node in enumerate(body):
        if i in chosen:
            # Create function
            fname = f"_blk_{rng.randint(0x100, 0xffff):04x}"
            func_def = {
                "type": "function_def",
                "name": fname,
                "body": {
                    "type": "compound",
                    "kind": "{",
                    "parts": [node],
                    "pos": None,
                },
                "pos": None,
            }
            extracted_functions.append(func_def)

            # Replace with function call
            call = {
                "type": "command",
                "parts": [{"type": "word", "value": fname, "pos": None}],
                "pos": None,
            }
            new_body.append(call)
        else:
            new_body.append(node)

    # Prepend extracted functions
    return extracted_functions + new_body
