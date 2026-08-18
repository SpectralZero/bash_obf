"""Static anti-regression analysis for emitted Bash source.

The analyzer intentionally reports conservative candidates rather than claiming
complete Bash data-flow proof. Dynamic expansion, sourced files, and eval can
make static liveness undecidable.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any

from obfush.engine.ast_parser import parse_bash


_COMMAND_TOKEN_RE = re.compile(
    r"(?m)(?:^|[;&|()]\s*)(?P<command>eval|xxd)(?=\s|$)"
)
_ASSIGNMENT_RE = re.compile(
    r"(?m)(?:^|[;({]\s*)"
    r"(?:(?:local|declare|typeset|readonly|export)(?:\s+-[A-Za-z]+)*\s+)?"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\+?="
)
_FUNCTION_DEF_RE = re.compile(
    r"(?m)(?:^|[;&|({]\s*)(?:function\s+)?"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\(\s*\)\s*\{"
)
_SPLIT_RECONSTRUCTION_RE = re.compile(
    r"\$\((?:[A-Za-z_][A-Za-z0-9_]*=\$'[^']*';\s*)+"
    r"printf\s+'%s'\s+\"\$\{",
)
_XOR_RECONSTRUCTION_RE = re.compile(
    r"\$\([^\n]*\$\(\([^\n]*\^[^\n]*\)\);\s*for\s+"
    r"[A-Za-z_][A-Za-z0-9_]*\s+in\s+(?:0x[0-9a-fA-F]{2}\s*)+;\s*do\s+"
    r"printf\s+-v",
)
_OPAQUE_CONSTANT_RE = re.compile(
    r"\$\(\([^\n]*?\+\s*0\)\)",
)
_CFF_DISPATCHER_RE = re.compile(
    r"while\s+\(\(\s*[A-Za-z_][A-Za-z0-9_]*\s*!=\s*0\s*\)\);\s*do\s*"
    r"case\s+\"\$\{[A-Za-z_][A-Za-z0-9_]*\}\"\s+in",
)
_LEGACY_PATTERNS = (
    re.compile(r"_[a-z]+_[0-9a-f]+_\d+"),
    re.compile(r"_(?:path|calc|ifaces|jnk|fn)_[A-Za-z0-9_]+"),
)
_QUOTED_LITERAL_RE = re.compile(
    r"\$?'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\"",
    re.DOTALL,
)


@dataclass(frozen=True)
class SourceAnalysis:
    source_bytes: int
    source_size_ratio: float | None
    source_sha256: str
    structure_sha256: str
    standalone_eval_count: int
    baseline_eval_count: int | None
    introduced_eval_count: int | None
    xxd_command_count: int
    baseline_xxd_command_count: int | None
    introduced_xxd_command_count: int | None
    legacy_fingerprint_count: int
    introduced_legacy_fingerprint_count: int | None
    split_reconstruction_count: int
    xor_reconstruction_count: int
    opaque_constant_count: int
    cff_dispatcher_count: int
    legacy_fingerprint_examples: list[str]
    assigned_variable_count: int
    assigned_never_read_candidates: list[str]
    function_definition_count: int
    uncalled_function_candidates: list[str]
    duplicate_literal_group_count: int
    duplicate_literal_occurrences: int
    duplicate_literal_examples: list[str]
    limitations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def analyze_source(
    source: str,
    original_size: int | None = None,
    baseline_source: str | None = None,
) -> SourceAnalysis:
    """Analyze emitted Bash for stable, testable anti-regression properties."""
    encoded = source.encode("utf-8")
    commands = Counter(match.group("command") for match in _COMMAND_TOKEN_RE.finditer(source))

    fingerprint_matches = sorted({
        match.group(0)
        for pattern in _LEGACY_PATTERNS
        for match in pattern.finditer(source)
    })
    baseline_commands = None
    baseline_fingerprints: set[str] | None = None
    if baseline_source is not None:
        baseline_commands = Counter(
            match.group("command") for match in _COMMAND_TOKEN_RE.finditer(baseline_source)
        )
        baseline_fingerprints = {
            match.group(0)
            for pattern in _LEGACY_PATTERNS
            for match in pattern.finditer(baseline_source)
        }

    assignments = _collect_assignments(source)
    dead_candidates = sorted(
        name for name, last_assignment_end in assignments.items()
        if not _has_later_reference(source, name, last_assignment_end)
    )

    functions = _collect_function_definitions(source)
    uncalled_functions = sorted(
        name for name, definition_end in functions.items()
        if not _has_later_command_call(source, name, definition_end)
    )

    duplicate_literals = _duplicate_literals(source)
    duplicate_occurrences = sum(count - 1 for _, count in duplicate_literals)

    ratio = None
    if original_size is not None and original_size > 0:
        ratio = len(encoded) / original_size

    return SourceAnalysis(
        source_bytes=len(encoded),
        source_size_ratio=ratio,
        source_sha256=hashlib.sha256(encoded).hexdigest(),
        structure_sha256=_structure_digest(source),
        standalone_eval_count=commands["eval"],
        baseline_eval_count=(
            baseline_commands["eval"] if baseline_commands is not None else None
        ),
        introduced_eval_count=(
            max(0, commands["eval"] - baseline_commands["eval"])
            if baseline_commands is not None else None
        ),
        xxd_command_count=commands["xxd"],
        baseline_xxd_command_count=(
            baseline_commands["xxd"] if baseline_commands is not None else None
        ),
        introduced_xxd_command_count=(
            max(0, commands["xxd"] - baseline_commands["xxd"])
            if baseline_commands is not None else None
        ),
        legacy_fingerprint_count=len(fingerprint_matches),
        introduced_legacy_fingerprint_count=(
            len(set(fingerprint_matches) - baseline_fingerprints)
            if baseline_fingerprints is not None else None
        ),
        split_reconstruction_count=len(_SPLIT_RECONSTRUCTION_RE.findall(source)),
        xor_reconstruction_count=len(_XOR_RECONSTRUCTION_RE.findall(source)),
        opaque_constant_count=len(_OPAQUE_CONSTANT_RE.findall(source)),
        cff_dispatcher_count=len(_CFF_DISPATCHER_RE.findall(source)),
        legacy_fingerprint_examples=fingerprint_matches[:10],
        assigned_variable_count=len(assignments),
        assigned_never_read_candidates=dead_candidates,
        function_definition_count=len(functions),
        uncalled_function_candidates=uncalled_functions,
        duplicate_literal_group_count=len(duplicate_literals),
        duplicate_literal_occurrences=duplicate_occurrences,
        duplicate_literal_examples=[literal for literal, _ in duplicate_literals[:10]],
        limitations=[
            "Liveness candidates do not model eval, namerefs, sourced files, or external consumers.",
            "Executable-token detection is lexical and intentionally conservative.",
            "Introduced-token counts subtract source-authored occurrences by count, not identity.",
            "Duplicate literals may be legitimate payload data, not generated decoys.",
            "The structure digest measures AST shape, not semantic or reverse-engineering difficulty.",
        ],
    )


def _collect_assignments(source: str) -> dict[str, int]:
    assignments: dict[str, int] = {}
    for match in _ASSIGNMENT_RE.finditer(source):
        assignments[match.group("name")] = match.end()
    return assignments


def _has_later_reference(source: str, name: str, start: int) -> bool:
    escaped = re.escape(name)
    reference = re.compile(
        rf"\$(?:{escaped}\b|\{{[!#]?{escaped}(?:\}}|[:/#\[]))"
    )
    return reference.search(source, start) is not None


def _collect_function_definitions(source: str) -> dict[str, int]:
    return {
        match.group("name"): match.end()
        for match in _FUNCTION_DEF_RE.finditer(source)
    }


def _has_later_command_call(source: str, name: str, start: int) -> bool:
    call = re.compile(
        rf"(?m)(?:^|[;&|({{]\s*){re.escape(name)}(?=\s|$|[;&|)])"
    )
    return call.search(source, start) is not None


def _duplicate_literals(source: str) -> list[tuple[str, int]]:
    literals = []
    for match in _QUOTED_LITERAL_RE.finditer(source):
        value = match.group(1) if match.group(1) is not None else match.group(2)
        if value is not None and len(value) >= 12:
            literals.append(value)
    counts = Counter(literals)
    return sorted(
        ((literal, count) for literal, count in counts.items() if count > 1),
        key=lambda item: (-item[1], item[0]),
    )


def _structure_digest(source: str) -> str:
    ast = parse_bash(source)

    def shape(node: Any) -> Any:
        if isinstance(node, dict):
            result: dict[str, Any] = {"type": node.get("type", "")}
            for key in ("kind", "op", "redirect_type", "original_style"):
                if key in node:
                    result[key] = node[key]
            for key in ("body", "parts", "test_parts"):
                if key in node:
                    result[key] = shape(node[key])
            return result
        if isinstance(node, list):
            return [shape(item) for item in node]
        return type(node).__name__

    payload = json.dumps(shape(ast), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
