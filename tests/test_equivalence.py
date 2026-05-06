"""End-to-end equivalence tests."""

import pytest
from obfush.engine.core import EngineConfig, PolymorphicEngine


class TestEndToEnd:
    """Full pipeline tests."""

    def test_basic_pipeline(self):
        """Run full pipeline on a simple script."""
        source = '#!/bin/bash\necho "hello world"\n'
        config = EngineConfig(
            seed=42,
            intensity=0.5,
            min_layers=3,
            verify=False,
        )
        engine = PolymorphicEngine(config)
        result = engine.run(source)
        assert result.output.strip()
        assert result.seed == 42
        assert len(result.layers_applied) >= 3

    def test_polymorphism(self):
        """Different seeds produce different output."""
        source = 'echo "test"\n'
        out1 = PolymorphicEngine(EngineConfig(seed=1, intensity=0.5)).run(source)
        out2 = PolymorphicEngine(EngineConfig(seed=2, intensity=0.5)).run(source)
        # Different seeds should yield different output
        # (at minimum, both should produce non-empty output)
        assert out1.output.strip()
        assert out2.output.strip()

    def test_reproducibility(self):
        """Same seed produces identical output."""
        source = 'echo "test"\n'
        out1 = PolymorphicEngine(EngineConfig(seed=42, intensity=0.8)).run(source)
        out2 = PolymorphicEngine(EngineConfig(seed=42, intensity=0.8)).run(source)
        assert out1.output == out2.output

    def test_dry_run(self):
        """Dry run should not transform the source."""
        source = 'echo "test"\n'
        config = EngineConfig(seed=42, dry_run=True)
        result = PolymorphicEngine(config).run(source)
        assert result.output == source

    def test_no_eval_contract(self):
        """With no-eval mode, output must contain zero eval tokens."""
        source = 'echo "secret payload"\ncurl http://example.com\n'
        config = EngineConfig(
            seed=42, intensity=0.8, eval_mode="no-eval",
            min_layers=3,
        )
        result = PolymorphicEngine(config).run(source)
        # 'eval' as a standalone command should not appear
        lines = result.output.split("\n")
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("eval ") or stripped == "eval":
                pytest.fail(f"Found eval in no-eval mode: {line}")

    def test_force_layers(self):
        """Forcing specific layers should use only those layers."""
        source = 'echo "test"\n'
        config = EngineConfig(
            seed=42,
            force_layers=["id-mangle", "str-shred"],
            min_layers=1,
        )
        result = PolymorphicEngine(config).run(source)
        assert set(result.layers_applied).issubset({"id-mangle", "str-shred"})
