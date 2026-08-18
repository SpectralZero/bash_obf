"""Verifier comparison, failure, environment, and cleanup tests."""

import os
import subprocess

import pytest

from obfush.engine.verifier import VerificationError, Verifier


def _result(stdout=b"", stderr=b"", exit_code=0, *, timed_out=False, error=None):
    return {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "error": error,
    }


def test_matching_behavior_verifies(monkeypatch):
    verifier = Verifier(bash_path="bash")
    monkeypatch.setattr(verifier, "_run_script", lambda source, stdin: _result(b"same\n"))
    assert verifier.verify("original", "obfuscated")


def test_stdout_mismatch_raises_with_diff(monkeypatch):
    verifier = Verifier(bash_path="bash", normalize=False)
    results = iter((_result(b"one"), _result(b"two")))
    monkeypatch.setattr(verifier, "_run_script", lambda source, stdin: next(results))

    with pytest.raises(VerificationError) as captured:
        verifier.verify("original", "obfuscated")

    assert captured.value.diff["stdout"] == {
        "original": "one", "obfuscated": "two",
    }


def test_exit_code_mismatch_raises(monkeypatch):
    verifier = Verifier(bash_path="bash")
    results = iter((_result(exit_code=0), _result(exit_code=7)))
    monkeypatch.setattr(verifier, "_run_script", lambda source, stdin: next(results))

    with pytest.raises(VerificationError) as captured:
        verifier.verify("original", "obfuscated")

    assert captured.value.diff["exit_code"] == {"original": 0, "obfuscated": 7}


def test_stderr_difference_is_warning_only(monkeypatch):
    verifier = Verifier(bash_path="bash", normalize=False)
    results = iter((_result(stderr=b"one"), _result(stderr=b"two")))
    monkeypatch.setattr(verifier, "_run_script", lambda source, stdin: next(results))
    assert verifier.verify("original", "obfuscated")


@pytest.mark.parametrize("failed", [
    _result(timed_out=True, exit_code=-1),
    _result(error="OSError: failed", exit_code=-2),
])
def test_execution_failures_never_verify_even_when_both_match(monkeypatch, failed):
    verifier = Verifier(bash_path="bash")
    monkeypatch.setattr(verifier, "_run_script", lambda source, stdin: failed)

    with pytest.raises(VerificationError) as captured:
        verifier.verify("original", "obfuscated")

    assert "execution" in captured.value.diff


def test_verify_json_reports_execution_failure(monkeypatch):
    verifier = Verifier(bash_path="bash")
    monkeypatch.setattr(
        verifier, "_run_script",
        lambda source, stdin: _result(timed_out=True, exit_code=-1),
    )
    result = verifier.verify_json("original", "obfuscated")
    assert not result["passed"]
    assert "execution" in result["diff"]


def test_verify_json_reports_comparison_dimensions(monkeypatch):
    verifier = Verifier(bash_path="bash", normalize=False)
    results = iter((_result(b"one", b"warn", 0), _result(b"two", b"other", 3)))
    monkeypatch.setattr(verifier, "_run_script", lambda source, stdin: next(results))
    result = verifier.verify_json("original", "obfuscated")
    assert not result["passed"]
    assert not result["stdout_match"]
    assert not result["exit_code_match"]
    assert result["stderr_warning"]


def test_test_input_text_is_passed_to_both_runs(monkeypatch):
    verifier = Verifier(bash_path="bash")
    seen = []

    def run(source, stdin):
        seen.append(stdin)
        return _result(stdin or b"")

    monkeypatch.setattr(verifier, "_run_script", run)
    assert verifier.verify("original", "obfuscated", "payload")
    assert seen == [b"payload", b"payload"]


def test_test_input_file_is_passed_to_both_runs(tmp_path, monkeypatch):
    payload = tmp_path / "input.bin"
    payload.write_bytes(b"\x00payload")
    verifier = Verifier(bash_path="bash")
    seen = []

    def run(source, stdin):
        seen.append(stdin)
        return _result(stdin or b"")

    monkeypatch.setattr(verifier, "_run_script", run)
    assert verifier.verify("original", "obfuscated", str(payload))
    assert seen == [b"\x00payload", b"\x00payload"]


def test_run_script_timeout_is_structured(monkeypatch):
    verifier = Verifier(bash_path="bash", timeout=1)

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("bash", 1, output=b"partial")

    monkeypatch.setattr(subprocess, "run", timeout)
    result = verifier._run_script("echo hello")
    assert result["timed_out"]
    assert result["stdout"] == b"partial"
    assert result["exit_code"] == -1


def test_run_script_removes_temporary_file(monkeypatch):
    verifier = Verifier(bash_path="bash")
    captured_path = None

    def run(args, **kwargs):
        nonlocal captured_path
        captured_path = args[1]
        assert os.path.exists(captured_path)
        return subprocess.CompletedProcess(args, 0, b"ok", b"")

    monkeypatch.setattr(subprocess, "run", run)
    result = verifier._run_script("printf ok")
    assert result["stdout"] == b"ok"
    assert captured_path is not None
    assert not os.path.exists(captured_path)


def test_safe_environment_removes_shell_hooks_and_exact_secrets(monkeypatch):
    monkeypatch.setenv("BASH_ENV", "/tmp/hook")
    monkeypatch.setenv("ENV", "/tmp/env")
    monkeypatch.setenv("CDPATH", "/tmp")
    monkeypatch.setenv("PROMPT_COMMAND", "malicious")
    monkeypatch.setenv("BASH_FUNC_demo%%", "() { :; }")
    monkeypatch.setenv("TOKEN", "secret")
    monkeypatch.setenv("PATH", os.environ.get("PATH", ""))

    env = Verifier(bash_path="bash")._safe_env()

    assert "BASH_ENV" not in env
    assert "ENV" not in env
    assert "CDPATH" not in env
    assert "PROMPT_COMMAND" not in env
    assert "BASH_FUNC_demo%%" not in env
    assert "TOKEN" not in env
    assert env["LC_ALL"] == "C"
    assert "PATH" in env


def test_no_bash_warns_and_returns_false():
    verifier = Verifier(bash_path="definitely-missing")
    verifier.bash_path = None
    with pytest.warns(RuntimeWarning, match="No bash found"):
        assert not verifier.verify("original", "obfuscated")


def test_real_identical_script_verifies():
    verifier = Verifier(timeout=5)
    if not verifier.bash_path:
        pytest.skip("Bash unavailable")
    assert verifier.verify("printf 'same\\n'\n", "printf 'same\\n'\n")
