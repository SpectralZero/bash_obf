# obfush

`obfush` is a proprietary internal Bash transformation and analysis tool for authorized testing. It preserves script behavior while changing the static representation, and includes equivalence verification, batch processing, benchmarking, a local GUI, and optional Linux binary-loader packaging.

## Current Status

- Version: `2.0.0-dev`
- Tests: `1049 passed, 1 skipped` (adds an adversarial differential corpus + faithfulness regressions)
- Coverage: `97.02%` combined statement and branch coverage
- Lint: Ruff clean for `obfush`, `tests`, `scripts`, and `ci`
- Distribution: internal source, wheel, sdist, and manually generated artifacts only
- VM program: explicitly deferred in [FUTURE_WORK.md](FUTURE_WORK.md)

## Install

```bash
python -m pip install -e .
```

For the local dashboard:

```bash
python -m pip install -e ".[gui]"
```

The core engine needs Python 3.11+, Bashlex, Click, Rich, xxhash, and PyYAML. Bash is required for equivalence verification and fixture execution. Binary output requires a Linux-compatible C compiler or WSL.

## Quick Start

```bash
obfush input.sh output.sh
obfush --seed 42 --eval-mode no-eval input.sh output.sh
obfush --batch scripts/ build/ --workers 4
obfush --benchmark input.sh --json-output
```

The command also supports `python -m obfush`.

## Operating Modes

### Script

The default mode parses and normalizes Bash, applies the selected compatibility-ordered layers, emits Bash, and optionally verifies equivalence.

```bash
obfush --verify --test-input stdin.txt input.sh output.sh
obfush --layers id-mangle,str-shred,encode --min-layers 1 input.sh output.sh
obfush --no-layer poly-shell,entropy-mask input.sh output.sh
```

### Binary

Binary mode encrypts the generated Bash payload into a Linux C loader. It is not a cross-platform executable and invokes `/bin/bash` on the target system.

```bash
obfush --output-mode binary input.sh loader
obfush --output-mode binary --checksum input.sh loader
obfush --output-mode binary --env-key deployment-name input.sh loader
```

`--checksum` writes `loader.sha256` for external artifact verification. It is not a self-integrity boundary. Anti-debug checks are enabled by default in the existing Linux loader and can be disabled with `--no-anti-debug` for compatibility testing.

### GUI

```bash
obfush --gui
obfush --gui --no-browser --gui-host 127.0.0.1 --gui-port 5050
```

The Flask dashboard provides source/output editors, presets, layer selection, entropy and security analysis, and a JSON batch queue. It is intended for local authorized use and has no external authentication layer.

### Setup and Plugins

```bash
obfush --setup
obfush --plugin ./trusted_layer.py input.sh output.sh
```

`--setup` creates a validated `~/.obfushrc`. Plugins are explicit and trusted: a plugin must expose `LayerImpl`, executes in-process, and is never auto-discovered from a home directory.

## Layers

The current registry contains 12 layers:

- `id-mangle`
- `str-shred`
- `cmd-sub`
- `junk-inject`
- `flow-obfusc`
- `opaque-const`
- `cff`
- `encode`
- `indirection`
- `poly-shell`
- `entropy-mask`
- `anti-trace`

The compatibility DAG enforces ordering constraints. `entropy-mask` preserves the script tail so injected decoys do not alter the final status, and `anti-trace` injects an anti-analysis preamble and is ordered last. Unsupported Bash regions use an opaque fallback path and receive less AST-aware transformation.

## GUI API

The local dashboard exposes:

- `GET /api/presets`
- `POST /api/obfuscate`
- `POST /api/analyze`
- `POST /api/batch`

Requests are JSON-limited to 1 MiB, source-limited to 1 MiB, and validated with structured error responses.

## Verification

```bash
python -m pytest --cov=obfush --cov-report=term-missing --cov-fail-under=97
python -m ruff check obfush tests scripts ci
python scripts/generate_man.py
python -m build
python ci/equivalence_check.py --seed 42 --intensity 0.8 --eval-mode ok
```

The checked-in CI workflow enforces tests, a 97% coverage gate, Ruff, anti-regression fixtures, native fixture assertions, and an equivalence matrix.

## Documentation

- [Installation](docs/installation.md)
- [Architecture](docs/architecture.md)
- [Layer development](docs/layer-development.md)
- [Threat model](docs/threat-model.md)
- [Security policy](SECURITY.md)
- [Contribution guidance](CONTRIBUTING.md)
- [Release process](docs/release-process.md)
- [Command manual](docs/obfush.1)
- [Deferred VM work](FUTURE_WORK.md)

## Security and Authorization

This tool is proprietary internal software. Use it only against systems and scripts for which explicit authorization exists. It transforms source representation; it does not make runtime activity invisible to system monitoring. The verifier executes shell subprocesses and must be treated as code execution, not as a sandbox. Plugins execute arbitrary trusted Python in the current process.

Runtime evasion, evidence destruction, log wiping, history manipulation, timestamp spoofing, unauthorized targeting, and distribution outside the authorized internal environment are out of scope. VM bytecode, VM interpreter/runtime, VM string pools, junk bytecode, opcode polymorphism, and multi-process VM execution are deferred in [FUTURE_WORK.md](FUTURE_WORK.md).

See [LICENSE](LICENSE) for the governing terms.
