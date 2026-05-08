"""
Layer 1: Identifier Mangling

Replaces every variable, function, and alias name with an unpredictable string.
Reserved words and special variables are preserved.
"""

from __future__ import annotations

import random
import re
import string
from typing import Any

from obfush.layers.base import Layer, LayerConfig, LayerStats
from obfush.utils.bash_keywords import (
    RESERVED_WORDS, SPECIAL_VARIABLES, BUILTIN_COMMANDS,
    COMMON_EXTERNALS, DECEPTIVE_WORDS,
)


class LayerImpl(Layer):
    name = "id-mangle"
    description = "Variable & function name randomisation"

    def transform(self, ast: dict, config: LayerConfig) -> tuple[dict, LayerStats]:
        stats = LayerStats()
        rng = config.rng

        # Step 1: Collect all identifiers
        identifiers = _collect_identifiers(ast)
        stats.nodes_visited = len(identifiers)

        # Step 2: Build the mangling map
        pool = _select_pool(rng, config.intensity)
        mangle_map = _build_mangle_map(identifiers, rng, pool)
        stats.identifiers_mangled = len(mangle_map)

        # Step 3: Apply the map to the AST
        ast = _apply_mangle_map(ast, mangle_map)
        stats.nodes_modified = stats.identifiers_mangled

        return ast, stats

    def estimate_size_increase(self, config: LayerConfig) -> float:
        return 1.1  # names may be slightly longer


# -- Text-pattern regexes (shared by collection + application) ----------------
# These are used both for structured AST traversal AND for opaque-blob
# fallback, where the entire script is a single text node.

# Assignment LHS: name=val, name+=val, declare name=val, etc.
# IMPORTANT: boundary is line-start (with optional leading whitespace) OR
# a TRUE statement separator (`;`, `&`, `|`, `(`). Spaces alone don't count
# -- otherwise literal text in echoed strings like `"summary: total=$total"`
# would match `total=` as if it were an assignment.
_ASSIGN_LHS_RE = re.compile(
    r'(?m)(^[ \t]*|[;&|(][ \t]*)'
    r'((?:declare(?:\s+-[aAilrtuxn]+)?\s+|local\s+|export\s+|readonly\s+|typeset\s+)?)'
    r'([a-zA-Z_]\w*)(\+?=|\[\w+\]=)'
)
# for-loop iterator: for NAME in ... | for (( NAME=... ))
# Strict: require `in` keyword (list form) OR `((` (C-style) so that
# literal text `"for loop (list)"` in echo strings doesn't match.
_FOR_ITER_RE = re.compile(
    r'(?m)\bfor\s+'
    r'(?:\(\(\s*([a-zA-Z_]\w*)'    # group 1: C-style  for (( var = ... ))
    r'|([a-zA-Z_]\w*)\s+in\b)'      # group 2: list-style  for var in ...
)
# Function definition: function NAME() { ... } | NAME() { ... }
_FUNC_DEF_RE = re.compile(
    r'(?m)(^|[\s;&])(?:function\s+([a-zA-Z_]\w*)|([a-zA-Z_]\w*)\s*\(\s*\))'
)
# Command call at statement position: line-start or after a true statement
# separator, followed by an identifier and a non-letter (space/redirect/end).
# Used in opaque-blob mode to rename function call sites. The lookup against
# mangle_map filters out builtins/externals so only user-defined names match.
_CMD_CALL_RE = re.compile(
    r'(?m)(^[ \t]*|[;&|(][ \t]*|(?:&&|\|\|)[ \t]*)'
    r'([a-zA-Z_]\w*)(?=[ \t]|$|;|&|\||\)|\n)'
)
# Bare name after a declaration keyword (no '=' present):
#   declare -A colors       declare -i count
#   local var               export MYVAR
# Used in opaque-blob mode to collect and rename these definitions.
_DECLARE_BARE_RE = re.compile(
    r'(?m)((?:declare|local|typeset|readonly|export)'
    r'(?:\s+-[a-zA-Z]+)*'
    r'\s+)'
    r'([a-zA-Z_]\w*)'
    r'(?![=\[])'
)
# Indirect reference values in assignments:  ="identifier", ='identifier',
# or =identifier (unquoted).  Renames the RHS when it is exactly a known
# mangled name (function-pointer / eval-indirect patterns).
# Negative lookbehind prevents false-matching on == and != operators.
_ASSIGN_INDIRECT_RE = re.compile(
    r'(?<![=!<>])=\s*'
    r'(?:"([a-zA-Z_]\w*)"'
    r"|'([a-zA-Z_]\w*)'"
    r'|([a-zA-Z_]\w*))'
    r'(?=[\s;&|\n)"\']|$)'
)


def _collect_identifiers_from_text(text: str) -> set[str]:
    """Extract defined identifiers from raw source text.

    Used as fallback when bashlex fails and the script is an opaque
    blob.  Uses the same regexes that the application phase uses,
    so collection and application are always in sync.
    """
    found: set[str] = set()

    # Assignment LHS
    for m in _ASSIGN_LHS_RE.finditer(text):
        name = m.group(3)
        if name and _is_mangleable(name):
            found.add(name)

    # Function definitions
    for m in _FUNC_DEF_RE.finditer(text):
        name = m.group(2) or m.group(3)
        if name and _is_mangleable(name):
            found.add(name)

    # for-loop iterators (group 1 = C-style, group 2 = list-style)
    for m in _FOR_ITER_RE.finditer(text):
        name = m.group(1) or m.group(2)
        if name and _is_mangleable(name):
            found.add(name)

    # Bare names in declaration statements (declare -A name, local var, etc.)
    for m in _DECLARE_BARE_RE.finditer(text):
        name = m.group(2)
        if name and _is_mangleable(name):
            found.add(name)

    return found


def _collect_identifiers(ast: dict) -> set[str]:
    """Walk AST and collect all user-defined identifiers.

    Only identifiers that are **defined** somewhere in the script (via
    assignment, function definition, or declaration keyword) are returned.
    Free references -- names that appear in ``var_refs`` but are never
    assigned -- are excluded.

    If the AST is an opaque blob (single word node with ``raw`` set),
    falls back to regex-based text scanning.
    """
    # Detect opaque-blob mode: body is a single word node with raw text
    body = ast.get("body", [])
    if (len(body) == 1
            and isinstance(body[0], dict)
            and body[0].get("type") == "word"
            and body[0].get("raw") is not None):
        return _collect_identifiers_from_text(body[0]["raw"])

    defined: set[str] = set()
    referenced: set[str] = set()

    def _walk(node: dict) -> None:
        if not isinstance(node, dict):
            return

        # Assignments -- LHS is a definition
        if node.get("type") == "assignment":
            name = node.get("name", "")
            if name and _is_mangleable(name):
                defined.add(name)

        # Function definitions
        if node.get("type") == "function_def":
            name = node.get("name", "")
            if name and _is_mangleable(name):
                defined.add(name)

        # Local/declare/export/readonly/typeset declarations
        if node.get("type") == "command":
            parts = node.get("parts", [])
            if (parts and parts[0].get("type") == "word"
                    and parts[0].get("value") in ("local", "declare", "typeset", "readonly", "export")):
                for part in parts[1:]:
                    val = part.get("value", "") if part.get("type") == "word" else ""
                    if "=" in val:
                        name = val.split("=")[0].lstrip("-")
                        if name and not name.startswith("-") and _is_mangleable(name):
                            defined.add(name)
                    elif val and not val.startswith("-") and _is_mangleable(val):
                        defined.add(val)
                    if part.get("type") == "assignment":
                        name = part.get("name", "")
                        if name and _is_mangleable(name):
                            defined.add(name)

        # Variable references -- collect but don't add to final set yet
        for ref in node.get("var_refs", []):
            if _is_mangleable(ref):
                referenced.add(ref)

        # Recurse
        for key in ("parts", "body", "test_parts"):
            val = node.get(key)
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        _walk(item)
            elif isinstance(val, dict):
                _walk(val)

    _walk(ast)
    return defined


def _is_mangleable(name: str) -> bool:
    """Check if an identifier is safe to mangle."""
    if not isinstance(name, str):
        return False
    if not name or not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name):
        return False
    if name in RESERVED_WORDS:
        return False
    if name in SPECIAL_VARIABLES:
        return False
    if name in BUILTIN_COMMANDS:
        return False
    if name in COMMON_EXTERNALS:
        return False
    # Don't mangle PATH-like env vars that external tools depend on
    if name.isupper() and len(name) > 1:
        return False
    return True


def _select_pool(rng: random.Random, intensity: float) -> str:
    """Select the naming pool based on RNG and intensity."""
    if intensity >= 0.9:
        return rng.choice(["hex", "deceptive", "mixed"])
    elif intensity >= 0.5:
        return rng.choice(["hex", "deceptive"])
    else:
        return "deceptive"


def _generate_hex_name(rng: random.Random, existing: set[str]) -> str:
    """Generate a hex-style name like _0x7f3a."""
    while True:
        value = rng.randint(0x0000, 0xFFFF)
        name = f"_0x{value:04x}"
        if name not in existing:
            return name


def _generate_deceptive_name(rng: random.Random, existing: set[str], pool: list[str]) -> str:
    """Pick a deceptive name from the pool."""
    available = [w for w in pool if w not in existing]
    if available:
        return rng.choice(available)
    # Exhausted pool — fall back to hex
    return _generate_hex_name(rng, existing)


def _build_mangle_map(
    identifiers: set[str],
    rng: random.Random,
    pool: str,
) -> dict[str, str]:
    """Build a mapping of original name → mangled name."""
    mangle_map: dict[str, str] = {}
    used_names: set[str] = set()

    deceptive_pool = list(DECEPTIVE_WORDS)
    rng.shuffle(deceptive_pool)

    for name in sorted(identifiers):  # sorted for determinism
        if pool == "hex":
            new_name = _generate_hex_name(rng, used_names)
        elif pool == "deceptive":
            new_name = _generate_deceptive_name(rng, used_names, deceptive_pool)
        elif pool == "mixed":
            if rng.random() < 0.5:
                new_name = _generate_hex_name(rng, used_names)
            else:
                new_name = _generate_deceptive_name(rng, used_names, deceptive_pool)
        else:
            new_name = _generate_hex_name(rng, used_names)

        mangle_map[name] = new_name
        used_names.add(new_name)

    return mangle_map


def _apply_mangle_map(ast: dict, mangle_map: dict[str, str]) -> dict:
    """Walk AST and replace all identifiers according to the map."""
    if not mangle_map:
        return ast

    # Replace ONLY in expansion contexts:
    #   $name, ${name}, ${name:-x}, ${!name}, ${#name}, ${name#pat}, etc.
    # AND inside arithmetic expansion: $((...)), $[...], (( ... ))
    # Bare identifiers in literal text (e.g. inside "x ($x) > 5") are LEFT ALONE.
    param_pattern = re.compile(
        r'\$\{[!#]?([a-zA-Z_]\w*)'   # ${name, ${!name, ${#name
        r'|\$([a-zA-Z_]\w*)'         # $name
    )
    arith_pattern = re.compile(r'\$\(\((.*?)\)\)', re.DOTALL)
    arith_alt_pattern = re.compile(r'\$\[(.*?)\]', re.DOTALL)
    # Standalone arithmetic command:  (( ... ))   — must not match $(()) (handled above)
    arith_cmd_pattern = re.compile(r'(?<!\$)\(\((.*?)\)\)', re.DOTALL)
    bare_id = re.compile(r'\b([a-zA-Z_]\w*)\b')
    # Assignment LHS — at start of any line (after optional indent) OR at start of token.
    # Matches:  name=val,  name+=val,  name[i]=val,  declare name=val,  for name in ...
    # MULTILINE so it scans every line in opaque-blob fallback case too.
    # Group 1 = boundary, Group 2 = optional keyword (declare/local/etc.) — captured
    # so we can put it back, Group 3 = identifier, Group 4 = operator.
    assign_lhs_pattern = _ASSIGN_LHS_RE
    for_iter_pattern = _FOR_ITER_RE
    func_def_pattern = _FUNC_DEF_RE

    def _mangle_arith_inner(inner: str) -> str:
        return bare_id.sub(
            lambda m: mangle_map.get(m.group(1), m.group(1)),
            inner,
        )

    def _mangle_string(s: str) -> str:
        """Replace identifiers only in expansion / arithmetic / assignment contexts.

        Multiline-safe: scans every line so it works correctly both for
        per-node word values AND for the opaque-blob fallback (whole script
        in a single word when bashlex can't parse it).
        """
        # 0a. Assignment LHS — handles  name=,  name+=,  name[i]=,
        #                    declare/local/export/readonly/typeset NAME=
        def _assign_repl(m: re.Match) -> str:
            boundary, keyword, name, op = m.group(1), m.group(2), m.group(3), m.group(4)
            if name in mangle_map:
                return f"{boundary}{keyword}{mangle_map[name]}{op}"
            return m.group(0)
        s = assign_lhs_pattern.sub(_assign_repl, s)

        # 0a'. Bare names in declaration statements (declare -A name, etc.)
        def _declare_bare_repl(m: re.Match) -> str:
            prefix, name = m.group(1), m.group(2)
            if name in mangle_map:
                return f"{prefix}{mangle_map[name]}"
            return m.group(0)
        s = _DECLARE_BARE_RE.sub(_declare_bare_repl, s)

        # 0a''. Indirect reference values: ="ident", ='ident', =ident
        #       Renames the RHS when it is exactly a known identifier.
        def _indirect_repl(m: re.Match) -> str:
            full = m.group(0)
            name = m.group(1) or m.group(2) or m.group(3)
            if name and name in mangle_map:
                return full.replace(name, mangle_map[name], 1)
            return full
        s = _ASSIGN_INDIRECT_RE.sub(_indirect_repl, s)

        # 0b. for-loop iterator:  for NAME in ...   |   for (( NAME=... ))
        def _for_repl(m: re.Match) -> str:
            full = m.group(0)
            # Group 1 is C-style (match ends right after the name);
            # group 2 is list-style (match continues through ` in`).
            if m.group(1) and m.group(1) in mangle_map:
                name = m.group(1)
                # Match ends with the name token in C-style.
                return full[: -len(name)] + mangle_map[name]
            if m.group(2) and m.group(2) in mangle_map:
                name = m.group(2)
                # List-style: match is ``for NAME ... in``. Replace the
                # captured name in place rather than splicing the tail.
                return full.replace(name, mangle_map[name], 1)
            return full
        s = for_iter_pattern.sub(_for_repl, s)

        # 0c. Function definition:  function NAME() {…}  |  NAME() {…}
        def _func_repl(m: re.Match) -> str:
            name = m.group(2) or m.group(3)
            if name and name in mangle_map:
                full = m.group(0)
                # Replace only the name token; keep the sep and parens
                return full.replace(name, mangle_map[name], 1)
            return m.group(0)
        s = func_def_pattern.sub(_func_repl, s)

        # 0d. Function calls inside $(...): $(func_name ...)
        #     The first word after $( is the command name.
        _cmd_sub_call = re.compile(
            r'\$\(\s*([a-zA-Z_]\w*)'
        )
        def _cmd_sub_repl(m: re.Match) -> str:
            name = m.group(1)
            if name in mangle_map:
                full = m.group(0)
                return full[: -len(name)] + mangle_map[name]
            return m.group(0)
        s = _cmd_sub_call.sub(_cmd_sub_repl, s)

        # 0e. Function call sites at statement position (opaque-blob mode).
        #     `funcname args` where funcname is a user-defined function.
        #     Builtins/externals are filtered automatically because they're
        #     never added to mangle_map by _is_mangleable.
        def _cmd_call_repl(m: re.Match) -> str:
            boundary, name = m.group(1), m.group(2)
            if name in mangle_map:
                return f"{boundary}{mangle_map[name]}"
            return m.group(0)
        s = _CMD_CALL_RE.sub(_cmd_call_repl, s)

        # 1. Arithmetic expansion: rename bare identifiers within $((...))
        def _arith_repl(m: re.Match) -> str:
            return f"$(({_mangle_arith_inner(m.group(1))}))"
        s = arith_pattern.sub(_arith_repl, s)
        # 2. Older-style arithmetic: $[...]
        def _arith_alt_repl(m: re.Match) -> str:
            return f"$[{_mangle_arith_inner(m.group(1))}]"
        s = arith_alt_pattern.sub(_arith_alt_repl, s)

        # 3. Standalone arithmetic command: (( ... ))
        def _arith_cmd_repl(m: re.Match) -> str:
            return f"(({_mangle_arith_inner(m.group(1))}))"
        s = arith_cmd_pattern.sub(_arith_cmd_repl, s)

        # 4. Parameter expansion: $name and ${...name...}
        def _param_repl(m: re.Match) -> str:
            name = m.group(1) or m.group(2)
            if name in mangle_map:
                full = m.group(0)
                # Replace the trailing identifier portion only
                return full[: -len(name)] + mangle_map[name]
            return m.group(0)
        return param_pattern.sub(_param_repl, s)

    def _walk(node: dict) -> dict:
        if not isinstance(node, dict):
            return node

        # Assignment names
        if node.get("type") == "assignment":
            name = node.get("name", "")
            if name in mangle_map:
                node["name"] = mangle_map[name]
            # Mangle value if it's a string
            if isinstance(node.get("value"), str):
                val = node["value"]
                mangled_val = _mangle_string(val)
                # Indirect reference: if the entire value is exactly a
                # user-defined identifier (e.g. func="worker_a", or
                # var_name="myvar"), rename it.  This preserves eval,
                # indirect expansion, and function-pointer patterns.
                if mangled_val in mangle_map:
                    mangled_val = mangle_map[mangled_val]
                node["value"] = mangled_val

        # Function definition names
        if node.get("type") == "function_def":
            name = node.get("name", "")
            if name in mangle_map:
                node["name"] = mangle_map[name]

        # Function call: command whose first word is an exact identifier
        # in the mangle map (i.e., the user-defined function name).
        # Also: rename variable names in declare/local/export/typeset.
        if node.get("type") == "command":
            parts = node.get("parts") or []
            if parts:
                first = parts[0]
                if isinstance(first, dict) and first.get("type") == "word":
                    cmd = first.get("value", "")

                    # Function call rename
                    if cmd in mangle_map:
                        first["value"] = mangle_map[cmd]

                    # Declaration commands: rename bare variable names
                    # e.g. declare -A colors -> declare -A _version
                    elif cmd in ("local", "declare", "typeset", "readonly", "export"):
                        for part in parts[1:]:
                            if not isinstance(part, dict) or part.get("type") != "word":
                                continue
                            val = part.get("value", "")
                            if val.startswith("-"):
                                continue  # skip flags like -A, -i
                            if "=" in val:
                                # name=value or name+=value
                                eq_pos = val.index("=")
                                lhs = val[:eq_pos].rstrip("+")
                                if lhs in mangle_map:
                                    part["value"] = mangle_map[lhs] + val[len(lhs):]
                            elif val in mangle_map:
                                # bare name: declare -A name
                                part["value"] = mangle_map[val]

        # Word values (variable references, command arguments)
        if node.get("type") == "word":
            value = node.get("value", "")
            if value:
                node["value"] = _mangle_string(value)
            # Update var_refs annotation
            if "var_refs" in node:
                node["var_refs"] = [
                    mangle_map.get(r, r) for r in node["var_refs"]
                ]

        # Expansion parameter names
        if node.get("type") == "expansion" and node.get("kind") == "parameter":
            value = node.get("value", "")
            if value in mangle_map:
                node["value"] = mangle_map[value]
            if "var_name" in node and node["var_name"] in mangle_map:
                node["var_name"] = mangle_map[node["var_name"]]

        # Recurse into children
        for key in ("parts", "body", "test_parts"):
            val = node.get(key)
            if isinstance(val, list):
                node[key] = [_walk(i) if isinstance(i, dict) else i for i in val]
            elif isinstance(val, dict):
                node[key] = _walk(val)

        return node

    # Update scope info
    scope = ast.get("_scope")
    if scope:
        scope["globals"] = {mangle_map.get(n, n) for n in scope.get("globals", set())}
        scope["assignments"] = {mangle_map.get(n, n) for n in scope.get("assignments", set())}
        scope["reads"] = {mangle_map.get(n, n) for n in scope.get("reads", set())}
        new_locals = {}
        for func, vars_ in scope.get("locals", {}).items():
            new_func = mangle_map.get(func, func)
            new_locals[new_func] = {mangle_map.get(v, v) for v in vars_}
        scope["locals"] = new_locals

    return _walk(ast)
