"""Executable coverage for synthetic AST emitter branches."""

import subprocess

import pytest

from obfush.engine.ast_emitter import emit


def _word(value: str, *, raw: bool = False) -> dict:
    node = {"type": "word", "value": value, "pos": None}
    if raw:
        node["raw"] = value
    return node


def _command(*values: str) -> dict:
    return {"type": "command", "parts": [_word(value) for value in values], "pos": None}


def _test(*values: str, style: str = "[[") -> dict:
    return {
        "type": "test_expr",
        "original_style": style,
        "test_parts": [_word(value) for value in values],
        "parts": [],
        "pos": None,
    }


def _run(ast: dict) -> subprocess.CompletedProcess:
    source = emit(ast)
    syntax = subprocess.run(
        ["bash", "-n"], input=source.encode("utf-8"), capture_output=True, timeout=10,
    )
    assert syntax.returncode == 0, f"{syntax.stderr.decode()}\n{source}"
    return subprocess.run(
        ["bash"], input=source.encode("utf-8"), capture_output=True, timeout=10,
    )


def test_synthetic_control_flow_executes_in_real_bash():
    ast = {
        "type": "script",
        "shebang": "#!/bin/bash",
        "body": [
            {"type": "assignment", "name": "total", "value": "0", "pos": None},
            {
                "type": "compound", "kind": "for", "variable": "item", "items": "1 2 3",
                "parts": [{
                    "type": "assignment", "name": "total",
                    "value": "$(( total + item ))", "pos": None,
                }], "pos": None,
            },
            {
                "type": "compound", "kind": "while",
                "parts": [
                    _test("$total", "-lt", "8"),
                    {"type": "assignment", "name": "total", "value": "$(( total + 1 ))", "pos": None},
                ], "pos": None,
            },
            {
                "type": "compound", "kind": "until",
                "parts": [
                    _test("$total", "-ge", "10"),
                    {"type": "assignment", "name": "total", "value": "$(( total + 1 ))", "pos": None},
                ], "pos": None,
            },
            {
                "type": "compound", "kind": "if",
                "parts": [
                    _test("$total", "-eq", "10"),
                    _command("printf", "if-ok\\n"),
                    _command("printf", "if-failed\\n"),
                ], "pos": None,
            },
            {
                "type": "compound", "kind": "case", "word": "$total",
                "parts": [
                    {"pattern": "10", "body": _command("printf", "case-ok\\n")},
                    {"pattern": "*", "body": _command("printf", "case-failed\\n")},
                ], "pos": None,
            },
        ],
    }

    result = _run(ast)

    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout == b"if-ok\ncase-ok\n"
    assert result.stderr == b""


def test_functions_expansions_tests_and_pipeline_execute():
    function = {
        "type": "function_def",
        "name": "produce",
        "body": {
            "type": "compound", "kind": "{",
            "parts": [_command("printf", "alpha\\nbeta\\n")], "pos": None,
        },
        "pos": None,
    }
    command_sub = {
        "type": "expansion", "kind": "command_sub", "value": "",
        "parts": [_command("produce")], "pos": None,
    }
    ast = {
        "type": "script",
        "body": [
            function,
            {"type": "assignment", "name": "captured", "value": command_sub, "pos": None},
            {
                "type": "list", "op": ";", "parts": [
                    _test("$captured", "=", "$'alpha\\nbeta'", style="[["),
                    {"type": "operator", "op": "&&", "pos": None},
                    _command("printf", "test-ok\\n"),
                ], "pos": None,
            },
            {
                "type": "pipeline",
                "parts": [_command("printf", "mixedCase"), _command("tr", "[:lower:]", "[:upper:]")],
                "pos": None,
            },
            _command("printf", "\\n"),
        ],
    }

    result = _run(ast)

    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout == b"test-ok\nMIXEDCASE\n"


def test_heredoc_and_redirect_emit_valid_bash():
    ast = {
        "type": "script",
        "body": [{
            "type": "command",
            "parts": [
                _word("cat"),
                {
                    "type": "redirect", "redirect_type": "<<", "target": "EOF", "fd": None,
                    "heredoc": {"type": "heredoc", "delimiter": "EOF", "body": "payload"},
                    "pos": None,
                },
            ],
            "pos": None,
        }],
    }

    result = _run(ast)

    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout == b"payload\n"


@pytest.mark.parametrize(("node", "expected"), [
    ({"type": "expansion", "kind": "parameter", "value": "name"}, "${name}"),
    ({"type": "expansion", "kind": "command_sub", "value": "printf ok"}, "$(printf ok)"),
    ({"type": "expansion", "kind": "process_sub", "value": "printf ok"}, "<(printf ok)"),
    ({"type": "expansion", "kind": "arithmetic", "value": "1 + 2"}, "$((1 + 2))"),
    ({"type": "expansion", "kind": "tilde", "value": ""}, "~"),
    ({"type": "expansion", "kind": "unknown", "value": "opaque"}, "opaque"),
    ({"type": "raw", "raw": "printf raw"}, "printf raw"),
    ({"type": "raw", "value": 42}, "42"),
    ({"type": "raw", "parts": [_word("printf"), _word("parts")]}, "printf parts"),
])
def test_individual_emitter_fallbacks(node, expected):
    assert emit({"type": "script", "body": [node]}).strip() == expected


@pytest.mark.parametrize(("style", "expected"), [
    ("[[", "[[ value = value ]]"),
    ("[", "[ value = value ]"),
    ("test", "test value = value"),
    ("unexpected", "[[ value = value ]]"),
])
def test_test_expression_styles(style, expected):
    assert emit({"type": "script", "body": [_test("value", "=", "value", style=style)]}).strip() == expected


def test_empty_synthetic_control_flow_defaults_are_valid_syntax():
    ast = {
        "type": "script",
        "body": [
            {"type": "compound", "kind": "if", "parts": [], "pos": None},
            {"type": "compound", "kind": "until", "parts": [], "pos": None},
        ],
    }
    source = emit(ast)
    syntax = subprocess.run(
        ["bash", "-n"], input=source.encode("utf-8"), capture_output=True, timeout=10,
    )
    assert syntax.returncode == 0, f"{syntax.stderr.decode()}\n{source}"
