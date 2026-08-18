"""Focused branch coverage for normalizer and non-VM utility boundaries."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

import obfush.batch as batch_module
import obfush.compiler.compiler as compiler_module
import obfush.engine.normalizer as normalizer
import obfush.engine.security_analyzer as security_analyzer
from obfush.batch import BatchItemResult
from obfush.compiler.compiler import CompilerCapability, CompilerError
from obfush.engine.core import EngineConfig
from obfush.utils.decoy_corpus import ACTIONS, COMPONENTS, CONTEXTS, DecoyCorpus
from obfush.utils.entropy_utils import format_entropy_report


def test_normalizer_covers_nested_ast_edges_without_mutating_input():
    ast = {
        "type": "script",
        "parts": {
            "type": "word",
            "value": "$root",
            "body": {"type": "word", "value": "$nested"},
        },
        "body": [
            {"type": "assignment", "name": "global_value"},
            {"type": "word", "value": "$global_value ${other}"},
            {"type": "expansion", "kind": "parameter", "value": "expanded"},
            {"type": "expansion", "kind": "parameter", "value": ""},
            {
                "type": "command",
                "parts": [
                    {"type": "word", "value": "["},
                    {"type": "word", "value": "$global_value"},
                    {"type": "word", "value": "]"},
                ],
            },
            {
                "type": "command",
                "parts": [
                    {"type": "word", "value": "test"},
                    "literal-part",
                    {"type": "word", "value": "-n"},
                ],
            },
            {
                "type": "compound",
                "kind": "[[",
                "body": {"type": "word", "value": "$compound_value"},
            },
            {
                "type": "list",
                "parts": [{"type": "command", "parts": []}],
            },
            {
                "type": "list",
                "parts": [
                    {"type": "word", "value": "one"},
                    {"type": "word", "value": "two"},
                    "separator",
                ],
            },
            {"type": "comment", "value": "discard me"},
            {
                "type": "function_def",
                "name": "worker",
                "body": {
                    "type": "script",
                    "body": [
                        {"type": "assignment", "name": "inside"},
                        {
                            "type": "command",
                            "parts": [
                                {"type": "word", "value": "local"},
                                {"type": "word", "value": "local_word=value"},
                                {"type": "assignment", "name": "local_assignment"},
                            ],
                        },
                        {"type": "word", "value": "$inside"},
                    ],
                },
            },
            {"type": "function_def", "name": "declaration_only", "body": []},
            {
                "type": "command",
                "parts": [
                    {"type": "word", "value": "local"},
                    {"type": "word", "value": "outside=value"},
                ],
            },
            "literal-body",
        ],
    }

    result = normalizer.normalize(ast)

    assert ast["body"][4]["type"] == "command"
    assert result["body"][4]["type"] == "test_expr"
    assert result["body"][4]["original_style"] == "["
    assert [part["value"] for part in result["body"][4]["test_parts"]] == [
        "$global_value"
    ]
    assert result["body"][5]["type"] == "test_expr"
    assert result["body"][6]["type"] == "test_expr"
    assert result["body"][7]["type"] == "command"
    assert result["body"][8]["type"] == "list"
    assert not any(
        isinstance(node, dict) and node.get("type") == "comment"
        for node in result["body"]
    )
    assert result["body"][2]["var_name"] == "expanded"
    assert "var_name" not in result["body"][3]
    assert result["parts"]["var_refs"] == ["root"]
    assert result["parts"]["body"]["var_refs"] == ["nested"]

    scope = result["_scope"]
    assert scope["globals"] == {"global_value"}
    assert scope["assignments"] == {"global_value", "inside", "local_assignment"}
    assert scope["locals"] == {
        "worker": {"local_word", "local_assignment"},
        "declaration_only": set(),
    }
    assert {"root", "nested", "global_value", "other", "expanded", "inside"} <= scope[
        "reads"
    ]


@pytest.mark.parametrize(
    "normalization_pass",
    [
        normalizer._normalize_variable_refs,
        normalizer._canonicalize_tests,
        normalizer._flatten_trivial_lists,
        normalizer._strip_comments,
    ],
)
def test_normalizer_walkers_leave_non_mapping_values_untouched(normalization_pass):
    assert normalization_pass("literal") == "literal"


def test_normalizer_strips_comment_in_mapping_child_and_walks_scope_mapping_child():
    ast = {
        "type": "script",
        "body": {"type": "comment", "value": "mapping comment"},
        "parts": {"type": "word", "var_refs": ["mapping_read"]},
    }

    stripped = normalizer._strip_comments(ast)
    tracked = normalizer._track_scopes(stripped)

    assert stripped["body"]["type"] == "comment"
    assert tracked["_scope"]["reads"] == {"mapping_read"}
    assert normalizer._track_scopes({"type": "script", "body": [None]})["_scope"][
        "reads"
    ] == set()


def test_entropy_report_lists_and_truncates_many_high_entropy_regions():
    report = format_entropy_report(bytes(range(256)) * 7, window_size=256)

    assert "High-entropy regions:" in report
    assert report.count("bits/byte") == 11
    assert "... and 3 more" in report


class _ConstantRng:
    def choice(self, values):
        return values[0]

    def randint(self, start, stop):
        assert (start, stop) == (0x10, 0xFF)
        return start


def test_decoy_corpus_collision_fallback_and_variable_name():
    corpus = DecoyCorpus(_ConstantRng())
    base = f"{ACTIONS[0]} {COMPONENTS[0]} {CONTEXTS[0]}"
    corpus._used_text.update({base, f"{base} (1)"})

    assert corpus.generate_comment() == f"{base} (2)"
    assert corpus.generate_var_name("ignored") == "log_rotate_10"


def test_security_structure_digest_handles_primitive_ast_children(monkeypatch):
    monkeypatch.setattr(
        security_analyzer,
        "parse_bash",
        lambda source: {"type": "script", "body": [1, "value", None]},
    )

    first = security_analyzer._structure_digest("first")
    second = security_analyzer._structure_digest("second")

    assert first == second
    assert len(first) == 64


def test_wsl_compile_falls_back_to_dynamic_build(monkeypatch, tmp_path):
    commands = []
    attempts = iter(
        [
            compiler_module._CompileAttempt(False, "static unavailable"),
            compiler_module._CompileAttempt(True, ""),
        ]
    )
    monkeypatch.setattr(compiler_module, "_wsl_path", lambda path: f"/mnt/c/{path.name}")
    monkeypatch.setattr(
        compiler_module.shutil,
        "which",
        lambda executable: "wsl.exe" if executable == "wsl.exe" else None,
    )

    def run_compile(command):
        commands.append(command)
        return next(attempts)

    monkeypatch.setattr(compiler_module, "_run_compile", run_compile)
    capability = CompilerCapability("wsl", "/usr/bin/gcc", "linux-x86_64", False)

    assert compiler_module._compile(
        capability, tmp_path / "loader.c", tmp_path / "loader"
    ) is False
    assert len(commands) == 2
    assert "-static" in commands[0]
    assert "-static" not in commands[1]


@pytest.mark.parametrize(
    ("dynamic_error", "reported_error"),
    [("dynamic failed", "dynamic failed"), ("", "static failed")],
)
def test_wsl_compile_reports_dynamic_failure(
    monkeypatch, tmp_path, dynamic_error, reported_error
):
    attempts = iter(
        [
            compiler_module._CompileAttempt(False, "static failed"),
            compiler_module._CompileAttempt(False, dynamic_error),
        ]
    )
    monkeypatch.setattr(compiler_module, "_wsl_path", lambda path: f"/mnt/c/{path.name}")
    monkeypatch.setattr(compiler_module.shutil, "which", lambda executable: "wsl.exe")
    monkeypatch.setattr(compiler_module, "_run_compile", lambda command: next(attempts))
    capability = CompilerCapability("wsl", "/usr/bin/gcc", "linux-x86_64", False)

    with pytest.raises(CompilerError, match=reported_error):
        compiler_module._compile(capability, tmp_path / "loader.c", tmp_path / "loader")


def test_wsl_path_requires_wsl_executable(monkeypatch, tmp_path):
    monkeypatch.setattr(compiler_module.shutil, "which", lambda executable: None)

    with pytest.raises(CompilerError, match="wsl.exe is unavailable"):
        compiler_module._wsl_path(tmp_path / "loader.c")


def test_build_binary_sets_executable_mode_on_posix(monkeypatch, tmp_path):
    capability = CompilerCapability("native", "cc", "linux", False)
    chmod_calls = []
    monkeypatch.setattr(compiler_module, "detect_compiler", lambda: capability)
    monkeypatch.setattr(
        compiler_module,
        "os",
        SimpleNamespace(name="posix", getpid=os.getpid, replace=os.replace),
    )

    def compile_artifact(capability, source, output):
        output.write_bytes(b"binary")
        return False

    monkeypatch.setattr(compiler_module, "_compile", compile_artifact)
    destination = tmp_path / "program"
    monkeypatch.setattr(
        type(destination),
        "chmod",
        lambda self, mode: chmod_calls.append((self, mode)),
    )

    compiler_module.build_binary("echo ok", str(destination), seed=1)

    assert chmod_calls == [(destination.resolve(), 0o755)]


def test_batch_rejects_non_directory_input(tmp_path):
    missing = tmp_path / "missing"
    regular_file = tmp_path / "input.txt"
    regular_file.write_text("not a directory", encoding="utf-8")

    for path in (missing, regular_file):
        with pytest.raises(ValueError, match="Batch input is not a directory"):
            batch_module.discover_scripts(path)


def test_batch_turns_output_write_failure_into_item_error(monkeypatch, tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    source = input_dir / "script.sh"
    source.write_text("echo ok\n", encoding="utf-8")
    successful = BatchItemResult(
        input_path=str(source),
        output_path=str(output_dir / "nested" / "script.sh"),
        status="ok",
        seed=42,
        source_bytes=8,
        output_bytes=9,
        elapsed_ms=1.0,
        layers_applied=["id-mangle"],
        verified=True,
        analysis={"source_bytes": 9},
    )
    monkeypatch.setattr(batch_module, "_process_one", lambda job: (successful, "output"))

    def fail_write(output_path, output):
        raise OSError("disk full")

    results = batch_module.process_batch(
        input_dir,
        output_dir,
        EngineConfig(seed=42),
        write_output=fail_write,
    )

    assert results == [
        BatchItemResult(
            **{
                **successful.to_dict(),
                "status": "error",
                "output_bytes": 0,
                "error": "OSError: disk full",
                "analysis": None,
            }
        )
    ]
    assert (output_dir / "nested").is_dir()


def test_empty_fail_fast_worklist_is_a_noop():
    assert batch_module._process_fail_fast([], workers=2) == []
