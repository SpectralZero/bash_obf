#!/usr/bin/env python3
"""Generate the obfush(1) page from the Click command's plain help."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from click.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "obfush.1"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from obfush import __version__  # noqa: E402
from obfush.cli import main  # noqa: E402


def click_help() -> str:
    """Return Click help without terminal styling or platform line endings."""
    result = CliRunner().invoke(
        main,
        ["--help"],
        color=False,
        prog_name="obfush",
        terminal_width=80,
    )
    if result.exit_code != 0:
        raise RuntimeError(
            f"could not collect Click help (exit code {result.exit_code})"
        ) from result.exception
    return result.output.replace("\r\n", "\n").rstrip() + "\n"


def _roff_escape(line: str) -> str:
    """Escape the small set of roff control characters used in CLI help."""
    line = line.replace("\\", "\\e").replace("-", "\\-")
    if line.startswith(".") or line.startswith("'"):
        line = "\\&" + line
    return line


def render_man(help_text: str) -> str:
    """Render normalized Click help as a deterministic man page."""
    normalized = re.sub(r"[ \t]+$", "", help_text.replace("\r\n", "\n")).rstrip()
    body = "\n".join(_roff_escape(line) for line in normalized.split("\n"))
    return (
        f'.TH OBFUSH 1 "obfush" "{__version__}" "Internal tooling"\n'
        ".SH NAME\n"
        "obfush \\- transform Bash source into an obfuscated Bash script\n"
        ".SH SYNOPSIS\n"
        ".B obfush\n"
        ".SH DESCRIPTION\n"
        "This page is generated from the Click command's plain \\fB--help\\fR output.\n"
        "It documents the command surface available in this source tree.\n"
        ".SH OPTIONS\n"
        ".nf\n"
        f"{body}\n"
        ".fi\n"
        ".SH DISTRIBUTION\n"
        "obfush is proprietary internal tooling. Use and redistribution are\n"
        "restricted by LICENSE and the organization's authorization process.\n"
        "This repository does not configure automatic public publication.\n"
    )


def generate(output: Path = OUTPUT) -> None:
    """Write the generated page using stable UTF-8 Unix newlines."""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_man(click_help()), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    generate()
