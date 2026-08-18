# Layer Development

## Current Extension Model

Layers are in-tree Python modules. The project does not currently discover third-party packages, Python entry points, or runtime plugin directories. Calling a layer a plugin means an internally reviewed module registered in `obfush.layers.LAYER_REGISTRY` and integrated with the static compatibility DAG.

Adding a layer therefore requires coordinated source changes outside documentation. Follow this guide in a branch where those implementation files are in scope.

## Contract

A module under `obfush/layers/` exports `LayerImpl`, a subclass of `obfush.layers.base.Layer`. It defines a unique canonical `name`, a short `description`, and `transform(ast, config) -> tuple[dict, LayerStats]`.

The transform receives the normalized dictionary AST and a frozen `LayerConfig` containing intensity, a layer-specific seed, a seeded `random.Random`, the eval mode, shared `NamePool`, source size, size budget, and entropy target. It may mutate the supplied AST, but must return a script-root dictionary and accurate statistics.

This is an internal Python API, not a stable public compatibility promise. Its current interface is:

```python
from obfush.layers.base import Layer, LayerConfig, LayerStats


class LayerImpl(Layer):
    name = "example-layer"
    description = "Apply one behavior-preserving AST transformation."

    def transform(
        self,
        ast: dict,
        config: LayerConfig,
    ) -> tuple[dict, LayerStats]:
        stats = LayerStats()
        # Traverse deterministically and use config.rng for every choice.
        return ast, stats
```

`Layer.validate(ast_before, ast_after)` defaults to checking the script root. Override it for layer-specific invariants. `Layer.estimate_size_increase(config)` is advisory and defaults to `1.0`; the engine still enforces its emitted byte budget. `LayerStats` supplies common counters and a `custom` mapping for compact diagnostics.

The engine creates one layer instance per application, gives it the normalized AST and `LayerConfig`, validates the returned tree, emits a size candidate, and either commits the transformed tree or restores its deep-copied predecessor. A layer must not retain AST, random generator, or configuration state for use by another run.

## Implementation Rules

- Preserve Bash behavior, exit status, quoting, variable scope, stream ordering, and side effects.
- Preserve the root and existing node shapes unless the emitter and all downstream consumers explicitly support a new shape. Dictionary AST details are internal and may change between reviewed releases.
- Use only `config.rng` for randomness. Never use module-global randomness, time, process IDs, hash randomization, or filesystem ordering.
- Allocate generated identifiers through `config.name_pool` when available.
- Treat opaque nodes conservatively. Do not parse or rewrite raw Bash with regular expressions unless the represented syntax and escaping rules are fully bounded.
- Keep synthetic AST markers explicit so size-budget trimming can remove only complete safe units.
- Implement `validate` when root-shape validation is insufficient. The engine deep-copies the AST and rolls back failed validation or over-budget output.
- Report work through `LayerStats`; place layer-specific diagnostic values in `stats.custom`.

## Registration And Ordering

1. Add the module path to `LAYER_REGISTRY` in `obfush/layers/__init__.py`.
2. Add the name to every relevant row in `MATRIX` and to `validate_layer_set`'s known set through the matrix.
3. Add only required before/after edges to `ORDERING_RULES`. The rules must remain acyclic.
4. Decide whether the layer is always selected or intensity-gated in `LayerSelector._auto_select`.
5. Update CLI layer help in the implementation and regenerate `docs/obfush.1` with `python scripts/generate_man.py`.

## Tests

Test deterministic output for a fixed seed, variation across different seeds where appropriate, no mutation after rollback, size-budget behavior, valid ordering with all interacting layers, and behavioral equivalence on focused Bash fixtures. Run at minimum:

```console
python -m pytest tests/test_layers tests/test_compat_matrix.py tests/test_equivalence.py
python scripts/generate_man.py
python -m pytest tests/test_man_generation.py
```

Use `bash -n` and equivalence fixtures for syntax-sensitive changes. Tests that execute scripts must use benign fixtures and a controlled environment.

## External Plugin Future

There is no external plugin API. Supporting one would require versioned AST and configuration contracts, package discovery, trust policy, dependency isolation, ordering declarations, failure semantics, and security review. None of that is configured today; do not distribute third-party layers as though compatibility or loading were supported.
