"""Layer: replace safe decimal integers with equivalent Bash arithmetic."""

from __future__ import annotations

import random
import re

from obfush.layers.base import Layer, LayerConfig, LayerStats


# A digit run is an obfuscatable arithmetic literal only when it is NOT part of a
# parameter expansion or a base-N constant.  ``(?<![A-Za-z0-9_$#])`` rejects a
# preceding ``$`` (so ``$1`` is never rewritten), a preceding ``#`` (the digits of
# a ``16#ff`` / ``2#1010`` base constant, and ``${var#5}`` prefix patterns), and
# ``(?<!\$\{)`` rejects ``${1}`` / ``${10}``.  The trailing ``(?![A-Za-z0-9_#])``
# rejects a following ``#`` (the *base* of a ``16#ff`` constant, which must stay a
# literal 2-64).
_INTEGER_RE = re.compile(
    r"(?<![A-Za-z0-9_$#])(?<!\$\{)(?P<value>-?(?:0|[1-9][0-9]*))(?![A-Za-z0-9_#])"
)
_TEST_RE = re.compile(
    r"(?P<prefix>(?:^|\s)(?:-eq|-ne|-gt|-ge|-lt|-le)\s+)"
    r"(?P<value>-?(?:0|[1-9][0-9]*))(?P<suffix>(?=\s|\]|$))"
)
_REVERSE_TEST_RE = re.compile(
    r"(?P<prefix>(?:^|\s))(?P<value>-?(?:0|[1-9][0-9]*))"
    r"(?P<suffix>\s+(?:-eq|-ne|-gt|-ge|-lt|-le)(?=\s))"
)
_NUMERIC_COMMANDS = frozenset({"sleep", "exit", "return"})
_MAX_ABS_VALUE = 1_000_000_000


class LayerImpl(Layer):
    name = "opaque-const"
    description = "Equivalent arithmetic constants"

    def transform(self, ast: dict, config: LayerConfig) -> tuple[dict, LayerStats]:
        stats = LayerStats()
        transformed = _opaque_walk(ast, config, stats)
        return transformed, stats

    def estimate_size_increase(self, config: LayerConfig) -> float:
        return 1.0 + config.intensity * 0.35


def generate_opaque(target: int, rng: random.Random, *, wrapped: bool = True) -> str:
    """Generate a deterministic arithmetic expression equal to target."""
    strategy = rng.randrange(4)
    if strategy == 0:
        factor = rng.randint(2, 15)
        quotient, remainder = divmod(target, factor)
        expression = f"({factor} * {quotient} + {remainder})"
    elif strategy == 1:
        offset = rng.randint(17, 4096)
        expression = f"({target + offset} - {offset})"
    elif strategy == 2:
        mask = rng.randint(1, 0xFFFF)
        expression = f"(({target ^ mask}) ^ {mask})"
    else:
        decoy = rng.randint(-9999, 9999)
        expression = f"(1 ? {target} : {decoy})"
    if wrapped:
        # The +0 suffix is semantically neutral and gives static analysis a
        # reliable grammar marker without depending on balanced-parenthesis regexes.
        return f"$(({expression} + 0))"
    return expression


def _opaque_walk(node: dict, config: LayerConfig, stats: LayerStats) -> dict:
    if not isinstance(node, dict):
        return node
    stats.nodes_visited += 1

    node_type = node.get("type", "")
    if node_type == "command":
        _rewrite_command(node, config, stats)
    elif node_type == "test_expr":
        _rewrite_test_expr(node, config, stats)
    elif node_type == "word":
        _rewrite_raw_word(node, config, stats)

    for key in ("parts", "body", "test_parts"):
        value = node.get(key)
        if isinstance(value, list):
            node[key] = [
                _opaque_walk(item, config, stats) if isinstance(item, dict) else item
                for item in value
            ]
        elif isinstance(value, dict):
            node[key] = _opaque_walk(value, config, stats)
    return node


def _rewrite_command(node: dict, config: LayerConfig, stats: LayerStats) -> None:
    parts = node.get("parts") or []
    if not parts or not isinstance(parts[0], dict):
        return
    command = parts[0].get("value", "")
    if command not in _NUMERIC_COMMANDS:
        return
    for part in parts[1:]:
        if not isinstance(part, dict) or part.get("type") != "word":
            continue
        value = part.get("value", "")
        if _eligible_integer(value) and _selected(config):
            part["value"] = generate_opaque(int(value), config.rng)
            part.pop("raw", None)
            _record(stats)


def _rewrite_test_expr(node: dict, config: LayerConfig, stats: LayerStats) -> None:
    parts = node.get("test_parts") or []
    for index, part in enumerate(parts):
        if not isinstance(part, dict) or part.get("type") != "word":
            continue
        previous = parts[index - 1].get("value", "") if index else ""
        following = parts[index + 1].get("value", "") if index + 1 < len(parts) else ""
        if (previous in {"-eq", "-ne", "-gt", "-ge", "-lt", "-le"}
                or following in {"-eq", "-ne", "-gt", "-ge", "-lt", "-le"}):
            value = part.get("value", "")
            if _eligible_integer(value) and _selected(config):
                part["value"] = generate_opaque(int(value), config.rng)
                part.pop("raw", None)
                _record(stats)


def _rewrite_raw_word(node: dict, config: LayerConfig, stats: LayerStats) -> None:
    value = node.get("value", "")
    if not isinstance(value, str) or not node.get("raw"):
        return

    rewritten = value
    if _is_arithmetic_construct(value):
        rewritten = _replace_arithmetic_literals(value, config, stats)
    elif _is_numeric_test_construct(value):
        rewritten = _replace_test_literals(value, config, stats)

    if rewritten != value:
        node["value"] = rewritten
        node["raw"] = rewritten


def _replace_arithmetic_literals(
    value: str,
    config: LayerConfig,
    stats: LayerStats,
) -> str:
    def replace(match: re.Match) -> str:
        literal = match.group("value")
        if not _eligible_integer(literal) or not _selected(config):
            return literal
        _record(stats)
        return generate_opaque(int(literal), config.rng, wrapped=False)

    return _INTEGER_RE.sub(replace, value)


def _replace_test_literals(value: str, config: LayerConfig, stats: LayerStats) -> str:
    def replace(match: re.Match) -> str:
        literal = match.group("value")
        if not _eligible_integer(literal) or not _selected(config):
            return match.group(0)
        _record(stats)
        return (
            f"{match.group('prefix')}"
            f"{generate_opaque(int(literal), config.rng)}"
            f"{match.group('suffix')}"
        )

    rewritten = _TEST_RE.sub(replace, value)
    return _REVERSE_TEST_RE.sub(replace, rewritten)


def _is_arithmetic_construct(value: str) -> bool:
    stripped = value.strip()
    return (
        stripped.startswith("((") and stripped.endswith(")")
        or stripped.startswith("$((") and stripped.endswith("))")
    )


def _is_numeric_test_construct(value: str) -> bool:
    stripped = value.strip()
    return (
        stripped.startswith("[[") and stripped.endswith("]]" )
        or stripped.startswith("[ ") and stripped.endswith(" ]")
        or stripped.startswith("test ")
    ) and not any(token in value for token in ("=~", "==", "!="))


def _eligible_integer(value: str) -> bool:
    if not re.fullmatch(r"-?(?:0|[1-9][0-9]*)", value):
        return False
    return abs(int(value)) <= _MAX_ABS_VALUE


def _selected(config: LayerConfig) -> bool:
    return config.rng.random() < (0.35 + config.intensity * 0.65)


def _record(stats: LayerStats) -> None:
    stats.nodes_modified += 1
    stats.custom["constants_obfuscated"] = str(
        int(stats.custom.get("constants_obfuscated", "0")) + 1
    )
