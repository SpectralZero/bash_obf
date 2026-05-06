<div align="center">

# `obfush` — Polymorphic Bash Obfuscation Engine

**v2.0.0-dev** &nbsp;|&nbsp; **Author:** Spectral0x00 &nbsp;|&nbsp; **Classification:** Internal — Red Team Tooling

<br>

*Every run produces unique output. No two invocations generate the same code, even from identical source.*

---

</div>

## Purpose

`obfush` transforms a valid bash script into a **functionally identical but statically unrecognisable** variant. The engine is designed for red team payload delivery where:

- **Source code must not be reversible** if a payload copy is captured by the blue team
- **Proprietary TTPs, infrastructure details, and capability indicators** must be stripped
- **Runtime behaviour should trigger EDR/AI detection** — that is the test objective

> **Out of scope:** No post-exploitation log wiping, history manipulation, or timestamp spoofing. This tool performs source-code obfuscation only. Runtime evasion is the operator's responsibility.

---

## Quick Start

### Windows

```powershell
cd obfush\
python bootstrap.py          # Handles everything — just run it
obfush input.sh output.sh
```

### Kali / Ubuntu / Debian

```bash
cd obfush/
python3 bootstrap.py         # Auto-detects PEP 668, creates venv if needed
source .venv/bin/activate    # Activate (if venv was created)
obfush input.sh output.sh
```

The bootstrap script is fully autonomous — **no flags, no arguments, no interaction required.** It runs 9 sequential phases:

```
 1. System fingerprint       Detect OS, distro, Python path, UID
 2. Python version gate      Enforce >= 3.11
 3. pip validation           Detect pip, show install commands if missing
 4. Virtual environment      Auto-create on PEP 668 systems (Kali/Debian 12+)
 5. Dependency installation  pip install -e .[dev] in editable mode
 6. Import chain             Verify all 12 modules load correctly
 7. External toolchain       Audit bash, git, base64, xxd, openssl, curl, jq
 8. Test suite               Run all 39 tests
 9. CLI smoke test           --version, --help, --help-advanced, --dry-run
```

> **On Kali/Debian 12+**, Python is "externally managed" (PEP 668). The bootstrap detects this
> automatically and creates a `.venv/` — no manual intervention needed.

---

## Architecture

```
                    ┌──────────────┐
                    │  CLI (Click) │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │   Engine     │
                    │  (core.py)   │
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
       ┌──────▼──────┐ ┌──▼───┐ ┌──────▼──────┐
       │  AST Parser  │ │ Seed │ │   Emitter   │
       │  (bashlex)   │ │System│ │   (bash)    │
       └──────┬───────┘ └──────┘ └─────────────┘
              │
       ┌──────▼──────┐
       │  Normalizer  │
       │  (5 passes)  │
       └──────┬───────┘
              │
    ┌─────────▼─────────┐
    │  Layer Selector    │
    │  (compat matrix +  │
    │   topo sort)       │
    └─────────┬──────────┘
              │
    ┌─────────▼─────────┐
    │   9 Transform      │
    │   Layers           │
    │   (ordered chain)  │
    └────────────────────┘
```

### Transformation Layers

| # | Layer | Description | Techniques |
|---|-------|-------------|------------|
| 1 | `id-mangle` | Variable & function name randomisation | Hex, deceptive, mixed naming pools |
| 2 | `str-shred` | String literal fragmentation | Hex/octal escapes, fragment concat, arithmetic printf, base64, variable reconstruction |
| 3 | `cmd-sub` | Syntax & command substitution | `echo`→`printf`, `source`↔`.`, `true`↔`:`, test style morphing |
| 4 | `junk-inject` | Dead code & timing jitter | 6 generators: assigned-never-read, noop chains, dead conditionals, dead functions, timing jitter, discarded subshells |
| 5 | `flow-obfusc` | Control flow restructuring | Block reordering (data-flow aware), opaque predicates, subshell wrapping, function extraction |
| 6 | `encode` | Encoding (base64, xor, hex) | 3 eval modes: `ok` (eval chains), `no-eval` (printf reassembly), `direct-exec` (bash -c subprocess) |
| 7 | `indirection` | Indirect dispatch & pointer chains | Variable command dispatch, eval chain indirection, function pointer maps |
| 8 | `poly-shell` | Multi-process self-extracting loader | Payload splitting, multi-method chunk encoding, bootstrap loader generation *(gated: intensity ≥ 0.9)* |
| 9 | `entropy-mask` | Statistical decoy injection | 7 decoy types, Shannon entropy targeting, sliding window analysis |

---

## Usage

### Basic

```bash
# Default obfuscation (intensity 0.8, eval allowed, 4+ layers)
obfush input.sh output.sh

# See what happened
obfush -v input.sh output.sh
```

### Eval Mode Control

```bash
# Maximum obfuscation — eval chains allowed (default)
obfush --eval-mode ok input.sh output.sh

# Stealth mode — zero eval tokens in output
obfush --eval-mode no-eval input.sh output.sh

# Direct exec — launches bash subprocess per encoded block
obfush --eval-mode direct-exec input.sh output.sh
```

### Intensity & Layer Control

```bash
# Aggressive (all 9 layers, max randomisation)
obfush --intensity 1.0 input.sh output.sh

# Light touch (fewer transforms, smaller output)
obfush --intensity 0.3 --min-layers 2 input.sh output.sh

# Force specific layers only
obfush --layers id-mangle,str-shred,encode --min-layers 1 input.sh output.sh

# Disable specific layers
obfush --no-layer poly-shell,entropy-mask input.sh output.sh
```

### Reproducibility & Seeding

```bash
# Deterministic output — same seed = identical result every time
obfush --seed 1337 input.sh output.sh

# String seeds also work (hashed internally)
obfush --seed "operation-nightfall" input.sh output.sh
```

### Entropy Management

```bash
# Target specific entropy (defeats ML scanners)
obfush --entropy-target 4.5 -v input.sh output.sh

# Verbose mode shows full entropy analysis with per-window breakdown
obfush -v input.sh output.sh
```

### Verification & Debugging

```bash
# Run equivalence check (requires bash — WSL/Git Bash on Windows)
obfush --verify input.sh output.sh

# Provide test input for verification
obfush --verify --test-input test_data.txt input.sh output.sh

# Dry run — preview without writing
obfush --dry-run -v input.sh output.sh

# Dump parsed AST for inspection
obfush --dump-ast ast_debug.json input.sh output.sh
```

---

## CLI Reference

```
Usage: obfush [OPTIONS] INPUT_SCRIPT OUTPUT_SCRIPT

Options:
  --seed TEXT                     Deterministic seed (reproducible output)
  --intensity FLOAT               0.0-1.0 obfuscation aggressiveness [0.8]
  --layers TEXT                   Comma-separated layers to force
  --no-layer TEXT                 Comma-separated layers to disable
  --min-layers INTEGER            Minimum active layers [4]
  --eval-mode [ok|no-eval|direct-exec]
                                  How to handle code evaluation [ok]
  --entropy-target FLOAT          Target Shannon entropy (bit/byte) [4.5]
  --verify                        Run equivalence check in sandbox
  --test-input PATH               Stdin for verification scripts
  -v, --verbose                   Show per-layer statistics
  --dry-run                       Preview only, don't write file
  --dump-ast PATH                 Dump parsed AST to file (debug)
  --help-advanced                 Full Spectral0x00 documentation
  --version                       Show version and exit
  -h, --help                      Show help and exit
```

---

## Project Structure

```
obfush/
├── bootstrap.py                # Autonomous cross-platform setup (just run it)
├── pyproject.toml              # Package manifest & dependencies
├── README.md                   # This file
│
├── obfush/
│   ├── __init__.py             # Package metadata
│   ├── cli.py                  # Click CLI entry point
│   │
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── seed.py             # Entropy-based seed generation
│   │   ├── core.py             # PolymorphicEngine orchestrator
│   │   ├── layer_selector.py   # Auto-selection & compatibility ordering
│   │   ├── ast_parser.py       # bashlex wrapper + fallback parser
│   │   ├── normalizer.py       # 5-pass AST canonicalisation
│   │   ├── ast_emitter.py      # AST → valid bash emitter
│   │   ├── verifier.py         # Sandboxed equivalence tester
│   │   └── entropy_evaluator.py# Shannon entropy analysis
│   │
│   ├── layers/
│   │   ├── __init__.py         # Layer registry
│   │   ├── base.py             # Abstract Layer contract
│   │   ├── id_mangle.py        # Layer 1: Identifier mangling
│   │   ├── str_shred.py        # Layer 2: String shredding
│   │   ├── cmd_sub.py          # Layer 3: Command substitution
│   │   ├── junk_inject.py      # Layer 4: Dead code injection
│   │   ├── flow_obfusc.py      # Layer 5: Control flow obfuscation
│   │   ├── encode.py           # Layer 6: Encoding (eval-mode aware)
│   │   ├── indirection.py      # Layer 7: Dynamic dispatch
│   │   ├── poly_shell.py       # Layer 8: Self-extracting loader
│   │   └── entropy_mask.py     # Layer 9: Entropy camouflage
│   │
│   └── utils/
│       ├── __init__.py
│       ├── bash_keywords.py    # Reserved words & deceptive word pools
│       ├── compat_matrix.py    # Layer compatibility + topological sort
│       ├── string_utils.py     # String encoding primitives
│       └── entropy_utils.py    # Shannon entropy computation
│
└── tests/
    ├── __init__.py
    ├── test_ast_parser.py      # Parser unit tests
    ├── test_normalizer.py      # Normalizer unit tests
    ├── test_emitter.py         # Emitter round-trip tests
    ├── test_equivalence.py     # End-to-end pipeline tests
    ├── test_layers/
    │   └── test_all_layers.py  # Individual layer tests
    ├── fixtures/               # Synthetic test scripts
    │   ├── basic.sh
    │   ├── functions.sh
    │   ├── pipelines.sh
    │   └── operational.sh
    └── entropy_corpus/         # Entropy baseline samples
        ├── log_rotate.sh
        ├── health_check.sh
        └── backup.sh
```

---

## Requirements

| Requirement | Minimum | Windows | Kali / Debian | Notes |
|-------------|---------|---------|---------------|-------|
| Python | 3.11+ | `python.org` installer | `sudo apt install python3` | Type hints, match statements |
| pip | any | Bundled with Python | `sudo apt install python3-pip` | Package installer |
| bashlex | 0.18+ | `pip install` | `pip3 install` | AST parsing |
| click | 8.1+ | `pip install` | `pip3 install` | CLI framework |
| rich | 13.0+ | `pip install` | `pip3 install` | Terminal formatting |
| xxhash | any | `pip install` | `pip3 install` | Seed hashing |
| PyYAML | any | `pip install` | `pip3 install` | Config (future) |
| bash | any | WSL / Git Bash | Native `/bin/bash` | Only for `--verify` |

### Platform Matrix

| Feature | Windows 10/11 | Kali Linux | Ubuntu/Debian |
|---------|:---:|:---:|:---:|
| Core engine | Yes | Yes | Yes |
| CLI (`obfush`) | Yes | Yes | Yes |
| `--verify` (equivalence check) | WSL or Git Bash | Native bash | Native bash |
| `bootstrap.py` | Yes | Yes | Yes |
| Auto-venv (PEP 668) | Skipped (not needed) | Auto-created | Auto-created |

> **Zero code changes needed between platforms.** The same codebase, same `bootstrap.py`, same
> `obfush` command works identically on Windows and Linux.

---

## Security & Ethics

This tool is scoped exclusively to **static source code obfuscation** for authorised internal red team operations.

**In scope:**
- Source code transformation to prevent reverse engineering of captured payloads
- Stripping TTPs, infrastructure markers, and capability indicators
- Testing EDR/AI detection of obfuscated payloads

**Firmly out of scope:**
- Runtime evasion, anti-debugging, or anti-analysis
- Post-exploitation log wiping, history manipulation, or timestamp spoofing
- Distribution outside authorised internal teams

---

## Testing

```bash
# Full test suite
pytest tests/ -v

# With coverage
pytest tests/ --cov=obfush --cov-report=term-missing

# Specific test module
pytest tests/test_equivalence.py -v
```

**Current status:** 39/39 tests passing

---

<div align="center">

**`obfush`** v2.0.0-dev — Spectral0x00 — Internal Use Only

</div>
