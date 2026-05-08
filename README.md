<div align="center">

# `obfush`
### Polymorphic Bash Obfuscation Engine

![Version](https://img.shields.io/badge/version-2.0.0--dev-blue?style=flat-square)
![Status](https://img.shields.io/badge/status-internal-red?style=flat-square)
![Tests](https://img.shields.io/badge/tests-52%2F52%20passing-brightgreen?style=flat-square)
![Classification](https://img.shields.io/badge/classification-Red%20Team%20Tooling-orange?style=flat-square)

**Author:** Spectral0x00 &nbsp;·&nbsp; **Classification:** Internal — Red Team Tooling

---

*Every run produces unique output. No two invocations generate the same code, even from identical source.*

</div>

---

## Overview

`obfush` transforms a valid bash script into a **functionally identical but statically unrecognisable** variant. Designed for red team payload delivery where:

- **Source code must not be reversible** if a payload is captured by the blue team
- **Proprietary TTPs, infrastructure markers, and capability indicators** must be stripped
- **Runtime behaviour should trigger EDR/AI detection** — that is the test objective, not something we fight

> **Out of scope:** No log wiping, history manipulation, timestamp spoofing, or runtime evasion. This tool performs source-code obfuscation only. System calls (`connect`, `execve`, `write`) remain fully visible to strace/eBPF/EDR.

---

## CI Status

| Gate | Result |
|:-----|:------:|
| Unit tests (`pytest tests/`) | **52 / 52** ✅ |
| Native fixture assertions (10 fixtures, sum across counters) | **234 / 234 PASS, 0 FAIL** ✅ |
| Equivalence (10 fixtures × 5 seeds, raw `diff -q`) | **50 / 50** ✅ |
| CI script (`ci/equivalence_check.py`) | **10 / 10 PASS** across seeds 1, 42, 7777 ✅ |
| OPSEC: original comments leaked into output | **0** ✅ |
| Decoy corpus pairwise overlap (100 seeds × 50 comments) | **< 10 %** ✅ |

---

## Quick Start

### Windows

```powershell
cd bash_obf\
python bootstrap.py          # Autonomous installer -- just run it
obfush input.sh output.sh
```

### Kali / Ubuntu / Debian

```bash
cd bash_obf/
python3 bootstrap.py         # Auto-detects PEP 668, creates venv if needed
source .venv/bin/activate    # Activate (if venv was created)
obfush input.sh output.sh
```

> The bootstrap is fully autonomous — no flags, no arguments, no interaction. It runs **9 sequential phases**: system fingerprint → Python check → pip → venv → deps → import chain → toolchain audit → tests → CLI smoke test.
>
> **On Kali/Debian 12+** Python is "externally managed" (PEP 668). Bootstrap detects this and creates `.venv/` automatically.

---

## Architecture

```
   input.sh
       │
       ▼
┌─────────────┐
│  Comment-   │  Pre-processing pass: strips ALL source comments
│  Strip Pass │  deterministically (shebang + quoted-# preserved).
└──────┬──────┘  Runs BEFORE bashlex so the parser path doesn't
       │         affect privacy guarantees.
       ▼
┌─────────────┐
│  AST Parser │  bashlex + opaque-blob fallback for unsupported
│  (bashlex)  │  syntax ([[ ]], complex param expansion, nested
└──────┬──────┘  heredocs).
       │
       ▼
┌─────────────┐
│  Normalizer │  5 passes: variable refs, expansion canonical
│  (5 passes) │  forms, scope tracking, var_refs annotations.
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   Layer     │  Compatibility-DAG enforcement + topological sort.
│  Selector   │  11 ordering rules.
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   9 Layers  │  Each layer transforms the AST. Layers are
│  (chained)  │  selectable; the DAG decides their order.
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   Emitter   │  AST → valid bash source. Context-aware
│             │  re-quoting (bashlex strips quotes; we restore
└──────┬──────┘  them based on word context).
       │
       ▼
   output.sh
```

### Transformation Layers

| # | Layer | What it does |
|:-:|:------|:-------------|
| 1 | `id-mangle` | Renames **defined** vars & functions only. Free references, ALL_CAPS env vars, builtins, and PATH-affecting commands are preserved. Hex/deceptive/mixed naming pools. |
| 2 | `str-shred` | Hex/octal/fragment/arithmetic-printf/base64 encoding of literal strings. Skips values containing `$`-expansions or shell syntax. |
| 3 | `cmd-sub` | `echo`↔`printf`, `true`↔`:`, `source`↔`.`, test-style morphing. |
| 4 | `junk-inject` | Dead code: assigned-never-read, noop chains, dead conditionals/functions, timing jitter. |
| 5 | `flow-obfusc` | Independent-block reordering (data-flow + stdout-ordering aware), opaque predicates, subshell wrapping. **Skips `local`/`declare`/`export`** so scope-binding commands stay in the parent shell. Compound-condition children are protected from individual wrapping. |
| 6 | `encode` | Wraps commands in `eval`/`bash -c`/`exec` chains. Three modes: `ok`, `no-eval`, `direct-exec`. Uses base64 + bash-native `printf` hex (no `xxd` dependency). |
| 7 | `indirection` | Variable & associative-array command dispatch. Function pointer maps. |
| 8 | `poly-shell` | Multi-process self-extracting loader. *Gated to intensity ≥ 0.9.* |
| 9 | `entropy-mask` | Procedural decoy injection from a **31,680-combo corpus** (40 actions × 36 components × 22 contexts). **Runs LAST**, and decoys are injected BEFORE the tail statement so the script's exit code is preserved. |

### Layer Ordering Rules (DAG)

Defined in `obfush/utils/compat_matrix.py`:

```
flow-obfusc → junk-inject, indirection
id-mangle   → encode, str-shred, cmd-sub        # LHS rename before encoding hides it
flow-obfusc → encode, str-shred, cmd-sub        # dependency analysis must see vars
encode, str-shred, cmd-sub, id-mangle,
junk-inject, indirection, flow-obfusc → entropy-mask    # decoys must pass through
```

---

## OPSEC: Comments & Decoys

A pre-processing pass strips **all** source comments before bashlex parses — deterministic regardless of which parser path the script takes. Shebangs and quoted `#` characters are preserved.

`entropy-mask` then injects misleading decoy comments drawn from a procedural corpus:

| Component | Generator | Combinations |
|:----------|:----------|:------------:|
| Comment block (`: "..."`) | `{action} {component} {context}` | 40 × 36 × 22 = **31,680** |
| Inline `# TODO/FIXME/NOTE/...` | 24 prefixes × 24 descriptions + 10 metadata | **586** |
| Log-style `[LEVEL] subj action` | 5 levels × 13 subjects × 12 actions | **780** |

No two obfuscated artifacts share the same decoy comment set. Clustering analysis is defeated by construction — verified: 100 seeds × 50 comments, max pairwise overlap < 10%.

---

## Usage

### Basic

```bash
obfush input.sh output.sh                 # Default: intensity 0.8, eval ok
obfush -v input.sh output.sh              # Verbose stats per layer
```

### Eval Mode

```bash
obfush --eval-mode ok input.sh out.sh           # Default -- max obfuscation
obfush --eval-mode no-eval input.sh out.sh      # Zero eval tokens
obfush --eval-mode direct-exec input.sh out.sh  # Bash subprocess per encoded block
```

### Intensity & Layers

```bash
obfush --intensity 1.0 input.sh out.sh                          # Aggressive
obfush --intensity 0.3 --min-layers 2 input.sh out.sh           # Light touch
obfush --layers id-mangle,str-shred,encode --min-layers 1 in.sh out.sh
obfush --no-layer poly-shell,entropy-mask input.sh out.sh
```

### Reproducibility

```bash
obfush --seed 1337 input.sh out.sh                     # Deterministic
obfush --seed "operation-nightfall" input.sh out.sh    # String seed (xxhash)
```

### Debugging

```bash
obfush --dry-run -v input.sh out.sh           # Preview without writing
obfush --dump-ast ast.json input.sh out.sh    # Inspect parsed AST
obfush --help-advanced                        # Full doc panel
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

> Run `obfush --help-advanced` for the full operational guide — eval-mode tradeoffs, layer ordering rationale, OPSEC corpus design, entropy targeting, equivalence contract, and scope reminder.

---

## Options & Tuning Guide

### `--intensity FLOAT` *(default: `0.8`)*

Controls how aggressive the obfuscation is.

| Intensity | Effect |
|:---------:|:-------|
| `0.3–0.5` | Light obfuscation. Renames identifiers, shreds some strings, adds a few decoys. Output stays close to the original size. Good for quick tests. |
| `0.6–0.8` | Recommended production level. All core layers active. Strong identifier mangling, string fragmentation, dead code, control-flow changes, and optional encoding. Output is 3–5× larger but still fast. |
| `0.9–1.0` | Maximum obfuscation. Adds poly-shell (multi-chunk self-extracting loader) and heavier flow-obfusc. Can increase size 10–15×. Note: `--eval-mode no-eval` at `1.0` may expose a printf escape bug (strings may break). Use `--eval-mode ok` at `1.0` for best results. |

> **Rule of thumb:** Start at `0.8`. If you need absolute maximum protection, use `--intensity 1.0 --eval-mode ok` and avoid `no-eval` for now.

---

### `--eval-mode` *(default: `ok`)*

How the tool wraps encoded/indirected commands. This directly affects whether `eval` appears in the final script.

| Mode | Behaviour | Use when… |
|:-----|:----------|:----------|
| `ok` | Uses eval chains for maximum disguise. Produces the most complex output. | Target environment does not grep for `eval`. |
| `no-eval` | Zero eval tokens. Reconstructs commands via `bash -c`, `source`, or `printf` chains. No eval signature. | `eval` is monitored or forbidden. Currently unstable at intensity `1.0` due to a printf escape bug. Works well at intensity ≤ `0.9`. |
| `direct-exec` | Replaces `eval` with `exec bash -c …`. Parent script exits cleanly. | You need no eval and can accept a second process. |

> **Recommendation:** For maximum stealth, use `--eval-mode no-eval` with intensity ≤ `0.9`. If you need full power, use `--eval-mode ok` with intensity `1.0`.

---

### `--layers` / `--no-layer` / `--min-layers`

Override which obfuscation layers run.

- `--layers id-mangle,encode` — only those layers run (overrides auto-selection). Useful for debugging or targeting specific protections.
- `--no-layer poly-shell` — disable a single layer. Handy if you want max intensity without the buggy poly-shell.
- `--min-layers 6` — force at least 6 layers to run (engine picks them randomly).

Default layer set at intensity `0.8`: all layers except `poly-shell` (which activates only at ≥ `0.9`).

---

### `--seed TEXT` *(default: random)*

A seed makes the output deterministic and reproducible.

- Same seed + same source = byte-for-byte identical obfuscated script on any machine.
- Without `--seed`, the output is different every run (true polymorphism).

> **Tip:** If a particular seed produces a perfect result, record it. You can re-use it for reproducible deployments or debugging.

---

### `--entropy-target FLOAT` *(default: `4.5`)*

Controls the statistical randomness of the final script.

- Normal bash scripts have entropy around `4.2–4.8` bit/byte.
- Encoded blobs push entropy above `5.8`, which ML classifiers flag.
- The engine adds realistic decoy code to bring the global entropy down to the target.

Default `4.5` works well. Lower it if you need the script to look even more "normal" (but output size will grow).

---

### `--verify` / `--test-input`

Run a built-in equivalence check after obfuscation.

- `--verify` executes both scripts and compares stdout, stderr, and exit codes.
- `--test-input FILE` feeds that file as stdin to both scripts during verification.
- Useful for CI or final confidence checks before deployment.

> **Note:** The verifier currently runs via subprocess. A full sandboxed version is planned for v2.1.

---

### `--verbose` / `--dry-run`

- `-v, --verbose` — prints per-layer statistics, entropy analysis, and final size.
- `--dry-run` — shows what would be done without writing the output file.

---

### `--dump-ast PATH`

Writes the parsed Abstract Syntax Tree to a JSON file. Useful for debugging or understanding how the parser sees your script.

---

### Quick-Start Examples

```bash
# Simple, reliable obfuscation (recommended)
obfush payload.sh payload_obf.sh

# Maximum obfuscation, avoid buggy layers
obfush payload.sh payload_max.sh --intensity 1.0 --eval-mode ok --no-layer poly-shell

# Zero eval tokens, moderate intensity
obfush payload.sh payload_clean.sh --eval-mode no-eval --intensity 0.8

# Reproducible artifact for team sharing
obfush payload.sh payload_shared.sh --seed 1337 --intensity 0.9
```

---

## Continuous Integration

`.github/workflows/ci.yml` runs **three jobs** on every push:

1. **`unit-tests`** — `pytest tests/` (52 tests). Fast gate.
2. **`fixture-assertions`** — every fixture script is executed natively in bash. Any non-zero exit fails the gate. Catches fixture-side bugs before they consume CI runner-minutes.
3. **`equivalence`** — light matrix on push (3 SHA-derived seeds × default × default), full matrix nightly (5 seeds × 3 intensities × 3 eval-modes = 45 jobs).

### SHA-Derived Seed Rotation

Light-matrix seeds are picked deterministically from a 12-seed pool using `commit_sha[:8]`, `[8:16]`, `[16:24]`. Same commit always picks the same 3 seeds (reproducible debugging); different commits pick different sets (drift across the seed space — no permanent blind spots).

### Failure Artifacts

On any equivalence mismatch, the workflow writes `ci_output/<fixture>_s<seed>_diff.txt` and `<fixture>_s<seed>_result.json` containing:

- `equivalent`
- `diff_preview`
- `exit_codes`
- `durations_ms`
- `normalization_classes_applied`

Artifacts are uploaded with **30-day retention** for triage.

### Quarantine Mechanism

Fixtures with known-but-tracked failures are listed in the `QUARANTINE` set in `ci/equivalence_check.py`. Quarantined failures are reported but do not block CI. Used as a safety valve for environment-dependent edge cases; currently empty.

### Local Equivalence Check

```bash
python ci/equivalence_check.py --seed 42 --intensity 0.8 --eval-mode ok
```

Same script the CI runs. Exit `0` when all non-quarantined fixtures pass.

---

## Testing

```bash
# Unit tests (52)
pytest tests/ -v

# Coverage
pytest tests/ --cov=obfush --cov-report=term-missing

# Equivalence (same script CI runs)
python ci/equivalence_check.py --seed 42 --intensity 0.8 --eval-mode ok

# Manual audit across all fixtures × multiple seeds
for fix in tests/fixtures/*.sh; do
  bash "$fix" > /tmp/orig.txt 2>&1
  ok=0
  for seed in 1 42 99 1337 7777; do
    obfush --seed "$seed" "$fix" /tmp/X.sh > /dev/null 2>&1
    bash /tmp/X.sh > /tmp/X.txt 2>&1
    diff -q /tmp/orig.txt /tmp/X.txt > /dev/null && ((ok++))
  done
  printf "  %-30s %d/5\n" "$(basename "$fix")" "$ok"
done
```

---

## Project Structure

```
Bash/
├── .github/workflows/ci.yml        # CI pipeline
├── bootstrap.py                    # Autonomous cross-platform installer
├── pyproject.toml                  # Package manifest
├── README.md                       # This file
├── LICENSE                         # Proprietary -- internal use only
│
├── ci/
│   ├── __init__.py
│   └── equivalence_check.py        # CI equivalence runner (also for local use)
│
├── obfush/
│   ├── __init__.py
│   ├── cli.py                      # Click CLI entry point
│   │
│   ├── engine/
│   │   ├── seed.py                 # Entropy-based seed generation
│   │   ├── core.py                 # PolymorphicEngine orchestrator
│   │   ├── layer_selector.py       # Auto-selection & DAG ordering
│   │   ├── ast_parser.py           # bashlex wrapper + opaque-blob fallback
│   │   ├── normalizer.py           # 5-pass AST canonicalisation
│   │   ├── ast_emitter.py          # AST -> bash (context-aware quoting)
│   │   ├── normalize.py            # Output normalization (single source)
│   │   ├── verifier.py             # Sandboxed equivalence tester
│   │   ├── comment_strip.py        # Pre-processing comment removal pass
│   │   └── entropy_evaluator.py    # Shannon entropy analysis
│   │
│   ├── layers/
│   │   ├── base.py                 # Abstract Layer contract
│   │   ├── id_mangle.py            # Layer 1
│   │   ├── str_shred.py            # Layer 2
│   │   ├── cmd_sub.py              # Layer 3
│   │   ├── junk_inject.py          # Layer 4
│   │   ├── flow_obfusc.py          # Layer 5
│   │   ├── encode.py               # Layer 6
│   │   ├── indirection.py          # Layer 7
│   │   ├── poly_shell.py           # Layer 8 (intensity >= 0.9)
│   │   └── entropy_mask.py         # Layer 9 (tail-preserving decoy injection)
│   │
│   └── utils/
│       ├── bash_keywords.py        # Reserved words, builtins, deceptive pools
│       ├── compat_matrix.py        # Layer DAG + topological sort
│       ├── decoy_corpus.py         # 31,680-combo procedural corpus
│       ├── string_utils.py         # Encoding primitives
│       └── entropy_utils.py        # Shannon entropy computation
│
└── tests/
    ├── test_ast_parser.py
    ├── test_normalizer.py
    ├── test_emitter.py
    ├── test_equivalence.py
    ├── test_corpus_and_normalizer.py       # Decoy corpus + normalizer tests
    ├── test_layers/
    │   └── test_all_layers.py
    ├── fixtures/                           # 10 bash test scripts
    │   ├── basic.sh
    │   ├── comprehensive.sh
    │   ├── full_syntax.sh
    │   ├── functions.sh
    │   ├── operational.sh
    │   ├── pipelines.sh
    │   ├── real_payload_smoke.sh           # Real-world operational patterns
    │   ├── redteam_full.sh
    │   ├── stress_indirection.sh
    │   └── ultimate_stress_test.sh         # Gold-standard: 25 sections, 107 assertions
    └── entropy_corpus/                     # Entropy baseline samples
```

---

## Requirements

| Component | Minimum | Notes |
|:----------|:-------:|:------|
| Python | 3.11+ | Type hints, `match` statements |
| pip | any | Package installer |
| bashlex | 0.18+ | AST parsing (primary) |
| click | 8.1+ | CLI framework |
| rich | 13.0+ | Terminal formatting |
| xxhash | any | Seed hashing |
| PyYAML | any | Config (future) |
| bash | any | Only for `--verify` and CI equivalence |

### Platform Matrix

| Feature | Windows 10/11 | Kali Linux | Ubuntu/Debian |
|:--------|:-------------:|:----------:|:-------------:|
| Core engine | ✅ | ✅ | ✅ |
| CLI (`obfush`) | ✅ | ✅ | ✅ |
| `--verify` (equivalence check) | WSL or Git Bash | Native bash | Native bash |
| `bootstrap.py` | ✅ | ✅ | ✅ |
| Auto-venv (PEP 668) | Skipped | Auto-created | Auto-created |
| GitHub Actions runner | n/a | n/a | `ubuntu-latest` |

> **Zero code changes between platforms.** Same codebase, same `bootstrap.py`, same `obfush` command works identically on Windows and Linux.

---

## Known Limitations

> **bashlex parser coverage.** Cannot parse `[[ ... ]]` conditionals, `(( ... ))` arithmetic commands, complex parameter expansion (`${var//pat/replace}`), or nested heredocs. Affected scripts (or affected regions within otherwise-parseable scripts) are routed to the **opaque-blob fallback path**. Output remains correct and executes identically — but obfuscation depth is reduced for those regions because AST-aware layers (`id-mangle`, `flow-obfusc`) work over text patterns instead of structured nodes.

> **`--verify` is minimal.** The CLI flag exists but the implementation is a thin wrapper. For full equivalence checking, prefer `python ci/equivalence_check.py` which uses the same normalization module and produces structured JSON.

> **Poly-shell layer is gated to intensity ≥ 0.9** and is the least-tested layer. Default intensity `0.8` keeps it disabled.

**Additional known issues:**

- `--eval-mode no-eval` at intensity `1.0` may produce broken printf escapes (strings become garbled). Fix in progress.
- `poly-shell` layer (intensity ≥ `0.9`) can miss newlines between chunks, causing syntax errors. Disable with `--no-layer poly-shell` until patched.
- Arithmetic inside double-quoted strings (e.g., `echo "Sum: $((2+3))"`) may occasionally split across two lines. The value is still correct.
- Indirect variable references (`${!name}`) where the name itself is stored as a literal string may not be renamed in opaque-blob mode.

---

## Security & Ethics

This tool is scoped exclusively to **static source code obfuscation** for authorised internal red team operations.

** In scope:**
- Source code transformation to prevent reverse engineering of captured payloads
- Stripping TTPs, infrastructure markers, and capability indicators
- Testing EDR/AI detection of obfuscated payloads

** Firmly out of scope:**
- Runtime evasion, anti-debugging, anti-analysis
- Post-exploitation log wiping, history manipulation, timestamp spoofing
- Distribution outside authorised internal teams
- Targeting any system without explicit written authorisation

See [LICENSE](LICENSE) for full terms.

---

<div align="center">

**`obfush`** v2.0.0-dev &nbsp;·&nbsp; Spectral0x00 &nbsp;·&nbsp; Internal Use Only

</div>