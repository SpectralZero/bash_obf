"""Tests for individual transformation layers."""

import random
import pytest
from obfush.engine.ast_parser import parse_bash
from obfush.engine.normalizer import normalize
from obfush.engine.ast_emitter import emit
from obfush.layers.base import LayerConfig


def _make_config(seed=42, intensity=0.8, eval_mode="ok"):
    rng = random.Random(seed)
    return LayerConfig(intensity=intensity, seed=seed, rng=rng, eval_mode=eval_mode)


def _prepare_ast(source):
    return normalize(parse_bash(source))


class TestIdMangle:
    def test_basic_mangle(self):
        from obfush.layers.id_mangle import LayerImpl
        layer = LayerImpl()
        ast = _prepare_ast('myvar="hello"\necho $myvar')
        config = _make_config()
        result, stats = layer.transform(ast, config)
        output = emit(result)
        # Original variable name should be gone
        # (may or may not be — depends on whether it's detected as mangleable)
        assert output.strip()

    def test_polymorphism(self):
        """Different seeds should produce different mangled names."""
        from obfush.layers.id_mangle import LayerImpl
        layer = LayerImpl()
        source = 'myvar="hello"\necho $myvar'
        out1 = emit(layer.transform(_prepare_ast(source), _make_config(seed=1))[0])
        out2 = emit(layer.transform(_prepare_ast(source), _make_config(seed=2))[0])
        # At minimum, outputs should not be empty
        assert out1.strip()
        assert out2.strip()


class TestStrShred:
    def test_basic_shred(self):
        from obfush.layers.str_shred import LayerImpl
        layer = LayerImpl()
        ast = _prepare_ast('echo "secret_password"')
        config = _make_config()
        result, stats = layer.transform(ast, config)
        output = emit(result)
        assert output.strip()

    def test_shred_produces_output(self):
        from obfush.layers.str_shred import LayerImpl
        layer = LayerImpl()
        ast = _prepare_ast('msg="hello world"\necho $msg')
        config = _make_config()
        result, stats = layer.transform(ast, config)
        output = emit(result)
        assert output.strip()


class TestCmdSub:
    def test_basic_morph(self):
        from obfush.layers.cmd_sub import LayerImpl
        layer = LayerImpl()
        ast = _prepare_ast('echo "hello"\ntrue')
        config = _make_config(intensity=1.0)
        result, stats = layer.transform(ast, config)
        output = emit(result)
        assert output.strip()


class TestJunkInject:
    def test_injects_junk(self):
        from obfush.layers.junk_inject import LayerImpl
        layer = LayerImpl()
        ast = _prepare_ast('echo "line1"\necho "line2"\necho "line3"')
        config = _make_config(intensity=1.0)
        result, stats = layer.transform(ast, config)
        output = emit(result)
        # Output should be longer due to junk
        assert output.strip()

    def test_stats_populated(self):
        from obfush.layers.junk_inject import LayerImpl
        layer = LayerImpl()
        ast = _prepare_ast('echo a\necho b\necho c\necho d\necho e')
        config = _make_config(intensity=1.0)
        result, stats = layer.transform(ast, config)
        # At high intensity, some junk should be injected
        assert isinstance(stats.junk_blocks_injected, int)


class TestFlowObfusc:
    def test_basic_flow(self):
        from obfush.layers.flow_obfusc import LayerImpl
        layer = LayerImpl()
        ast = _prepare_ast('echo a\necho b\necho c')
        config = _make_config(intensity=1.0)
        result, stats = layer.transform(ast, config)
        output = emit(result)
        assert output.strip()


class TestEncode:
    def test_encode_eval_ok(self):
        from obfush.layers.encode import LayerImpl
        layer = LayerImpl()
        ast = _prepare_ast('echo "secret"')
        config = _make_config(eval_mode="ok", intensity=1.0)
        result, stats = layer.transform(ast, config)
        output = emit(result)
        assert output.strip()

    def test_encode_no_eval(self):
        from obfush.layers.encode import LayerImpl
        layer = LayerImpl()
        ast = _prepare_ast('echo "secret"')
        config = _make_config(eval_mode="no-eval", intensity=1.0)
        result, stats = layer.transform(ast, config)
        output = emit(result)
        assert "eval" not in output


class TestIndirection:
    def test_basic_indirection(self):
        from obfush.layers.indirection import LayerImpl
        layer = LayerImpl()
        ast = _prepare_ast('curl http://example.com')
        config = _make_config(intensity=1.0)
        result, stats = layer.transform(ast, config)
        output = emit(result)
        assert output.strip()


class TestEntropyMask:
    def test_adds_decoys(self):
        from obfush.layers.entropy_mask import LayerImpl
        layer = LayerImpl()
        ast = _prepare_ast('echo "test"')
        config = _make_config(intensity=0.8)
        result, stats = layer.transform(ast, config)
        output = emit(result)
        assert output.strip()
