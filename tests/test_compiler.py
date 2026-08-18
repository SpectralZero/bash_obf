"""Unit and integration-contract tests for compiled binary output."""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

import obfush.compiler as compiler_package
import obfush.compiler.compiler as compiler_module
from obfush.cli import main
from obfush.compiler.anti_debug import generate_anti_debug
from obfush.compiler.compiler import (
    BinaryBuildResult,
    CompilerCapability,
    CompilerError,
    build_binary,
    detect_compiler,
)
from obfush.compiler.crypto import EncryptedPayload, decrypt_payload, encrypt_payload
from obfush.compiler.env_keying import c_environment_check, derive_environment_tag
from obfush.compiler.stub_generator import StubResult, generate_stub


class _FixedBytesRng:
    def randbytes(self, size: int) -> bytes:
        return bytes(range(size))


@pytest.mark.parametrize("key_size", [16, 32, 64])
def test_encrypt_payload_uses_repeated_xor_and_round_trips(key_size):
    payload = bytes(range(100))

    encrypted = encrypt_payload(payload, _FixedBytesRng(), key_size)

    assert encrypted.key == bytes(range(key_size))
    assert encrypted.ciphertext == bytes(
        byte ^ (index % key_size) for index, byte in enumerate(payload)
    )
    assert decrypt_payload(encrypted) == payload


def test_encrypt_payload_is_seed_deterministic_and_does_not_mutate_input():
    payload = b"echo deterministic\n"

    first = encrypt_payload(payload, random.Random(1234), 24)
    second = encrypt_payload(payload, random.Random(1234), 24)
    different = encrypt_payload(payload, random.Random(1235), 24)

    assert first == second
    assert first != different
    assert payload == b"echo deterministic\n"
    assert first.ciphertext != payload


@pytest.mark.parametrize(
    ("payload", "key_size", "message"),
    [
        (b"", 32, "payload must not be empty"),
        (b"x", 15, "key_size must be 16-64 bytes"),
        (b"x", 65, "key_size must be 16-64 bytes"),
    ],
)
def test_encrypt_payload_rejects_invalid_inputs(payload, key_size, message):
    with pytest.raises(ValueError, match=message):
        encrypt_payload(payload, random.Random(1), key_size)


def test_derive_environment_tag_matches_truncated_utf8_sha256():
    value = "build-host-\u03b1"

    tag = derive_environment_tag(value)

    assert tag == hashlib.sha256(value.encode("utf-8")).digest()[:8]
    assert len(tag) == 8


def test_derive_environment_tag_rejects_empty_value():
    with pytest.raises(ValueError, match="environment key must not be empty"):
        derive_environment_tag("")


def test_c_environment_check_embeds_only_tag_and_runtime_sources():
    tag = bytes.fromhex("0011223344556677")

    source = c_environment_check(tag, "_check_environment")

    assert "static int _check_environment(void)" in source
    assert 'getenv("OBFUSH_ENV_KEY")' in source
    assert "gethostname(value, sizeof(value) - 1)" in source
    assert "obfush_sha256" in source
    assert "memcmp(expected, actual, 8) == 0" in source
    assert "0x00, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77" in source


@pytest.mark.parametrize("tag", [b"", b"seven!!", b"nine-byte"])
def test_c_environment_check_requires_exactly_eight_bytes(tag):
    with pytest.raises(ValueError, match="environment tag must be eight bytes"):
        c_environment_check(tag, "check")


def test_generate_anti_debug_selects_all_unique_templates_with_matching_names():
    names = [f"check_{index}" for index in range(5)]
    marker_by_name = {
        "tracerpid": "TracerPid:",
        "parent": "getppid()",
        "preload": 'getenv(\"LD_PRELOAD\")',
        "dumpable": "PR_SET_DUMPABLE",
        "timing": "CLOCK_MONOTONIC",
    }
    index_by_name = {
        "tracerpid": 0,
        "parent": 1,
        "preload": 2,
        "dumpable": 3,
        "timing": 4,
    }

    fragments = generate_anti_debug(random.Random(9), names, count=10)

    assert len(fragments) == 5
    assert {fragment.name for fragment in fragments} == set(marker_by_name)
    for fragment in fragments:
        expected_function = names[index_by_name[fragment.name]]
        assert f"static int {expected_function}(void)" in fragment.source
        assert marker_by_name[fragment.name] in fragment.source


def test_generate_anti_debug_is_deterministic_and_honors_count():
    names = [f"fn_{index}" for index in range(5)]

    first = generate_anti_debug(random.Random(42), names, count=3)
    second = generate_anti_debug(random.Random(42), names, count=3)

    assert first == second
    assert len(first) == 3
    assert len({fragment.name for fragment in first}) == 3
    assert generate_anti_debug(random.Random(42), names, count=0) == []


def test_generate_anti_debug_requires_five_function_names():
    with pytest.raises(ValueError, match="five function names are required"):
        generate_anti_debug(random.Random(1), ["a", "b", "c", "d"])


def _encrypted_fixture() -> EncryptedPayload:
    return encrypt_payload(b"echo secret-value\n", random.Random(101), 16)


def test_generate_stub_contains_encrypted_loader_contract_without_plaintext():
    encrypted = _encrypted_fixture()

    stub = generate_stub(encrypted, random.Random(202), anti_debug=True)

    assert stub.key_size == 16
    assert len(stub.anti_debug_checks) == 3
    assert len(set(stub.anti_debug_checks)) == 3
    assert "echo secret-value" not in stub.source
    assert ", ".join(f"0x{byte:02x}" for byte in encrypted.ciphertext) in stub.source
    assert ", ".join(f"0x{byte:02x}" for byte in encrypted.key) in stub.source
    assert 'execv("/bin/bash", bash_argv)' in stub.source
    assert 'bash_argv[1] = (char *)"-c"' in stub.source
    assert "for (int i = 1; i < argc; ++i)" in stub.source
    assert "WIFEXITED(status)" in stub.source
    assert "WIFSIGNALED(status)" in stub.source
    assert "while (n--) *p++ = 0" in stub.source
    assert re.search(r"if \([^\n]+\) return 126;", stub.source)


def test_generate_stub_can_disable_anti_debug_checks():
    stub = generate_stub(_encrypted_fixture(), random.Random(303), anti_debug=False)

    assert stub.anti_debug_checks == []
    assert "return 126" not in stub.source
    assert "TracerPid:" not in stub.source
    assert 'getenv("LD_PRELOAD")' not in stub.source
    assert "PR_SET_DUMPABLE" not in stub.source
    assert "CLOCK_MONOTONIC" not in stub.source
    assert "/proc/%d/comm" not in stub.source
    assert 2 <= len(re.findall(r"static unsigned long \w+\(unsigned long x\)", stub.source)) <= 4


def test_generate_stub_embeds_environment_guard_without_plaintext_key():
    environment_key = "production-host-secret"
    tag = derive_environment_tag(environment_key)

    stub = generate_stub(
        _encrypted_fixture(),
        random.Random(404),
        anti_debug=False,
        environment_tag=tag,
    )

    assert environment_key not in stub.source
    assert 'getenv("OBFUSH_ENV_KEY")' in stub.source
    assert "return 125" in stub.source
    assert ", ".join(f"0x{byte:02x}" for byte in tag) in stub.source


def test_generate_stub_is_seed_deterministic_and_polymorphic():
    encrypted = _encrypted_fixture()

    first = generate_stub(encrypted, random.Random(505))
    repeated = generate_stub(encrypted, random.Random(505))
    different = generate_stub(encrypted, random.Random(506))

    assert first == repeated
    assert first.source != different.source


@pytest.mark.parametrize(
    ("available", "expected_backend", "expected_static", "expected_calls"),
    [
        ({"musl-gcc": "/tools/musl-gcc"}, "native", True, ["musl-gcc"]),
        (
            {"gcc": "/tools/gcc"},
            "native",
            False,
            ["musl-gcc", "gcc"],
        ),
        (
            {"clang": "/tools/clang"},
            "native",
            False,
            ["musl-gcc", "gcc", "clang"],
        ),
    ],
)
def test_detect_compiler_prefers_native_toolchains_in_order(
    monkeypatch, available, expected_backend, expected_static, expected_calls
):
    calls = []

    def fake_which(executable):
        calls.append(executable)
        return available.get(executable)

    monkeypatch.setattr(compiler_module, "os", SimpleNamespace(name="posix"))
    monkeypatch.setattr(compiler_module.shutil, "which", fake_which)
    monkeypatch.setattr(
        compiler_module.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("native detection must not launch a probe"),
    )

    capability = detect_compiler()

    assert capability == CompilerCapability(
        expected_backend,
        next(iter(available.values())),
        "linux",
        expected_static,
    )
    assert calls == expected_calls


def test_detect_compiler_probes_linux_toolchain_through_windows_bash(monkeypatch):
    run_calls = []

    def fake_which(executable):
        return "C:/Windows/System32/bash.exe" if executable == "bash" else None

    def fake_run(command, **kwargs):
        run_calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="/usr/bin/gcc\n", stderr="")

    monkeypatch.setattr(compiler_module, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(compiler_module.shutil, "which", fake_which)
    monkeypatch.setattr(compiler_module.subprocess, "run", fake_run)

    capability = detect_compiler()

    assert capability == CompilerCapability("wsl", "/usr/bin/gcc", "linux-x86_64", False)
    assert run_calls == [
        (
            [
                "bash",
                "-lc",
                "command -v musl-gcc || command -v gcc || command -v clang || command -v cc",
            ],
            {"capture_output": True, "text": True, "timeout": 15},
        )
    ]


@pytest.mark.parametrize(
    "probe",
    [
        SimpleNamespace(returncode=1, stdout="", stderr="missing"),
        SimpleNamespace(returncode=0, stdout="\n", stderr=""),
    ],
)
def test_detect_compiler_rejects_failed_or_empty_windows_probe(monkeypatch, probe):
    monkeypatch.setattr(compiler_module, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(
        compiler_module.shutil,
        "which",
        lambda executable: "bash.exe" if executable == "bash" else None,
    )
    monkeypatch.setattr(compiler_module.subprocess, "run", lambda *args, **kwargs: probe)

    with pytest.raises(CompilerError, match="No supported Linux C compiler found"):
        detect_compiler()


def test_detect_compiler_rejects_missing_native_toolchain(monkeypatch):
    monkeypatch.setattr(compiler_module, "os", SimpleNamespace(name="posix"))
    monkeypatch.setattr(compiler_module.shutil, "which", lambda executable: None)

    with pytest.raises(CompilerError, match="musl-gcc, gcc, clang, or cc"):
        detect_compiler()


def test_compile_native_prefers_static_build(monkeypatch, tmp_path):
    commands = []

    def fake_run(command):
        commands.append(command)
        return compiler_module._CompileAttempt(True, "")

    monkeypatch.setattr(compiler_module, "_run_compile", fake_run)
    capability = CompilerCapability("native", "/usr/bin/gcc", "linux", False)
    source = tmp_path / "loader.c"
    output = tmp_path / "loader"

    assert compiler_module._compile(capability, source, output) is True
    assert len(commands) == 1
    assert commands[0][0] == capability.compiler
    assert commands[0][-3:] == [str(source), "-o", str(output)]
    assert "-static" in commands[0]
    assert "-fPIE" in commands[0]
    assert "-pie" in commands[0]
    assert "-Wl,-z,relro,-z,now" in commands[0]


def test_compile_native_falls_back_to_dynamic_build(monkeypatch, tmp_path):
    commands = []
    attempts = iter([
        compiler_module._CompileAttempt(False, "static libraries unavailable"),
        compiler_module._CompileAttempt(True, ""),
    ])

    def fake_run(command):
        commands.append(command)
        return next(attempts)

    monkeypatch.setattr(compiler_module, "_run_compile", fake_run)
    capability = CompilerCapability("native", "/usr/bin/clang", "linux", False)

    static_linked = compiler_module._compile(
        capability, tmp_path / "loader.c", tmp_path / "loader"
    )

    assert static_linked is False
    assert len(commands) == 2
    assert "-static" in commands[0]
    assert "-static" not in commands[1]


@pytest.mark.parametrize(
    ("static_error", "dynamic_error", "reported"),
    [
        ("static failed", "dynamic failed", "dynamic failed"),
        ("static failed", "", "static failed"),
    ],
)
def test_compile_native_reports_failure_from_both_attempts(
    monkeypatch, tmp_path, static_error, dynamic_error, reported
):
    attempts = iter([
        compiler_module._CompileAttempt(False, static_error),
        compiler_module._CompileAttempt(False, dynamic_error),
    ])
    monkeypatch.setattr(compiler_module, "_run_compile", lambda command: next(attempts))
    capability = CompilerCapability("native", "cc", "linux", False)

    with pytest.raises(CompilerError, match=reported):
        compiler_module._compile(capability, tmp_path / "loader.c", tmp_path / "loader")


def test_compile_wsl_translates_paths_and_invokes_wsl_exec(monkeypatch, tmp_path):
    commands = []
    source = tmp_path / "loader.c"
    output = tmp_path / "loader"
    translated = {source: "/mnt/c/build/loader.c", output: "/mnt/c/build/loader"}

    monkeypatch.setattr(compiler_module, "_wsl_path", translated.__getitem__)
    monkeypatch.setattr(
        compiler_module.shutil,
        "which",
        lambda executable: "C:/Windows/wsl.exe" if executable == "wsl.exe" else None,
    )

    def fake_run(command):
        commands.append(command)
        return compiler_module._CompileAttempt(True, "")

    monkeypatch.setattr(compiler_module, "_run_compile", fake_run)
    capability = CompilerCapability("wsl", "/usr/bin/gcc", "linux-x86_64", False)

    assert compiler_module._compile(capability, source, output) is True
    assert commands[0][:3] == ["C:/Windows/wsl.exe", "--exec", "/usr/bin/gcc"]
    assert commands[0][-3:] == ["/mnt/c/build/loader.c", "-o", "/mnt/c/build/loader"]


def test_compile_wsl_requires_wsl_executable(monkeypatch, tmp_path):
    monkeypatch.setattr(compiler_module, "_wsl_path", lambda path: f"/tmp/{path.name}")
    monkeypatch.setattr(compiler_module.shutil, "which", lambda executable: None)
    capability = CompilerCapability("wsl", "/usr/bin/gcc", "linux-x86_64", False)

    with pytest.raises(CompilerError, match="wsl.exe is unavailable"):
        compiler_module._compile(capability, tmp_path / "loader.c", tmp_path / "loader")


def test_run_compile_captures_trimmed_stderr(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=7, stderr="  compile failed\n", stdout="")

    monkeypatch.setattr(compiler_module.subprocess, "run", fake_run)

    attempt = compiler_module._run_compile(["cc", "loader.c"])

    assert attempt == compiler_module._CompileAttempt(False, "compile failed")
    assert calls == [
        (["cc", "loader.c"], {"capture_output": True, "text": True, "timeout": 120})
    ]


def test_wsl_path_uses_wslpath_and_returns_trimmed_path(monkeypatch, tmp_path):
    calls = []

    def fake_which(executable):
        return "wsl" if executable == "wsl" else None

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="/mnt/c/work/loader.c\n", stderr="")

    monkeypatch.setattr(compiler_module.shutil, "which", fake_which)
    monkeypatch.setattr(compiler_module.subprocess, "run", fake_run)
    source = tmp_path / "loader.c"

    assert compiler_module._wsl_path(source) == "/mnt/c/work/loader.c"
    assert calls == [
        (
            ["wsl", "--exec", "wslpath", "-a", str(source)],
            {"capture_output": True, "text": True, "timeout": 15},
        )
    ]


@pytest.mark.parametrize(
    "probe",
    [
        SimpleNamespace(returncode=1, stdout="", stderr="bad path"),
        SimpleNamespace(returncode=0, stdout="\n", stderr=""),
    ],
)
def test_wsl_path_rejects_failed_translation(monkeypatch, tmp_path, probe):
    monkeypatch.setattr(compiler_module.shutil, "which", lambda executable: "wsl.exe")
    monkeypatch.setattr(compiler_module.subprocess, "run", lambda *args, **kwargs: probe)

    with pytest.raises(CompilerError, match="Could not translate path for WSL"):
        compiler_module._wsl_path(tmp_path / "loader.c")


def test_build_binary_orchestrates_generation_atomic_install_and_metadata(monkeypatch, tmp_path):
    capability = CompilerCapability("native", "/mock/cc", "linux", True)
    encrypted = EncryptedPayload(ciphertext=b"\xaa\xbb", key=b"k" * 16)
    tag = b"tag12345"
    stub = StubResult("int main(void) { return 0; }\n", ["timing"], 16)
    artifact = b"\x7fELFmock-binary"
    calls = {}

    monkeypatch.setattr(compiler_module, "detect_compiler", lambda: capability)

    def fake_encrypt(payload, rng, key_size):
        calls["encrypt"] = (payload, rng, key_size)
        return encrypted

    def fake_derive(value):
        calls["environment"] = value
        return tag

    def fake_stub(encrypted_payload, rng, **kwargs):
        calls["stub"] = (encrypted_payload, rng, kwargs)
        return stub

    def fake_compile(actual_capability, source, output):
        calls["compile"] = (actual_capability, source.read_text(encoding="utf-8"))
        output.write_bytes(artifact)
        return True

    monkeypatch.setattr(compiler_module, "encrypt_payload", fake_encrypt)
    monkeypatch.setattr(compiler_module, "derive_environment_tag", fake_derive)
    monkeypatch.setattr(compiler_module, "generate_stub", fake_stub)
    monkeypatch.setattr(compiler_module, "_compile", fake_compile)
    destination = tmp_path / "nested" / "program"
    destination.parent.mkdir()
    destination.write_bytes(b"old")

    result = build_binary(
        "echo caf\u00e9\n",
        str(destination),
        seed=77,
        anti_debug=False,
        environment_key="host-key",
    )

    assert calls["encrypt"][0] == "echo caf\u00e9\n".encode("utf-8")
    assert 16 <= calls["encrypt"][2] <= 64
    assert calls["environment"] == "host-key"
    assert calls["stub"][0] is encrypted
    assert calls["stub"][1] is calls["encrypt"][1]
    assert calls["stub"][2] == {"anti_debug": False, "environment_tag": tag}
    assert calls["compile"] == (capability, stub.source)
    assert destination.read_bytes() == artifact
    assert not list(destination.parent.glob(f".{destination.name}.tmp-*"))
    assert result == BinaryBuildResult(
        output_path=str(destination.resolve()),
        output_bytes=len(artifact),
        sha256=hashlib.sha256(artifact).hexdigest(),
        compiler=capability.compiler,
        backend=capability.backend,
        target=capability.target,
        static_linked=True,
        key_size=16,
        anti_debug_checks=["timing"],
    )
    assert result.to_dict()["sha256"] == hashlib.sha256(artifact).hexdigest()


def test_build_binary_without_environment_key_skips_derivation(monkeypatch, tmp_path):
    capability = CompilerCapability("native", "cc", "linux", False)
    captured = {}

    monkeypatch.setattr(compiler_module, "detect_compiler", lambda: capability)
    monkeypatch.setattr(
        compiler_module,
        "derive_environment_tag",
        lambda value: pytest.fail("environment derivation should be skipped"),
    )

    def fake_stub(encrypted, rng, **kwargs):
        captured.update(kwargs)
        return StubResult("source\n", [], len(encrypted.key))

    def fake_compile(capability, source, output):
        output.write_bytes(b"binary")
        return False

    monkeypatch.setattr(compiler_module, "generate_stub", fake_stub)
    monkeypatch.setattr(compiler_module, "_compile", fake_compile)

    result = build_binary("echo ok", str(tmp_path / "program"), seed=1)

    assert captured["environment_tag"] is None
    assert captured["anti_debug"] is True
    assert result.static_linked is False


def test_build_binary_is_deterministic_without_using_a_real_compiler(monkeypatch, tmp_path):
    capability = CompilerCapability("native", "mock-cc", "linux", False)
    monkeypatch.setattr(compiler_module, "detect_compiler", lambda: capability)

    def compile_source(capability, source, output):
        output.write_bytes(hashlib.sha256(source.read_bytes()).digest())
        return False

    monkeypatch.setattr(compiler_module, "_compile", compile_source)

    first = build_binary("printf deterministic", str(tmp_path / "first"), seed=8128)
    repeated = build_binary("printf deterministic", str(tmp_path / "second"), seed=8128)
    different = build_binary("printf deterministic", str(tmp_path / "third"), seed=8129)

    assert (tmp_path / "first").read_bytes() == (tmp_path / "second").read_bytes()
    assert first.sha256 == repeated.sha256
    assert first.key_size == repeated.key_size
    assert first.anti_debug_checks == repeated.anti_debug_checks
    assert first.sha256 != different.sha256


@pytest.mark.parametrize("artifact", [None, b""])
def test_build_binary_rejects_missing_or_empty_compiler_artifact(monkeypatch, tmp_path, artifact):
    capability = CompilerCapability("native", "cc", "linux", False)
    monkeypatch.setattr(compiler_module, "detect_compiler", lambda: capability)

    def fake_compile(capability, source, output):
        if artifact is not None:
            output.write_bytes(artifact)
        return True

    monkeypatch.setattr(compiler_module, "_compile", fake_compile)
    destination = tmp_path / "program"

    with pytest.raises(CompilerError, match="without producing an artifact"):
        build_binary("echo ok", str(destination), seed=5)

    assert not destination.exists()


def test_build_binary_rejects_integrity_before_detecting_a_compiler(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compiler_module,
        "detect_compiler",
        lambda: pytest.fail("integrity rejection must happen before compiler detection"),
    )

    with pytest.raises(CompilerError, match="external signature or checksum"):
        build_binary("echo ok", str(tmp_path / "program"), seed=5, integrity=True)


class _CliEngineResult:
    output = "printf 'compiled payload\\n'\n"
    seed = 9876
    layers_applied = ["id-mangle"]
    elapsed_ms = 2.5
    verified = False
    layer_stats = {}


class _CliEngine:
    def __init__(self, config):
        self.config = config

    def run(self, source):
        assert source == "echo source\n"
        return _CliEngineResult()


@pytest.mark.parametrize(
    ("extra_args", "expected_anti_debug"),
    [([], True), (["--no-anti-debug"], False)],
)
def test_cli_binary_mode_passes_engine_output_and_options_to_builder(
    monkeypatch, tmp_path, extra_args, expected_anti_debug
):
    calls = []
    artifact = b"\x7fELF"
    monkeypatch.setattr("obfush.cli.PolymorphicEngine", _CliEngine)

    def fake_build(payload, output_path, **kwargs):
        calls.append((payload, output_path, kwargs))
        Path(output_path).write_bytes(artifact)
        return BinaryBuildResult(
            output_path=str(Path(output_path).resolve()),
            output_bytes=len(artifact),
            sha256=hashlib.sha256(artifact).hexdigest(),
            compiler="mock-cc",
            backend="native",
            target="linux",
            static_linked=False,
            key_size=32,
            anti_debug_checks=["timing"] if expected_anti_debug else [],
        )

    monkeypatch.setattr(compiler_package, "build_binary", fake_build)
    destination = tmp_path / "program"
    result = CliRunner().invoke(
        main,
        [
            "-",
            str(destination),
            "--no-config",
            "--seed",
            "42",
            "--layers",
            "id-mangle",
            "--min-layers",
            "1",
            "--output-mode",
            "binary",
            "--env-key",
            "host-key",
            "--json-output",
            *extra_args,
        ],
        input="echo source\n",
    )

    assert result.exit_code == 0, result.output
    assert calls == [
        (
            _CliEngineResult.output,
            str(destination),
            {
                "seed": _CliEngineResult.seed,
                "anti_debug": expected_anti_debug,
                "environment_key": "host-key",
            },
        )
    ]
    metadata = json.loads(result.stdout)
    assert destination.read_bytes() == artifact
    assert metadata["output_mode"] == "binary"
    assert metadata["output_bytes"] == len(artifact)
    assert metadata["binary"]["compiler"] == "mock-cc"
    assert metadata["binary"]["key_size"] == 32
    assert metadata["binary"]["anti_debug_checks"] == (
        ["timing"] if expected_anti_debug else []
    )


def test_cli_binary_mode_reports_builder_failure(monkeypatch, tmp_path):
    monkeypatch.setattr("obfush.cli.PolymorphicEngine", _CliEngine)
    monkeypatch.setattr(
        compiler_package,
        "build_binary",
        lambda *args, **kwargs: (_ for _ in ()).throw(CompilerError("compiler unavailable")),
    )
    destination = tmp_path / "program"

    result = CliRunner().invoke(
        main,
        [
            "-",
            str(destination),
            "--no-config",
            "--output-mode",
            "binary",
        ],
        input="echo source\n",
    )

    assert result.exit_code == 1
    assert "Binary build error" in result.output
    assert "compiler unavailable" in result.output
    assert not destination.exists()


def test_cli_binary_mode_rejects_stdout_destination_before_running_engine(monkeypatch):
    class FailEngine:
        def __init__(self, config):
            pytest.fail("engine must not run for an invalid binary destination")

    monkeypatch.setattr("obfush.cli.PolymorphicEngine", FailEngine)

    result = CliRunner().invoke(
        main,
        ["-", "-", "--no-config", "--output-mode", "binary"],
        input="echo source\n",
    )

    assert result.exit_code == 2
    assert "Binary output requires a filesystem" in result.output


def test_cli_binary_dry_run_does_not_invoke_builder(monkeypatch, tmp_path):
    monkeypatch.setattr("obfush.cli.PolymorphicEngine", _CliEngine)
    monkeypatch.setattr(
        compiler_package,
        "build_binary",
        lambda *args, **kwargs: pytest.fail("dry-run must not build a binary"),
    )
    destination = tmp_path / "program"

    result = CliRunner().invoke(
        main,
        [
            "-",
            str(destination),
            "--no-config",
            "--output-mode",
            "binary",
            "--dry-run",
        ],
        input="echo source\n",
    )

    assert result.exit_code == 0, result.output
    assert "Dry run" in result.output
    assert not destination.exists()


def test_cli_binary_mode_rejects_explicit_empty_environment_key(monkeypatch, tmp_path):
    class FailEngine:
        def __init__(self, config):
            pytest.fail("empty environment key must be rejected before running the engine")

    monkeypatch.setattr("obfush.cli.PolymorphicEngine", FailEngine)

    result = CliRunner().invoke(
        main,
        [
            "-",
            str(tmp_path / "program"),
            "--no-config",
            "--output-mode",
            "binary",
            "--env-key",
            "",
        ],
        input="echo source\n",
    )

    assert result.exit_code == 2
    assert "--env-key must not be empty" in result.output


_NATIVE_COMPILER = None if os.name == "nt" else next(
    (shutil.which(name) for name in ("musl-gcc", "gcc", "clang", "cc") if shutil.which(name)),
    None,
)


@pytest.mark.skipif(
    _NATIVE_COMPILER is None,
    reason="optional smoke test requires a native Linux C compiler",
)
def test_native_compiler_smoke_builds_and_runs_loader(tmp_path):
    destination = tmp_path / "compiled-loader"

    result = build_binary(
        "printf 'binary:%s\\n' \"$1\"",
        str(destination),
        seed=4242,
        anti_debug=False,
    )
    completed = subprocess.run(
        [str(destination), "argument"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert destination.read_bytes().startswith(b"\x7fELF")
    assert result.output_bytes == destination.stat().st_size
    assert result.sha256 == hashlib.sha256(destination.read_bytes()).hexdigest()
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "binary:argument\n"
