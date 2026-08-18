"""Edge coverage for the bash AST parser and emitter."""

from __future__ import annotations

import shutil
import subprocess
from types import SimpleNamespace

import pytest

from obfush.engine import ast_parser
from obfush.engine.ast_emitter import emit


# Keep the subprocess tests portable to environments that only run the Python
# parser tests.  The parser itself does not require an installed Bash binary.
BASH = shutil.which("bash")


def _find_nodes(node: object, node_type: str) -> list[dict]:
    found: list[dict] = []
    if isinstance(node, dict):
        if node.get("type") == node_type:
            found.append(node)
        for value in node.values():
            found.extend(_find_nodes(value, node_type))
    elif isinstance(node, list):
        for value in node:
            found.extend(_find_nodes(value, node_type))
    return found


def _run_bash(source: str) -> subprocess.CompletedProcess[bytes]:
    if BASH is None:
        pytest.skip("bash is unavailable")
    syntax = subprocess.run(
        [BASH, "-n"], input=source.encode(), capture_output=True, timeout=10,
    )
    assert syntax.returncode == 0, f"{syntax.stderr.decode()}\n{source}"
    return subprocess.run(
        [BASH], input=source.encode(), capture_output=True, timeout=10,
    )


def _word(value: str, *, raw: bool = False) -> dict:
    node = {"type": "word", "value": value, "pos": None}
    if raw:
        node["raw"] = value
    return node


def _command(*values: str) -> dict:
    return {"type": "command", "parts": [_word(value) for value in values], "pos": None}


def test_parser_converts_redirects_and_file_descriptor_targets():
    ast = ast_parser.parse_bash("cat < input > output 2>&1")

    redirects = _find_nodes(ast, "redirect")
    assert [node["redirect_type"] for node in redirects] == ["<", ">", ">&"]
    assert redirects[0]["target"]["value"] == "input"
    assert redirects[1]["target"]["value"] == "output"
    assert redirects[2]["fd"] == 2
    assert redirects[2]["target"] == "1"

    result = _run_bash(emit(ast_parser.parse_bash("cat < /dev/null > /dev/null 2>&1")))
    assert result.returncode == 0, result.stderr.decode()


def test_parser_preserves_heredoc_metadata_and_emitter_handles_synthetic_heredoc():
    ast = ast_parser.parse_bash("cat <<EOF\npayload $HOME\nEOF")
    redirect = _find_nodes(ast, "redirect")[0]

    assert redirect["redirect_type"] == "<<"
    assert redirect["target"]["value"] == "EOF"
    assert redirect["heredoc"]["delimiter"] == "EOF"
    assert redirect["heredoc"]["body"].startswith("payload $HOME")

    synthetic = {
        "type": "script",
        "body": [{
            "type": "command",
            "parts": [
                _word("cat"),
                {
                    "type": "redirect", "redirect_type": "<<", "target": "EOF",
                    "fd": None, "heredoc": {"delimiter": "EOF", "body": "payload"},
                },
            ],
        }],
    }
    result = _run_bash(emit(synthetic))
    assert result.returncode == 0
    assert result.stdout == b"payload\n"


def test_command_and_process_substitutions_have_recursive_command_parts():
    command_ast = ast_parser.parse_bash("printf '%s\\n' \"$(printf nested)\"")
    substitutions = _find_nodes(command_ast, "expansion")
    assert [node["kind"] for node in substitutions] == ["command_sub"]
    assert substitutions[0]["parts"][0]["type"] == "command"
    command_result = _run_bash(emit(command_ast))
    assert command_result.stdout == b"nested\n"

    process_ast = ast_parser.parse_bash("cat <(printf '%s\\n' process)")
    process = _find_nodes(process_ast, "expansion")[0]
    assert process["kind"] == "process_sub"
    assert process["parts"][0]["parts"][0]["value"] == "printf"

    # bashlex stores process substitution inside a word.  Exercise the
    # expansion emitter directly as the canonical executable AST shape.
    executable = {
        "type": "script",
        "body": [{
            "type": "command",
            "parts": [
                _word("cat"),
                {"type": "expansion", "kind": "process_sub", "value": "",
                 "parts": [_command("printf", "process\\n")]},
            ],
        }],
    }
    process_result = _run_bash(emit(executable))
    assert process_result.stdout == b"process\n"


@pytest.mark.parametrize(("source", "keyword", "expected"), [
    ("{ printf '%s\\n' group; }", "{", b"group\n"),
    ("(printf '%s\\n' subshell)", "(", b"subshell\n"),
    ("if true; then printf '%s\\n' branch; fi", "if", b"branch\n"),
    ("for item in one two; do printf '%s\\n' $item; done", "for", b"one\ntwo\n"),
])
def test_real_compounds_emit_valid_bash(source: str, keyword: str, expected: bytes):
    ast = ast_parser.parse_bash(source)
    compounds = _find_nodes(ast, "compound")
    assert compounds
    assert compounds[0]["kind"] == "group"
    assert any(node.get("value") == keyword for node in _find_nodes(compounds[0], "word"))

    result = _run_bash(emit(ast))
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout == expected


def test_function_definition_and_assignment_round_trip_executes():
    source = "#!/usr/bin/env bash\nvalue=ready\nshow() { printf '%s\\n' \"$value\"; }\nshow"
    ast = ast_parser.parse_bash(source)

    assert ast["shebang"] == "#!/usr/bin/env bash"
    assert _find_nodes(ast, "function_def")[0]["name"] == "show"
    assert _find_nodes(ast, "assignment")[0]["name"] == "value"

    result = _run_bash(emit(ast))
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout == b"ready\n"


@pytest.mark.parametrize(("source", "node_type"), [
    ("printf '%s\\n' $'ansi\\nquote'", "word"),
    ("printf '%s\\n' $((1 + 2))", "word"),
    ("printf '%s\\n' ${name#prefix}", "word"),
    ("array=(one 'two words')", "assignment"),
    ("(( count++ ))", "word"),
    ("[[ 'left ]] right' == 'left ]] right' ]]", "word"),
])
def test_unsupported_constructs_are_restored_as_opaque_nodes(source: str, node_type: str):
    ast = ast_parser.parse_bash(source)
    opaque = [node for node in _find_nodes(ast, node_type) if "raw" in node]

    if node_type == "assignment":
        opaque = [node for node in _find_nodes(ast, node_type) if "(" in str(node.get("value"))]
    assert opaque
    if "raw" in opaque[0]:
        assert any(node["raw"] in source for node in opaque)
    output = emit(ast)
    if node_type == "assignment":
        assert "array=" in output
        assert "two words" in output
    else:
        assert source.split(maxsplit=1)[0] in output


def test_total_parse_failure_keeps_shebang_and_source(monkeypatch: pytest.MonkeyPatch):
    def fail_parse(_source: str) -> list[object]:
        raise ValueError("unsupported syntax")

    monkeypatch.setattr(ast_parser.bashlex, "parse", fail_parse)
    ast = ast_parser.parse_bash("#!/bin/bash\necho \"opaque\"")

    assert ast["body"][0]["raw"] == 'echo "opaque"'
    assert emit(ast) == '#!/bin/bash\necho "opaque"\n'


def test_malformed_shell_source_uses_opaque_word_fallback():
    ast = ast_parser.parse_bash('echo "unterminated')

    assert ast["body"] == [{
        "type": "word", "value": 'echo "unterminated',
        "pos": (0, len('echo "unterminated')), "raw": 'echo "unterminated',
        "opaque": True,
    }]
    assert emit(ast) == 'echo "unterminated\n'


def test_converter_handles_opaque_and_missing_bashlex_attributes():
    class FalseyUnknown:
        kind = "unknown"
        pos = (1, 2)

        def __bool__(self) -> bool:
            return False

    unknown = ast_parser._convert_node(SimpleNamespace(kind="vendor_node", word="literal", pos=(0, 7)))
    assert unknown == {"type": "word", "value": "literal", "pos": (0, 7), "raw": "literal"}
    assert ast_parser._convert_node(FalseyUnknown())["value"] == ""

    pipeline = SimpleNamespace(
        kind="pipeline", pos=(0, 10), parts=[SimpleNamespace(kind="pipe")], pipe=None,
    )
    assert ast_parser._convert_node(pipeline)["parts"] == []

    discovered = SimpleNamespace(
        kind="pipeline", pos=(0, 10), parts=None, pipe=None,
        commands=[SimpleNamespace(kind="word", word="found", pos=(0, 5))],
    )
    converted = ast_parser._convert_node(discovered)
    assert converted["parts"][0]["value"] == "found"

    compound = SimpleNamespace(
        kind="compound", compound_kind="group", parts=[
            SimpleNamespace(kind="word", word="inside", pos=(0, 6)),
        ], list=None, pos=(0, 8),
    )
    assert ast_parser._convert_node(compound)["parts"][0]["value"] == "inside"


def test_converter_redirect_and_expansion_fallback_attributes():
    heredoc = SimpleNamespace(value="body", delimiter="END")
    redirect = SimpleNamespace(
        kind="redirect", type=">", output=7, input=3, heredoc=heredoc, pos=(0, 8),
    )
    converted = ast_parser._convert_node(redirect)
    assert converted["target"] == "7"
    assert converted["fd"] == 3
    assert converted["heredoc"]["body"] == "body"

    for kind, expected in (("commandsubstitution", "command_sub"), ("processsubstitution", "process_sub")):
        node = SimpleNamespace(kind=kind, pos=(0, 2))
        converted = ast_parser._convert_node(node)
        assert converted["kind"] == expected
        assert converted["parts"][0]["type"] == "noop"

    assert ast_parser._convert_node(SimpleNamespace(kind="parameter", pos=(0, 2)))["value"] == ""
    assert ast_parser._convert_node(SimpleNamespace(kind="tilde", pos=(0, 1)))["value"] == "~"
    heredoc_node = ast_parser._convert_node(SimpleNamespace(kind="heredoc", pos=(0, 2)))
    assert heredoc_node["delimiter"] == "EOF"
    assert ast_parser._convert_node(SimpleNamespace(kind="assignment", word="plain", pos=(0, 5)))["value"] == ""


def test_preprocessor_finds_nested_and_quote_sensitive_fallback_spans():
    source = "echo ${outer:-${inner}} x=(one 'two)') [[ 'a ]] b' ]] (( count++ ))"
    processed, placeholders = ast_parser._preprocess_for_bashlex(source)

    assert processed != source
    assert len(placeholders) == 4
    assert "${outer:-${inner}}" in placeholders.values()
    assert "x=(one 'two)')" in placeholders.values()
    assert "[[ 'a ]] b' ]]" in placeholders.values()
    assert "(( count++ ))" in placeholders.values()
    assert ast_parser._find_complex_params("${plain} ${a:-${b}}") == [(9, 19)]
    assert ast_parser._find_arith_commands("$((1 + 2)) ((count++))") == [(11, 22)]


def test_emitter_quote_and_shell_syntax_defensive_paths():
    values = {
        "'already quoted'": "'already quoted'",
        '"already quoted"': '"already quoted"',
        "$'ansi'": "$'ansi'",
        '$"locale"': '$"locale"',
        '"He"$\'llo\'"o"': '"He"$\'llo\'"o"',
        "${name}": '"${name}"',
        "$?": '"$?"',
        "$(printf ok)": "$(printf ok)",
        "`printf ok`": "`printf ok`",
        "[[ x == y ]]": "[[ x == y ]]",
        "(( count++ ))": "(( count++ ))",
        "[ -n x ]": "[ -n x ]",
        "array=(one two)": "array=(one two)",
        'value="x $y"': 'value="x $y"',
        'eval "$code"': 'eval "$code"',
        "left | right": "left | right",
        "plain value": "'plain value'",
        "dollar $value": '"dollar $value"',
        "apostrophe's": "'apostrophe'\\''s'",
        "ümlaut": "'ümlaut'",
    }

    for value, expected in values.items():
        node = {"type": "script", "body": [_word(value)]}
        assert emit(node).strip() == expected

    assert emit({"type": "script", "body": [_word("raw syntax", raw=True)]}).strip() == "raw syntax"
    assert emit({"type": "script", "body": [{"type": "word"}]}).strip() == ""


def test_emitter_assignments_redirects_and_raw_nodes_defensively():
    ast = {
        "type": "script",
        "body": [
            {"type": "assignment", "name": "plain", "value": "value"},
            {"type": "assignment", "name": "full=x=1", "value": ""},
            {"type": "assignment", "name": "quoted", "value": {"type": "expansion", "kind": "command_sub", "value": "printf ok"}},
            {"type": "redirect", "redirect_type": ">", "target": _word("out")},
            {"type": "redirect", "redirect_type": "<", "target": "", "fd": 0},
            {"type": "heredoc", "delimiter": "DONE", "body": "line"},
            {"type": "operator", "op": "&&"},
            {"type": "raw", "parts": [_word("left"), _word("right")]},
            {"type": "mystery", "value": 42},
            {"type": "mystery"},
        ],
    }
    output = emit(ast)

    assert "plain=value" in output
    assert "full=x=1" in output
    assert 'quoted="$(printf ok)"' in output
    assert ">out" in output
    assert "0<" in output
    assert "<<DONE\nline\nDONE" in output
    assert "&&" in output
    assert "left right" in output
    assert "42" in output


def test_emitter_control_flow_and_balanced_quote_helpers():
    assert emit({"type": "script", "body": [{"type": "compound", "kind": "mystery", "parts": [_word("body")]}]}).strip() == "body"
    assert emit({"type": "script", "body": [{"type": "compound", "kind": "(", "parts": [_command("true")]}]}).startswith("(\n")
    bracket_output = emit({
        "type": "script",
        "body": [{"type": "compound", "kind": "[[", "parts": [_word("-n"), _word("x")]}],
    }).strip()
    assert bracket_output.startswith("[[ -n")
    assert bracket_output.endswith("x ]]")

    assert ast_parser._find_complex_params("${x} ${x:-${y}}") == [(5, 15)]
