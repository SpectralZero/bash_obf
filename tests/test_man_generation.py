"""Regression tests for the deterministic Click help man-page generator."""

from pathlib import Path

from scripts.generate_man import click_help, generate, render_man


ROOT = Path(__file__).resolve().parents[1]


def test_man_page_is_generated_from_current_plain_click_help() -> None:
    generated = ROOT / "docs" / "obfush.1"
    assert generated.read_text(encoding="utf-8") == render_man(click_help())


def test_generate_is_repeatable(tmp_path: Path) -> None:
    generated = tmp_path / "obfush.1"
    generate(generated)
    first = generated.read_bytes()
    generate(generated)

    assert generated.read_bytes() == first
    assert b"Usage: obfush [OPTIONS] [INPUT_SCRIPT] [OUTPUT_SCRIPT]" in first
    assert b"\\-\\-help\\-advanced" in first


def test_man_page_has_stable_metadata_and_no_terminal_control_codes() -> None:
    content = (ROOT / "docs" / "obfush.1").read_text(encoding="utf-8")
    assert content.startswith('.TH OBFUSH 1 "obfush" "2.0.0-dev" "Internal tooling"\n')
    assert "\x1b" not in content
    assert "2026-" not in content
    assert "\r" not in content
