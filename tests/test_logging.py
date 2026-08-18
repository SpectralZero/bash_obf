"""Structured logging and stream-isolation tests."""

import io
import json
import logging

from click.testing import CliRunner

from obfush.cli import main
from obfush.logging_utils import configure_logging, get_logger


def test_json_formatter_emits_structured_extra_fields_and_exception():
    stream = io.StringIO()
    logger = configure_logging("DEBUG", stream=stream)
    try:
        raise ValueError("failed")
    except ValueError:
        logger.exception(
            "operation_failed",
            extra={"event": "operation_failed", "item": "sample.sh"},
        )

    payload = json.loads(stream.getvalue())
    assert payload["level"] == "ERROR"
    assert payload["logger"] == "obfush"
    assert payload["message"] == "operation_failed"
    assert payload["event"] == "operation_failed"
    assert payload["item"] == "sample.sh"
    assert "ValueError: failed" in payload["exception"]
    assert payload["timestamp"].endswith("+00:00")


def test_log_level_filters_records():
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)
    logger = get_logger("test")
    logger.debug("hidden")
    logger.info("visible", extra={"event": "visible"})
    payload = json.loads(stream.getvalue())
    assert payload["message"] == "visible"
    assert payload["logger"] == "obfush.test"


def test_configure_logging_does_not_modify_root_logger():
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    configure_logging("WARNING", stream=io.StringIO())
    assert root.handlers == original_handlers


def test_cli_debug_logs_stay_off_stdout_json(tmp_path):
    destination = tmp_path / "output.sh"
    result = CliRunner(mix_stderr=False).invoke(main, [
        "-", str(destination), "--no-config", "--seed", "42",
        "--layers", "id-mangle", "--min-layers", "1",
        "--json-output", "--log-level", "DEBUG",
    ], input="echo hello\n")

    assert result.exit_code == 0, result.stderr
    metadata = json.loads(result.stdout)
    assert metadata["seed"] == 42
    log_lines = [json.loads(line) for line in result.stderr.splitlines() if line.strip()]
    events = {line.get("event") for line in log_lines}
    assert "configuration_resolved" in events
    assert "engine_started" in events
    assert "layer_completed" in events
    assert "engine_completed" in events


def test_cli_warning_default_emits_no_structured_logs(tmp_path):
    destination = tmp_path / "output.sh"
    result = CliRunner(mix_stderr=False).invoke(main, [
        "-", str(destination), "--no-config", "--seed", "42",
        "--layers", "id-mangle", "--min-layers", "1", "--json-output",
    ], input="echo hello\n")
    assert result.exit_code == 0
    assert result.stderr == ""
