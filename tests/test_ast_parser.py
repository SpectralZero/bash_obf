"""Tests for the AST parser."""

import pytest
from obfush.engine.ast_parser import parse_bash


class TestParseBash:
    """Test the bash AST parser."""

    def test_simple_echo(self):
        ast = parse_bash('echo "hello"')
        assert ast["type"] == "script"
        assert len(ast["body"]) >= 1

    def test_shebang_preserved(self):
        source = '#!/bin/bash\necho "test"'
        ast = parse_bash(source)
        assert ast.get("shebang") == "#!/bin/bash"

    def test_variable_assignment(self):
        ast = parse_bash('x="hello"')
        assert ast["type"] == "script"
        body = ast["body"]
        assert len(body) >= 1

    def test_pipeline(self):
        ast = parse_bash('echo "data" | grep "d"')
        assert ast["type"] == "script"

    def test_command_substitution(self):
        ast = parse_bash('result=$(echo hello)')
        assert ast["type"] == "script"

    def test_function_definition(self):
        ast = parse_bash('myfunc() { echo "inside"; }')
        assert ast["type"] == "script"

    def test_conditional(self):
        ast = parse_bash('if true; then echo yes; fi')
        assert ast["type"] == "script"

    def test_for_loop(self):
        ast = parse_bash('for i in 1 2 3; do echo $i; done')
        assert ast["type"] == "script"

    def test_empty_input(self):
        ast = parse_bash('')
        assert ast["type"] == "script"

    def test_arithmetic_fallback(self):
        """Arithmetic expressions should be preserved via fallback."""
        ast = parse_bash('x=$((1 + 2))')
        assert ast["type"] == "script"
        # Should not crash — fallback handles it

    def test_complex_param_fallback(self):
        """Complex parameter expansions should be preserved."""
        ast = parse_bash('echo ${var#pattern}')
        assert ast["type"] == "script"

    def test_multiline(self):
        source = 'x=1\ny=2\necho $x $y'
        ast = parse_bash(source)
        assert ast["type"] == "script"
        assert len(ast["body"]) >= 1


class TestAssignmentDetection:
    """Test that assignments are properly detected."""

    def test_simple_assignment(self):
        ast = parse_bash('myvar="hello"')
        body = ast["body"]
        # Should find an assignment node somewhere in the tree
        found = _find_nodes(ast, "assignment")
        assert len(found) >= 1

    def test_multiple_assignments(self):
        ast = parse_bash('a=1\nb=2\nc=3')
        found = _find_nodes(ast, "assignment")
        assert len(found) >= 1


def _find_nodes(node, node_type):
    """Recursively find nodes of a given type."""
    results = []
    if not isinstance(node, dict):
        return results
    if node.get("type") == node_type:
        results.append(node)
    for key in ("body", "parts", "test_parts"):
        val = node.get(key)
        if isinstance(val, list):
            for item in val:
                results.extend(_find_nodes(item, node_type))
        elif isinstance(val, dict):
            results.extend(_find_nodes(val, node_type))
    return results
