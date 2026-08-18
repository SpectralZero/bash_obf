"""Release-surface edge coverage without external VMs or toolchains."""

from __future__ import annotations

import builtins
import os
import runpy
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import click
import pytest
import xxhash
from click.testing import CliRunner

import obfush.cli as cli_module
import obfush.engine.verifier as verifier_module
import obfush.gui as gui_module
from obfush.batch import BatchItemResult
from obfush.cli import PRESETS, _apply_preset, _run_setup, _write_output_atomic, main
from obfush.config import ConfigError, load_config, validate_config
from obfush.engine.verifier import Verifier
from obfush.gui.app import create_app
from obfush.layers.base import LayerStats


@dataclass
class _EngineResult:
    source: str = "echo source\n"
    output: str = "echo transformed\n"
    seed: int = 42
    layers_applied: list[str] = field(default_factory=lambda: ["id-mangle"])
    layer_stats: dict[str, LayerStats] = field(
        default_factory=lambda: {"id-mangle": LayerStats(elapsed_ms=0.25)}
    )
    elapsed_ms: float = 1.25
    verified: bool = False


def _install_engine(monkeypatch, *, result=None, error: Exception | None = None):
    configs = []

    class Engine:
        def __init__(self, config):
            configs.append(config)

        def run(self, source):
            if error is not None:
                raise error
            return result or _EngineResult(source=source)

    monkeypatch.setattr(cli_module, "PolymorphicEngine", Engine)
    return configs


@pytest.fixture
def api_client():
    return create_app({"TESTING": True}).test_client()


def test_apply_preset_only_replaces_default_parameter_sources():
    sources = {
        "intensity": click.core.ParameterSource.COMMANDLINE,
        "force_layers": click.core.ParameterSource.DEFAULT,
        "min_layers": click.core.ParameterSource.DEFAULT,
        "eval_mode": click.core.ParameterSource.DEFAULT,
    }
    context = SimpleNamespace(get_parameter_source=sources.get)
    values = {
        "intensity": 0.2,
        "force_layers": None,
        "min_layers": 1,
        "eval_mode": "ok",
    }

    assert _apply_preset(context, None, values.copy()) == values
    resolved = _apply_preset(context, "stealth", values.copy())

    assert resolved["intensity"] == 0.2
    assert resolved["force_layers"] == PRESETS["stealth"]["force_layers"]
    assert resolved["min_layers"] == 4
    assert resolved["eval_mode"] == "no-eval"


def test_setup_applies_private_permissions_on_non_windows(monkeypatch, tmp_path):
    answers = iter(("standard", 0.7, "no-eval"))
    written = {}
    permissions = []
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(Path, "chmod", lambda self, mode: permissions.append((self, mode)))
    monkeypatch.setattr(click, "prompt", lambda *args, **kwargs: next(answers))
    monkeypatch.setattr(click, "confirm", lambda *args, **kwargs: False)
    monkeypatch.setattr(cli_module, "os", SimpleNamespace(name="posix"))

    def write_output(path, output):
        written["path"] = path
        written["output"] = output
        Path(path).write_text(output, encoding="utf-8")

    monkeypatch.setattr(cli_module, "_write_output_atomic", write_output)

    _run_setup()

    destination = tmp_path / ".obfushrc"
    assert written["path"] == str(destination)
    assert "eval_mode: no-eval" in written["output"]
    assert permissions == [(destination, 0o600)]


def test_atomic_write_reraises_when_failed_temporary_cleanup_disappears(
    monkeypatch, tmp_path,
):
    destination = tmp_path / "output.sh"
    destination.write_text("original", encoding="utf-8")
    temporary = None
    real_unlink = os.unlink

    def reject_replace(source, target):
        nonlocal temporary
        temporary = source
        raise OSError("replace denied")

    monkeypatch.setattr(cli_module.os, "replace", reject_replace)
    monkeypatch.setattr(cli_module.os, "unlink", lambda path: (_ for _ in ()).throw(FileNotFoundError()))

    with pytest.raises(OSError, match="replace denied"):
        _write_output_atomic(str(destination), "replacement")

    assert destination.read_text(encoding="utf-8") == "original"
    assert temporary is not None
    real_unlink(temporary)


def test_cli_reports_missing_gui_dependency(monkeypatch):
    real_import = builtins.__import__

    def reject_gui(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "obfush.gui" and "launch" in fromlist:
            raise ImportError("Flask unavailable")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", reject_gui)
    result = CliRunner().invoke(main, ["--gui"])

    assert result.exit_code == 1
    assert "GUI dependencies are missing; install obfush[gui]" in result.output


def test_cli_translates_config_loader_errors(monkeypatch, tmp_path):
    def fail_config(paths):
        raise ConfigError(f"invalid release config: {paths}")

    monkeypatch.setattr("obfush.config.load_config", fail_config)
    result = CliRunner().invoke(
        main,
        ["-", str(tmp_path / "output.sh"), "--no-config"],
        input="echo source\n",
    )

    assert result.exit_code == 2
    assert "invalid release config" in result.output


def test_cli_hashes_text_seed_and_parses_disabled_layers(monkeypatch, tmp_path):
    configs = _install_engine(monkeypatch)
    output = tmp_path / "output.sh"
    result = CliRunner().invoke(
        main,
        [
            "-", str(output), "--no-config", "--seed", "release-seed",
            "--no-layer", "encode, poly-shell",
        ],
        input="echo source\n",
    )

    assert result.exit_code == 0, result.output
    assert configs[0].seed == xxhash.xxh64(b"release-seed").intdigest()
    assert configs[0].disable_layers == ["encode", "poly-shell"]
    assert output.read_text(encoding="utf-8") == "echo transformed\n"


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["--benchmark", "missing.sh", "--no-config"], "Input script does not exist"),
        (["--batch", "INPUT", "OUTPUT", "--dump-ast", "ast.json"], "not supported"),
    ],
)
def test_cli_rejects_late_mode_validation(arguments, message, tmp_path):
    if "INPUT" in arguments:
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / "one.sh").write_text("echo one\n", encoding="utf-8")
        arguments = [
            str(input_dir) if value == "INPUT" else str(tmp_path / "out")
            if value == "OUTPUT" else value
            for value in arguments
        ]
        arguments.append("--no-config")

    result = CliRunner().invoke(main, arguments)

    assert result.exit_code == 2
    assert message in result.output


def test_cli_translates_batch_orchestration_failure(monkeypatch, tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    monkeypatch.setattr(
        "obfush.batch.process_batch",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("batch storage offline")),
    )

    result = CliRunner().invoke(main, [
        "--batch", str(input_dir), str(tmp_path / "output"), "--no-config",
    ])

    assert result.exit_code == 1
    assert "batch storage offline" in result.output


@pytest.mark.parametrize("failed", [False, True])
def test_cli_human_batch_summary_and_exit_status(monkeypatch, tmp_path, failed):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    items = [BatchItemResult(
        input_path=str(input_dir / "good.sh"),
        output_path=str(tmp_path / "output" / "good.sh"),
        status="ok",
        seed=1,
        source_bytes=10,
        output_bytes=20,
        elapsed_ms=1.0,
        layers_applied=["id-mangle"],
        verified=False,
    )]
    if failed:
        items.append(BatchItemResult(
            input_path=str(input_dir / "bad.sh"),
            output_path=str(tmp_path / "output" / "bad.sh"),
            status="error",
            seed=None,
            source_bytes=0,
            output_bytes=0,
            elapsed_ms=0.0,
            layers_applied=[],
            verified=False,
            error="invalid source",
        ))
    monkeypatch.setattr("obfush.batch.process_batch", lambda *args, **kwargs: items)

    result = CliRunner().invoke(main, [
        "--batch", str(input_dir), str(tmp_path / "output"), "--no-config",
    ])

    assert result.exit_code == (1 if failed else 0)
    assert "OK" in result.output
    assert f"{1} succeeded, {int(failed)} failed" in result.output
    if failed:
        assert "invalid source" in result.output


@pytest.mark.parametrize(
    ("source", "benchmark_error", "message"),
    [
        (" \n", None, "Input script is empty"),
        ("echo source\n", RuntimeError("clock failed"), "clock failed"),
    ],
)
def test_cli_translates_benchmark_failures(
    monkeypatch, tmp_path, source, benchmark_error, message,
):
    input_path = tmp_path / "input.sh"
    input_path.write_text(source, encoding="utf-8")
    if benchmark_error is not None:
        monkeypatch.setattr(
            "obfush.benchmark.benchmark_engine",
            lambda *args, **kwargs: (_ for _ in ()).throw(benchmark_error),
        )

    result = CliRunner().invoke(
        main,
        ["--benchmark", str(input_path), "--no-config"],
    )

    assert result.exit_code == 1
    assert message in result.output


def test_cli_reports_source_read_failure(monkeypatch, tmp_path):
    source_path = tmp_path / "input.sh"
    source_path.write_text("echo source\n", encoding="utf-8")
    monkeypatch.setattr(
        cli_module,
        "_read_source",
        lambda path: (_ for _ in ()).throw(PermissionError("read denied")),
    )

    result = CliRunner().invoke(
        main,
        [str(source_path), str(tmp_path / "output.sh"), "--no-config"],
    )

    assert result.exit_code == 1
    assert "Error reading input" in result.output
    assert "read denied" in result.output


def test_cli_rejects_empty_single_file_source(tmp_path):
    result = CliRunner().invoke(
        main,
        ["-", str(tmp_path / "output.sh"), "--no-config"],
        input="  \n",
    )

    assert result.exit_code == 1
    assert "Input script is empty" in result.output


def test_cli_reports_output_write_failure(monkeypatch, tmp_path):
    _install_engine(monkeypatch)
    monkeypatch.setattr(
        cli_module,
        "_write_output",
        lambda *args: (_ for _ in ()).throw(OSError("disk full")),
    )

    result = CliRunner().invoke(
        main,
        ["-", str(tmp_path / "output.sh"), "--no-config"],
        input="echo source\n",
    )

    assert result.exit_code == 1
    assert "Error writing output" in result.output
    assert "disk full" in result.output


def test_cli_non_verbose_engine_failure_omits_traceback(monkeypatch, tmp_path):
    _install_engine(monkeypatch, error=RuntimeError("transform rejected"))

    result = CliRunner().invoke(
        main,
        ["-", str(tmp_path / "output.sh"), "--no-config"],
        input="echo source\n",
    )

    assert result.exit_code == 1
    assert "Engine error" in result.output
    assert "transform rejected" in result.output
    assert "Traceback" not in result.output


def test_cli_verbose_success_prints_entropy_report(monkeypatch, tmp_path):
    _install_engine(monkeypatch)
    output = tmp_path / "output.sh"

    result = CliRunner().invoke(
        main,
        ["-", str(output), "--no-config", "--verbose"],
        input="echo source\n",
    )

    assert result.exit_code == 0, result.output
    assert "Written to" in result.output
    assert "Entropy Analysis" in result.output
    assert output.exists()


def test_cli_json_dry_run_has_no_output_path(monkeypatch, tmp_path):
    import json

    _install_engine(monkeypatch)
    output = tmp_path / "output.sh"
    result = CliRunner().invoke(
        main,
        ["-", str(output), "--no-config", "--dry-run", "--json-output"],
        input="echo source\n",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is True
    assert payload["output_path"] is None
    assert not output.exists()


def test_cli_module_main_guard_invokes_click_command(monkeypatch):
    invoked = []

    def command_call(command, *args, **kwargs):
        invoked.append(command.name)

    monkeypatch.setattr(click.Command, "__call__", command_call)
    runpy.run_path(cli_module.__file__, run_name="__main__")

    assert invoked == ["main"]


def test_package_main_module_delegates_to_cli(monkeypatch):
    invoked = []
    monkeypatch.setattr(cli_module, "main", lambda: invoked.append("main"))

    runpy.run_module("obfush.__main__", run_name="__main__")

    assert invoked == ["main"]


def test_gui_launch_schedules_browser_and_runs_fixed_server(monkeypatch):
    runs = []
    timers = []

    class App:
        def run(self, **options):
            runs.append(options)

    class Timer:
        def __init__(self, delay, callback, args):
            timers.append((delay, callback, args))

        def start(self):
            timers.append("started")

    monkeypatch.setattr(gui_module, "create_app", App)
    monkeypatch.setattr(gui_module.threading, "Timer", Timer)

    gui_module.launch(host="0.0.0.0", port=6123, debug=True)
    gui_module.launch(host="127.0.0.1", port=5001, open_browser=False)

    assert timers[0] == (0.75, gui_module.webbrowser.open, ("http://0.0.0.0:6123/",))
    assert timers[1] == "started"
    assert runs == [
        {"host": "0.0.0.0", "port": 6123, "debug": True, "use_reloader": False},
        {"host": "127.0.0.1", "port": 5001, "debug": False, "use_reloader": False},
    ]


def test_gui_app_factory_uses_default_configuration():
    app = create_app()

    assert app.config["MAX_CONTENT_LENGTH"] == 1_048_576
    assert app.config["JSON_SORT_KEYS"] is False
    assert app.test_client().get("/").status_code == 200


@pytest.mark.parametrize("error", [RuntimeError("engine rejected source"), RuntimeError()])
def test_gui_obfuscate_translates_engine_failures(monkeypatch, api_client, error):
    class Engine:
        def __init__(self, config):
            self.config = config

        def run(self, source):
            raise error

    monkeypatch.setattr("obfush.gui.api.PolymorphicEngine", Engine)

    response = api_client.post("/api/obfuscate", json={"source": "echo source\n"})
    payload = response.get_json()["error"]

    assert response.status_code == 422
    assert payload["code"] == "processing_error"
    assert payload["message"] == (str(error) or "Obfuscation failed")


@pytest.mark.parametrize(
    ("config", "field", "message"),
    [
        ({"eval_mode": "unsafe"}, "eval_mode", "eval_mode must be"),
        ({"layers": "id-mangle"}, "layers", "layers must be a list"),
        ({"layers": ["id-mangle", "id-mangle"]}, "layers", "duplicates"),
        ({"seed": True}, "seed", "integer or string"),
        ({"seed": ""}, "seed", "1-256 characters"),
        ({"seed": -1}, "seed", "unsigned"),
        ({"intensity": 2}, "intensity", "between 0.0 and 1.0"),
        ({"min_layers": 1.5}, "min_layers", "must be an integer"),
        ({"min_layers": 0}, "min_layers", "between 1"),
    ],
)
def test_gui_rejects_config_boundary_values(api_client, config, field, message):
    response = api_client.post(
        "/api/obfuscate",
        json={"source": "echo source\n", **config},
    )
    payload = response.get_json()["error"]

    assert response.status_code == 400
    assert payload["field"] == field
    assert message in payload["message"]


def test_gui_resolves_hashed_seed_preset_and_explicit_layer_minimum(
    monkeypatch, api_client,
):
    configs = []

    class Engine:
        def __init__(self, config):
            configs.append(config)

        def run(self, source):
            return _EngineResult(source=source, seed=configs[-1].seed)

    monkeypatch.setattr("obfush.gui.api.PolymorphicEngine", Engine)

    preset_response = api_client.post("/api/obfuscate", json={
        "source": "echo preset\n", "preset": "stealth", "seed": "release-seed",
    })
    layer_response = api_client.post("/api/obfuscate", json={
        "source": "echo layers\n", "layers": ["id-mangle"], "min_layers": 2,
    })

    assert preset_response.status_code == 200
    assert configs[0].seed == xxhash.xxh64(b"release-seed").intdigest()
    assert configs[0].force_layers == PRESETS["stealth"]["force_layers"].split(",")
    assert layer_response.status_code == 200
    assert configs[1].force_layers == ["id-mangle"]
    assert configs[1].min_layers == 2


@pytest.mark.parametrize(
    ("payload", "field", "message"),
    [
        ({"files": [{}] * 101}, "files", "at most 100"),
        ({"files": [{"name": "one.sh", "source": "echo one"}], "config": []},
         "config", "config must be an object"),
        ({"files": [{"name": "one.sh", "source": "echo one"}],
          "config": {"unknown": True}}, "config", "Unknown config field"),
        ({"files": ["one.sh"]}, "files[0]", "Each file must be an object"),
        ({"files": [{"name": "one.sh", "source": "echo one", "mode": "x"}]},
         "files[0]", "Unknown file field"),
        ({"files": [{"name": "", "source": "echo one"}]},
         "files[0]", "base .sh filename"),
    ],
)
def test_gui_batch_rejects_queue_and_config_shapes(api_client, payload, field, message):
    response = api_client.post("/api/batch", json=payload)
    error = response.get_json()["error"]

    assert response.status_code == 400
    assert error["field"] == field
    assert message in error["message"]


def test_gui_batch_uses_fallback_message_for_empty_exception(monkeypatch, api_client):
    class Engine:
        def __init__(self, config):
            self.config = config

        def run(self, source):
            raise RuntimeError()

    monkeypatch.setattr("obfush.gui.api.PolymorphicEngine", Engine)
    response = api_client.post("/api/batch", json={
        "files": [{"name": "one.sh", "source": "echo one\n"}],
    })

    assert response.status_code == 200
    assert response.get_json()["items"] == [{
        "name": "one.sh", "status": "error", "error": "Obfuscation failed",
    }]
    assert response.get_json()["summary"] == {"total": 1, "succeeded": 0, "failed": 1}


def test_verifier_json_success_is_structured(monkeypatch):
    verifier = Verifier(bash_path="bash")
    monkeypatch.setattr(verifier, "verify", lambda *args: True)

    assert verifier.verify_json("original", "obfuscated") == {
        "passed": True,
        "stdout_match": True,
        "exit_code_match": True,
        "stderr_warning": False,
        "diff": None,
    }


def test_verifier_structures_unexpected_process_errors(monkeypatch):
    verifier = Verifier(bash_path="bash")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("execution denied")),
    )

    result = verifier._run_script("echo source")

    assert result["exit_code"] == -2
    assert result["stderr"] == b"execution denied"
    assert result["error"] == "PermissionError: execution denied"
    assert result["timed_out"] is False


def test_verifier_ignores_cleanup_failure_after_success(monkeypatch):
    verifier = Verifier(bash_path="bash")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0, b"ok", b""),
    )
    monkeypatch.setattr(
        verifier_module.os,
        "unlink",
        lambda path: (_ for _ in ()).throw(OSError("locked")),
    )

    result = verifier._run_script("printf ok")

    assert result["stdout"] == b"ok"
    assert result["exit_code"] == 0


@pytest.mark.parametrize(
    ("system", "available", "expected"),
    [
        ("Linux", set(), None),
        ("Windows", {r"C:\Program Files\Git\bin\bash.exe"},
         r"C:\Program Files\Git\bin\bash.exe"),
        ("Windows", set(), None),
    ],
)
def test_verifier_bash_platform_fallbacks(monkeypatch, system, available, expected):
    checked = []
    monkeypatch.setattr(verifier_module.shutil, "which", lambda executable: None)
    monkeypatch.setattr(verifier_module.platform, "system", lambda: system)

    def is_file(path):
        checked.append(path)
        return path in available

    monkeypatch.setattr(verifier_module.os.path, "isfile", is_file)

    assert Verifier._find_bash() == expected
    if system == "Linux":
        assert checked == []
    elif expected is not None:
        assert checked[-1] == expected
    else:
        assert len(checked) == 5


@pytest.mark.parametrize(
    ("kind", "message"),
    [
        ("missing", "Could not read configuration"),
        ("unicode", "Could not read configuration"),
        ("yaml", "Could not read configuration"),
    ],
)
def test_config_io_and_parse_errors_are_contextualized(tmp_path, kind, message):
    config = tmp_path / "release.yml"
    if kind == "unicode":
        config.write_bytes(b"intensity: \xff\n")
    elif kind == "yaml":
        config.write_text("[unterminated\n", encoding="utf-8")

    with pytest.raises(ConfigError, match=message) as captured:
        load_config([config])

    assert str(config) in str(captured.value)


def test_blank_config_is_ignored_when_merging(tmp_path):
    blank = tmp_path / "blank.yml"
    values = tmp_path / "values.yml"
    blank.write_text("# intentionally blank\n", encoding="utf-8")
    values.write_text("intensity: 0.5\n", encoding="utf-8")

    assert load_config([blank, values]) == {"intensity": 0.5}


def test_absolute_config_test_input_is_preserved(tmp_path):
    payload = tmp_path / "stdin.txt"
    payload.write_text("release input", encoding="utf-8")
    config = tmp_path / "release.yml"
    config.write_text(f"test_input: '{payload.as_posix()}'\n", encoding="utf-8")

    assert load_config([config])["test_input"] == str(payload.resolve())


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({"preset": "unknown"}, "preset must be"),
        ({"seed": []}, "seed must be a string or integer"),
        ({"log_level": 3}, "log_level must be a string"),
        ({"log_level": "trace"}, "log_level must be DEBUG"),
        ({"output_mode": "archive"}, "output_mode must be script or binary"),
    ],
)
def test_config_rejects_release_option_values(config, message):
    with pytest.raises(ConfigError, match=message):
        validate_config(config)


def test_config_normalizes_valid_logging_and_environment_values():
    assert validate_config({
        "log_level": "info",
        "environment_key": "production",
    }) == {
        "log_level": "INFO",
        "environment_key": "production",
    }
