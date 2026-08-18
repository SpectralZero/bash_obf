"""Poly-shell loader regression tests."""

import random

from obfush.engine.ast_emitter import emit
from obfush.layers.poly_shell import _build_loader, _encode_chunks, _split_payload


class _MethodSelector:
    def __init__(self, method):
        self.method = method

    def choice(self, methods):
        assert self.method in methods
        return self.method


def test_split_payload_preserves_source_exactly():
    source = "if true; then\n  echo one\n  echo two\nfi\n"

    chunks = _split_payload(source, 3, random.Random(42))

    assert "".join(chunks) == source


def test_hex_decoder_has_no_xxd_dependency():
    encoded = _encode_chunks(["echo hello\n"], _MethodSelector("hex"))

    assert "xxd" not in encoded[0]["decode_expr"]
    assert "printf '%b'" in encoded[0]["decode_expr"]


def test_no_eval_loader_is_emitted_as_shell_syntax():
    encoded = _encode_chunks(["echo hello\n"], _MethodSelector("base64"))

    output = emit(_build_loader(encoded, random.Random(42), "no-eval"))

    assert "mktemp" in output
    assert "source \"${" in output
    assert "rm -f" in output
    assert "eval " not in output
    assert "%.}" in output
