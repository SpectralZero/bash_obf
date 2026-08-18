# Architecture

## Scope

`obfush` is a Python 3.11+ command-line application that transforms Bash source into Bash source or, when a suitable Linux C compiler is available, a Linux loader binary. It is proprietary internal red-team tooling. It is not a virtual machine and has no bytecode runtime.

## Request Flow

1. `obfush.cli:main` parses Click arguments and combines command-line values with discovered or explicit YAML configuration.
2. `PolymorphicEngine` chooses or derives a seed and strips source comments while preserving Bash constructs that contain `#` data.
3. `ast_parser` uses `bashlex` and protected opaque regions for syntax that cannot be represented safely.
4. `normalizer` canonicalizes the internal dictionary AST and annotates references used by later transforms.
5. `LayerSelector` chooses layers, derives a separate deterministic seed for each, and topologically orders them with `compat_matrix`.
6. Each layer receives a deep-copy-backed transaction boundary. Structural validation or size-budget failure rolls the layer back.
7. `ast_emitter` emits Bash source. Optional equivalence verification executes the original and generated scripts in controlled subprocesses and compares behavior.
8. Script mode writes the result atomically. Binary mode encrypts the transformed source, emits a C loader, and invokes an available Linux compiler; the resulting program ultimately executes `/bin/bash`.

## Components

| Component | Responsibility |
| --- | --- |
| `obfush.cli` | User interface, configuration precedence, batch and benchmark dispatch, output handling |
| `obfush.engine` | Parsing, normalization, selection, orchestration, emission, analysis, verification |
| `obfush.layers` | Registered AST transformations using the `Layer` contract |
| `obfush.utils` | Compatibility ordering, deterministic names, string reconstruction, entropy helpers |
| `obfush.compiler` | Optional Linux C loader generation and compilation |
| `obfush.batch` | Recursive `.sh` processing and worker coordination |

## Data And Trust Boundaries

Input scripts, configuration files, test input, output paths, environment keys, and compiler executables cross into the process from the operator environment. Obfuscated output remains executable code with the original script's authority. The tool does not sandbox transformation itself. Equivalence verification launches Bash and therefore must only receive trusted or explicitly authorized scripts in an isolated test environment.

Dependencies and C compilers are supply-chain boundaries. Internal release artifacts should be built from a reviewed commit, verified by checksum, and retained in the authorized artifact store. The repository workflows only upload GitHub Actions run artifacts and do not publish externally.

## Determinism

The engine derives per-layer random generators from the master seed. Layers must use the supplied `LayerConfig.rng`, shared `NamePool`, and deterministic traversal order. A fixed seed is necessary but does not promise identical output across arbitrary dependency or implementation versions; release reproducibility should pin the reviewed source and build environment.

## Deliberate Exclusions

Runtime behavior remains observable to host monitoring. The project does not provide a bytecode format, opcode set, interpreter, string pool, junk bytecode, or VM execution model. Those items, including any multi-process VM design, are deferred in `FUTURE_WORK.md`.
