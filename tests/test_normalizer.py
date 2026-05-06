"""Tests for the AST normaliser."""

import pytest
from obfush.engine.ast_parser import parse_bash
from obfush.engine.normalizer import normalize


class TestNormalize:
    """Test AST normalisation passes."""

    def test_normalise_preserves_structure(self):
        ast = parse_bash('echo "hello"')
        normalised = normalize(ast)
        assert normalised["type"] == "script"

    def test_scope_tracking(self):
        source = 'x=1\necho $x'
        ast = parse_bash(source)
        normalised = normalize(ast)
        scope = normalised.get("_scope")
        assert scope is not None
        assert isinstance(scope["globals"], set)
        assert isinstance(scope["reads"], set)

    def test_deep_copy(self):
        """Normalisation should not mutate the original AST."""
        ast = parse_bash('x=1')
        original_body_len = len(ast.get("body", []))
        normalize(ast)
        assert len(ast.get("body", [])) == original_body_len
