"""Tests for the AST emitter — round-trip parse→emit."""

from obfush.engine.ast_parser import parse_bash
from obfush.engine.ast_emitter import emit


class TestEmitter:
    """Test AST → bash source emitter."""

    def test_simple_echo(self):
        source = 'echo "hello"'
        ast = parse_bash(source)
        output = emit(ast)
        assert "echo" in output
        assert "hello" in output

    def test_shebang_preserved(self):
        source = '#!/bin/bash\necho "test"'
        ast = parse_bash(source)
        output = emit(ast)
        assert output.startswith("#!/bin/bash")

    def test_assignment(self):
        source = 'x="hello"'
        ast = parse_bash(source)
        output = emit(ast)
        assert output.strip(), f"Empty output for assignment: {output!r}"

    def test_round_trip_non_empty(self):
        """Emitted output should not be empty for valid input."""
        sources = [
            'echo hello',
            'x=1; echo $x',
            'true && echo yes',
        ]
        for source in sources:
            ast = parse_bash(source)
            output = emit(ast)
            assert output.strip(), f"Empty output for: {source}"

    def test_sole_parameter_expansion_is_kept_as_one_word(self):
        ast = parse_bash('printf "%s\\n" "$value"')
        output = emit(ast)
        assert '"$value"' in output
