"""Conservative control-flow flattening for safe straight-line Bash regions."""

from __future__ import annotations

import re

from obfush.layers.base import Layer, LayerConfig, LayerStats


_MIN_BLOCKS = 3
_MAX_BLOCKS = 8
_SAFE_COMMANDS = frozenset({":", "true", "echo", "printf"})
_STATUS_OR_INTROSPECTION_RE = re.compile(
    r"\$\?|\$\{?PIPESTATUS|\$\{?BASH_COMMAND|\$\{?BASH_LINENO|"
    r"\$\{?LINENO|\$\{?FUNCNAME|\$\{?BASH_SOURCE|\$\{?RANDOM|\$\{?SECONDS"
)
_GLOBAL_EXCLUSION_RE = re.compile(
    r"(?m)(?:^|[;&|]\s*)"
    r"(?:trap\b|set\s+(?:-[A-Za-z]*[ex][A-Za-z]*|-o\s+(?:errexit|xtrace))|"
    r"shopt\s+-s\s+extdebug)"
)


class LayerImpl(Layer):
    name = "cff"
    description = "Straight-line state-machine dispatch"

    def transform(self, ast: dict, config: LayerConfig) -> tuple[dict, LayerStats]:
        stats = LayerStats()
        if config.name_pool is None:
            stats.custom["skipped"] = "name-pool-unavailable"
            return ast, stats

        from obfush.engine.ast_emitter import emit

        source = emit(ast)
        if _GLOBAL_EXCLUSION_RE.search(source) or _STATUS_OR_INTROSPECTION_RE.search(source):
            stats.custom["skipped"] = "status-or-debug-sensitive"
            return ast, stats

        ast = _flatten_walk(ast, config, stats, depth=0)
        return ast, stats

    def estimate_size_increase(self, config: LayerConfig) -> float:
        return 1.0 + config.intensity * 1.0


def _flatten_walk(
    node: dict,
    config: LayerConfig,
    stats: LayerStats,
    depth: int,
) -> dict:
    if not isinstance(node, dict):
        return node
    stats.nodes_visited += 1

    if node.get("type") == "script" and isinstance(node.get("body"), list):
        node["body"] = _flatten_statement_list(node["body"], config, stats)

    # Synthetic function/brace bodies can expose direct statement lists.
    if depth < 2 and node.get("type") == "compound" and node.get("kind") in {"{", "group"}:
        parts = node.get("parts")
        if isinstance(parts, list) and all(_is_statement_node(part) for part in parts):
            node["parts"] = _flatten_statement_list(parts, config, stats)

    for key in ("body", "parts"):
        value = node.get(key)
        if isinstance(value, dict):
            node[key] = _flatten_walk(value, config, stats, depth + 1)
        elif isinstance(value, list):
            node[key] = [
                _flatten_walk(item, config, stats, depth + 1)
                if isinstance(item, dict) and not item.get("_cff") else item
                for item in value
            ]
    return node


def _flatten_statement_list(
    statements: list,
    config: LayerConfig,
    stats: LayerStats,
) -> list:
    result: list = []
    group: list[dict] = []

    def flush() -> None:
        nonlocal group
        while len(group) >= _MIN_BLOCKS:
            width = min(_MAX_BLOCKS, len(group))
            chunk = group[:width]
            result.append(_build_dispatcher(chunk, config, stats))
            group = group[width:]
        result.extend(group)
        group = []

    for statement in statements:
        if isinstance(statement, dict) and _is_eligible_statement(statement):
            group.append(statement)
        else:
            flush()
            result.append(statement)
    flush()
    return result


def _build_dispatcher(
    statements: list[dict],
    config: LayerConfig,
    stats: LayerStats,
) -> dict:
    from obfush.engine.ast_emitter import emit

    if config.name_pool is None:
        raise ValueError("cff requires a shared name pool")
    state_name = config.name_pool.next_name()
    real_states = _unique_states(len(statements) - 1, config.rng)
    router_count = max(1, round((len(statements) - 1) * 0.3))
    router_states = _unique_states(router_count, config.rng, exclude=set(real_states))

    path: list[tuple[str, int]] = []
    router_iter = iter(router_states)
    for index, state in enumerate(real_states):
        path.append(("real", state))
        if index < router_count:
            path.append(("router", next(router_iter)))

    arms: list[tuple[int, str]] = []
    real_index = 0
    for path_index, (kind, state) in enumerate(path):
        next_state = path[path_index + 1][1] if path_index + 1 < len(path) else 0
        if kind == "real":
            statement = emit({"type": "script", "body": [statements[real_index]]}).strip()
            real_index += 1
            body = f"{statement}\n{state_name}={next_state}"
        else:
            body = f": \"${{{state_name}}}\"\n{state_name}={next_state}"
        arms.append((state, body))
    config.rng.shuffle(arms)

    lines = [
        f"{state_name}={path[0][1]}",
        f"while (( {state_name} != 0 )); do",
        f"case \"${{{state_name}}}\" in",
    ]
    for state, body in arms:
        lines.extend((f"{state})", body, ";;"))
    lines.extend((
        f"*) {state_name}=0 ;;",
        "esac",
        "done",
        f"unset {state_name}",
        emit({"type": "script", "body": [statements[-1]]}).strip(),
    ))

    stats.nodes_modified += len(statements)
    stats.custom["dispatchers_created"] = str(
        int(stats.custom.get("dispatchers_created", "0")) + 1
    )
    stats.custom["blocks_flattened"] = str(
        int(stats.custom.get("blocks_flattened", "0")) + len(statements)
    )
    stats.custom["router_states"] = str(
        int(stats.custom.get("router_states", "0")) + router_count
    )
    return {
        "type": "word",
        "value": "\n".join(lines),
        "raw": "\n".join(lines),
        "pos": None,
        "_cff": True,
    }


def _unique_states(count: int, rng, exclude: set[int] | None = None) -> list[int]:
    used = set(exclude or ())
    states: list[int] = []
    while len(states) < count:
        state = rng.randint(11, 9999)
        if state not in used:
            used.add(state)
            states.append(state)
    return states


def _is_statement_node(node) -> bool:
    return isinstance(node, dict) and node.get("type") in {
        "command", "assignment", "pipeline", "list", "compound", "function_def", "word",
    }


def _is_eligible_statement(node: dict) -> bool:
    """Check if a statement is eligible for CFF flattening.

    Much more permissive than before: allows any command without redirects
    or operators, and any standalone assignment.  The key restrictions are:
    - No status/introspection references ($?, PIPESTATUS, etc.)
    - No _cff-tagged nodes (already flattened)
    - No redirects or operators (I/O reordering breaks semantics)
    """
    if node.get("_cff"):
        return False

    node_type = node.get("type", "")

    # Standalone assignments are always safe to reorder within a dispatcher
    if node_type == "assignment":
        value = str(node.get("value", ""))
        return not _STATUS_OR_INTROSPECTION_RE.search(value)

    if node_type != "command":
        return False

    parts = node.get("parts") or []
    if not parts or any(not isinstance(part, dict) for part in parts):
        return False

    # No redirects or operators
    if any(part.get("type") in {"redirect", "operator"} for part in parts):
        return False

    # No status/introspection variables
    rendered_values = [str(part.get("value", "")) for part in parts]
    if _STATUS_OR_INTROSPECTION_RE.search(" ".join(rendered_values)):
        return False

    # Pure assignment commands (all parts are assignments)
    if all(part.get("type") == "assignment" for part in parts):
        return all(
            "$(" not in str(part.get("value", ""))
            and "`" not in str(part.get("value", ""))
            for part in parts
        )

    # Any command with a word-type first part is eligible
    # (previously restricted to only echo/printf/true/:)
    first = parts[0]
    if first.get("type") != "word":
        return False

    # Exclude control flow / scope-modifying commands
    cmd = first.get("value", "")
    if cmd in {"exit", "return", "break", "continue", "trap", "exec",
               "shift", ".", "source", "set", "shopt", "eval",
               "local", "declare", "typeset", "readonly", "export",
               "cd", "pushd", "popd", "ulimit", "umask",
               "read", "wait", "getopts", "mapfile", "readarray"}:
        return False

    return True
