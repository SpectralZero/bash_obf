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

## Equivalence Contract

Tested across **8 fixtures × 5 seeds = 40/40** byte-for-byte equivalent observable behaviour. Stress-tested on a 87-assertion comprehensive bash fixture exercising every parameter expansion form, indirect references, associative arrays, extended globs, recursive functions, regex matching, base64 round-trips, and multi-stage eval chains.

| Fixture | Seeds | Status |
|---|---|---|
| `basic.sh` | 5/5 | ✅ |
| `comprehensive.sh` | 5/5 | ✅ |
| `full_syntax.sh` | 5/5 | ✅ |
| `functions.sh` | 5/5 | ✅ |
| `operational.sh` | 5/5 | ✅ |
| `pipelines.sh` | 5/5 | ✅ |
| `redteam_full.sh` | 5/5 | ✅ |
| `stress_indirection.sh` | 5/5 | ✅ |

Equivalence is byte-for-byte after normalising **inherent fixture non-determinism**: PIDs (`$$`, `BASHPID`), `date` timestamps, and bash error-message paths/line numbers. The obfuscator itself produces deterministic output for any given seed.

**Unit tests:** 39/39 passing.

---

## Quick Start

### Windows

```powershell
cd Bash\
python bootstrap.py          # Handles everything -- just run it
obfush input.sh output.sh
```

### Kali / Ubuntu / Debian

```bash
cd Bash/
python3 bootstrap.py         # Auto-detects PEP 668, creates venv if needed
source .venv/bin/activate    # Activate (if venv was created)
obfush input.sh output.sh
```

The bootstrap script is fully autonomous — **no flags, no arguments, no interaction required.** It runs 9 sequential phases (system fingerprint → Python check → pip → venv → deps → import chain → toolchain audit → tests → CLI smoke test).

> **On Kali/Debian 12+**, Python is "externally managed" (PEP 668). Bootstrap detects this and creates `.venv/` automatically.

---

## Architecture

```
                    +-------------+
                    | CLI (Click) |
                    +------+------+
                           |
                    +------v------+
                    |   Engine    |
                    +------+------+
                           |
              +------------+------------+
              |            |            |
       +------v------+ +---v--+ +------v------+
       |  AST Parser | | Seed | |   Emitter   |
       |  (bashlex)  | | sys. | |   (bash)    |
       +------+------+ +------+ +-------------+
              |
       +------v------+
       | Normalizer  |
       | (5 passes)  |
       +------+------+
              |
       +------v---------+
       | Layer Selector |
       | (compat DAG +  |
       |  topo sort)    |
       +------+---------+
              |
       +------v---------+
       | 9 Transform    |
       | Layers         |
       | (ordered chain)|
       +----------------+
```

### Transformation Layers

| # | Layer | Description |
|---|-------|-------------|
| 1 | `id-mangle` | Renames **defined** vars & functions only (free references and ALL_CAPS env vars are preserved). Hex/deceptive/mixed naming pools. |
| 2 | `str-shred` | Hex/octal/fragment/arithmetic-printf/base64 encoding of literal strings. Skips values containing `$`-expansions or shell syntax. |
| 3 | `cmd-sub` | `echo`<->`printf`, `true`<->`:`, `source`<->`.`, test-style morphing. |
| 4 | `junk-inject` | Dead code: assigned-never-read, noop chains, dead conditionals/functions, timing jitter. |
| 5 | `flow-obfusc` | Independent-block reordering (data-flow + stdout-ordering aware), opaque predicates, subshell wrapping. Skips `local`/`declare`/`export` to preserve scope. |
| 6 | `encode` | Wraps commands in eval/bash-c chains. Three modes: `ok`, `no-eval`, `direct-exec`. Uses base64 + bash-native printf hex (no `xxd` dependency). |
| 7 | `indirection` | Variable & associative-array command dispatch. Function pointer maps. |
| 8 | `poly-shell` | Multi-process self-extracting loader. *Gated to intensity >= 0.9.* |
| 9 | `entropy-mask` | Statistical decoy injection. 7 decoy types, sliding-window entropy targeting. **Runs LAST** so other layers don't corrupt decoys. |

### Layer Ordering Rules (DAG, enforced)

The compatibility matrix in `obfush/utils/compat_matrix.py` enforces the following ordering invariants (violating any of these breaks runtime semantics):

```
flow-obfusc -> junk-inject, indirection
id-mangle   -> encode, str-shred, cmd-sub      [LHS must be renamed before being hidden in encoded blobs]
flow-obfusc -> encode, str-shred, cmd-sub      [dependency analysis must see vars before they're hidden]
encode      -> entropy-mask
str-shred   -> entropy-mask                    [decoys must pass through unmodified]
cmd-sub     -> entropy-mask
id-mangle   -> entropy-mask
junk-inject -> entropy-mask
indirection -> entropy-mask
flow-obfusc -> entropy-mask
```

---

## Usage

### Basic

```bash
# Default obfuscation (intensity 0.8, eval allowed, 4+ layers)
obfush input.sh output.sh

# Verbose stats
obfush -v input.sh output.sh
```

### Eval Mode Control

```bash
# Maximum obfuscation -- eval chains allowed (default)
obfush --eval-mode ok input.sh output.sh

# Stealth mode -- zero eval tokens in output
obfush --eval-mode no-eval input.sh output.sh

# Direct exec -- launches bash subprocess per encoded block
obfush --eval-mode direct-exec input.sh output.sh
```

### Intensity & Layer Control

```bash
# Aggressive (all 9 layers, max randomisation)
obfush --intensity 1.0 input.sh output.sh

# Light touch
obfush --intensity 0.3 --min-layers 2 input.sh output.sh

# Force specific layers only
obfush --layers id-mangle,str-shred,encode --min-layers 1 input.sh output.sh

# Disable specific layers
obfush --no-layer poly-shell,entropy-mask input.sh output.sh
```

### Reproducibility & Seeding

```bash
# Deterministic output -- same seed = identical result every time
obfush --seed 1337 input.sh output.sh

# String seeds also work (xxhash internally)
obfush --seed "operation-nightfall" input.sh output.sh
```

### Entropy Management

```bash
# Target specific entropy (defeats ML scanners)
obfush --entropy-target 4.5 -v input.sh output.sh
```

### Verification & Debugging

```bash
# Equivalence check (requires bash; WSL/Git Bash on Windows)
obfush --verify input.sh output.sh

# Dry run -- preview without writing
obfush --dry-run -v input.sh output.sh

# Dump parsed AST for inspection
obfush --dump-ast ast_debug.json input.sh output.sh

# Full advanced help (eval modes, layer ordering, entropy, scope)
obfush --help-advanced
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
  --help-advanced                 Show full documentation and exit
  --version                       Show version and exit
  -h, --help                      Show help and exit
```

---

## Project Structure

```
Bash/
├── bootstrap.py                # Autonomous cross-platform setup (just run it)
├── pyproject.toml              # Package manifest & dependencies
├── README.md                   # This file
├── LICENSE                     # Proprietary -- internal use only
├── SESSION.md                  # Development session handoff doc
│
├── obfush/
│   ├── __init__.py             # Package metadata
│   ├── cli.py                  # Click CLI entry point
│   │
│   ├── engine/
│   │   ├── seed.py             # Entropy-based seed generation
│   │   ├── core.py             # PolymorphicEngine orchestrator
│   │   ├── layer_selector.py   # Auto-selection & DAG ordering
│   │   ├── ast_parser.py       # bashlex wrapper + opaque-blob fallback
│   │   ├── normalizer.py       # 5-pass AST canonicalisation
│   │   ├── ast_emitter.py      # AST -> valid bash (context-aware quoting)
│   │   ├── verifier.py         # Sandboxed equivalence tester
│   │   └── entropy_evaluator.py# Shannon entropy analysis
│   │
│   ├── layers/
│   │   ├── base.py             # Abstract Layer contract
│   │   ├── id_mangle.py        # Layer 1: Identifier mangling (defined-only)
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
│       ├── bash_keywords.py    # Reserved words & deceptive word pools
│       ├── compat_matrix.py    # Layer DAG + topological sort
│       ├── string_utils.py     # String encoding primitives
│       └── entropy_utils.py    # Shannon entropy computation
│
└── tests/
    ├── test_ast_parser.py
    ├── test_normalizer.py
    ├── test_emitter.py
    ├── test_equivalence.py
    ├── test_layers/
    │   └── test_all_layers.py
    ├── fixtures/               # 8 test scripts covering bash language
    │   ├── basic.sh
    │   ├── comprehensive.sh
    │   ├── full_syntax.sh
    │   ├── functions.sh
    │   ├── operational.sh
    │   ├── pipelines.sh
    │   ├── redteam_full.sh
    │   └── stress_indirection.sh
    └── entropy_corpus/         # Entropy baseline samples
        ├── log_rotate.sh
        ├── health_check.sh
        └── backup.sh
```

---

## Requirements

| Requirement | Minimum | Notes |
|-------------|---------|-------|
| Python | 3.11+ | Type hints, match statements |
| pip | any | Package installer |
| bashlex | 0.18+ | AST parsing (primary) |
| click | 8.1+ | CLI framework |
| rich | 13.0+ | Terminal formatting |
| xxhash | any | Seed hashing |
| PyYAML | any | Config (future) |
| bash | any | Only for `--verify` |

### Platform Matrix

| Feature | Windows 10/11 | Kali Linux | Ubuntu/Debian |
|---------|:---:|:---:|:---:|
| Core engine | Yes | Yes | Yes |
| CLI (`obfush`) | Yes | Yes | Yes |
| `--verify` (equivalence check) | WSL or Git Bash | Native bash | Native bash |
| `bootstrap.py` | Yes | Yes | Yes |
| Auto-venv (PEP 668) | Skipped | Auto-created | Auto-created |

> **Zero code changes between platforms.** Same codebase, same `bootstrap.py`, same `obfush` command works identically on Windows and Linux.

---

## Known Limitations

**bashlex parser coverage.** bashlex cannot parse all bash syntax: `[[ ... ]]` conditionals, `(( ... ))` arithmetic commands, complex parameter expansion (`${var//pat/replace}`), and nested heredocs may send the entire script (or affected regions) to the **opaque-blob fallback path**. Output remains correct and executes identically — but obfuscation depth is reduced for those regions because the AST-aware layers (id-mangle, flow-obfusc) work over text patterns instead of structured nodes.

**Verifier is a stub.** `--verify` exists in the CLI but the implementation is minimal. For now, run `bash original.sh > a.txt; bash obfuscated.sh > b.txt; diff a.txt b.txt` manually (and normalise PID/timestamp non-determinism with `sed`).

**Poly-shell layer is gated to intensity >= 0.9** and is the least-tested layer. Default intensity 0.8 keeps it disabled.

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
- Targeting any system without explicit written authorisation

See [LICENSE](LICENSE) for the full terms.

---

## Testing

```bash
# Full unit-test suite (39 tests)
pytest tests/ -v

# With coverage
pytest tests/ --cov=obfush --cov-report=term-missing

# Equivalence audit across all fixtures (run from repo root)
for fix in tests/fixtures/*.sh; do
  bash "$fix" > /tmp/orig.txt 2>&1
  ok=0
  for seed in 1 42 99 1337 7777; do
    obfush --seed "$seed" "$fix" /tmp/X.sh > /dev/null 2>&1
    bash /tmp/X.sh > /tmp/X.txt 2>&1
    norm() { sed -E 's|/[^:[:space:]]+\.sh: line [0-9]+:|<S>:|g; s|/tmp/[a-z_]+_[0-9]+|/tmp/X_N|g; s|\[20[0-9]{2}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}\]|[TS]|g' "$1"; }
    diff -q <(norm /tmp/orig.txt) <(norm /tmp/X.txt) > /dev/null && ((ok++))
  done
  printf "  %-30s %d/5\n" "$(basename "$fix")" "$ok"
done
```

---

## Recent Changes (v2.0.0-dev)

- **id-mangle:** only mangles names that are *defined* (assignments, function defs, declaration commands). Free references — including ALL_CAPS env vars and unbound `${!var}` literals — are preserved.
- **flow-obfusc:** dependency analysis now sees `local`/`declare`/`export` declarations; reorder barrier is conservative (only pure-assignment blocks reorder); compound-condition children are protected from wrapping via `_no_wrap` propagation.
- **encode:** removed `xor_base64` (required `python3` at runtime); `hex_printf` method replaces the old `xxd` method (bash-native, no external tool).
- **cmd-sub:** removed unsafe `cat <<<` morph (didn't round-trip through later layers).
- **emitter:** context-aware re-quoting that recognises `$'...'`, `$"..."`, `${...}`, `$(...)`, `[[ ]]`, `(( ))`, mixed-quote concatenations, and pre-rendered shell syntax. Auto-quotes `${var}` to prevent word-splitting.
- **parser:** correct extraction of bashlex assignment/function-def fields, reservedword/operator nodes, control-flow constructs (`if`/`while`/`until`/`for`/`case`/`select`), pipeline `|` filtering, redirect-output normalisation.
- **layer DAG:** 11 ordering rules enforced.

See [SESSION.md](SESSION.md) for the full change log and architectural rationale.

---

<div align="center">

**`obfush`** v2.0.0-dev — Spectral0x00 — Internal Use Only

</div>
