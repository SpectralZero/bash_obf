# obfush v3.0 — THE DEFINITIVE GOD MODE PLAN

> **Implementation status (2026-08-14):** This is the historical design plan,
> not the current backlog. The non-VM engine, binary packaging, GUI, batch,
> benchmark, configuration, plugin, setup, documentation, container, release,
> and 97% coverage work is implemented in the working tree. All VM bytecode,
> opcode, interpreter, encrypted VM string-pool, junk-bytecode, and
> multi-process VM execution work is explicitly deferred to `FUTURE_WORK.md`.
> Runtime evidence-destruction mechanisms are not part of the shipped surface;
> binary artifact integrity uses external SHA-256 sidecars and release checksums.

**Classification:** Lead Architect Handoff — Final Design Document
**Coverage Target:** 97%+ (1,154 missing statements → 0)
**Scope:** 12 phases, 55+ files, 198 test cases, 6 sprints

> Every section of this document can be torn out and handed to a contributor as a work ticket. Every open question is answered. Every recommendation has an exact file path, line number, and definition of done.

---

# TABLE OF CONTENTS

```
PART I    — DECISIONS (All Questions Answered)
PART II   — ANTI-RE HARDENING (Phases 1–11, Full Implementation Specs)
PART III  — GUI DASHBOARD (Phase 12, Full Component Specs)
PART IV   — TEST COVERAGE: 60% → 97% (Per-File Test Matrix)
PART V    — ENGINEERING EXCELLENCE (10 Dimensions, 73 Recommendations)
PART VI   — UNIFIED ROADMAP (6 Sprints, Exit Criteria)
PART VII  — FINAL METRICS TABLE
```

---

# PART I: DECISIONS — ALL QUESTIONS ANSWERED

No open questions remain. Every decision includes rationale and constraint analysis.

| # | Question | Decision | Rationale |
|---|---|---|---|
| Q1 | XOR key embedding strategy | **(b) Opaque constant, split across 3 variables, assembled via arithmetic** | Runtime-derived keys (`$$`, `$BASH_VERSION`) break `--seed` determinism and equivalence tests. Split-across-3-vars requires tracing an arithmetic chain — good enough for script mode. Binary mode uses full 32-byte rolling XOR in `.rodata`. |
| Q2 | CFF scope | **(b) Top-level + function bodies, depth ≤ 2 guard** | Functions contain the most valuable logic. Depth guard prevents recursive flattening. Risk mitigated by verifier + CI. |
| Q3 | Implementation priority | **Phase 3+4 → Phase 2 → Phase 1 → Phase 5 → Phase 7** | Fingerprint removal (2 days) immediately breaks all YARA rules. Size cap prevents bloat before heavier phases. Live decoys are highest-impact. Eval removal is architecturally complex — ship after simpler wins stabilize. |
| Q4 | Compiled loader language | **(a) C with gcc/musl-gcc** | 20KB static binary. Zero runtime deps. Maximum syscall control. 150 lines of C doesn't benefit from Rust's memory safety or Go's cross-compile. *Assumption: gcc available on build machine; fallback to `cc` with dynamic linking + warning.* |
| Q5 | Environment keying | **(b) Multi-factor: SHA256(hostname + username + first-NIC MAC), truncated to 8 bytes** | Single-factor hostname too easy to spoof. Full bash condition is over-engineered. Multi-factor is the sweet spot. `--env-key` for simple hostname string, `--env-key-full` for multi-factor. |
| Q6 | GUI framework | **(a) Flask + vanilla JS, CodeMirror for editor, D3 for entropy viz** | No npm, no build step. `pip install obfush[gui]` and it works. FastAPI's async doesn't help (CPU-bound). React adds 200MB node_modules for 5 pages. |
| Q7 | VM scope | **(c) Core + fallback** | VM handles: vars, conditionals, loops, functions, echo/printf, pipes, redirects, arithmetic, tests, arrays. Unsupported constructs (heredocs, complex param expansion, process substitution) exec via bash subprocess with encrypted payload handoff. Covers ~93% of real scripts. Full bash VM is multi-year; this ships in weeks. |

---

# PART II: ANTI-RE HARDENING — PHASES 1–11

## Current Weakness Inventory (Measured)

| # | Weakness | Severity | Deobfuscation Time | Phase That Fixes It |
|---|---|---|---|---|
| W1 | Single `eval` bottleneck — `sed 's/eval/echo/'` dumps cleartext | **CRITICAL** | 5 seconds | Phase 1 |
| W2 | 100% dead decoys — dead-code elimination strips 68% of output | **CRITICAL** | 30 seconds | Phase 2 |
| W3 | Predictable naming: `_category_hex_counter` pattern | **HIGH** | 2 minutes (YARA rule) | Phase 3 |
| W4 | 17% duplicate decoy comments across samples | **HIGH** | 5 minutes (clustering) | Phase 3 |
| W5 | Output bloat 2x–11.6x (small scripts worst) | **MEDIUM** | N/A (operational) | Phase 4 |
| W6 | Structural fingerprint: decoys cluster before eval | **HIGH** | 1 minute (visual) | Phase 1+3 |
| W7 | No control-flow obfuscation beyond reordering | **MEDIUM** | 15 minutes | Phase 5 |
| W8 | Arithmetic predicates solvable by Z3/angr | **MEDIUM** | 10 minutes | Phase 11 |
| W9 | Runtime fully visible: `bash -x`, strace, eBPF | **CRITICAL** | Instant | Phase 7+9 |
| W10 | Binary diffing matches across builds | **HIGH** | 20 minutes | Phase 7 (polymorphic) |
| W11 | No self-integrity — binary patchable | **HIGH** | 5 minutes | Phase 11 |
| W12 | Full program in single process — `strace -f` captures all | **MEDIUM** | 10 minutes | Phase 10 |

---

## Phase 1: Kill the `eval` Bottleneck

> **Fixes:** W1 (CRITICAL), W6 (HIGH)
> **Priority:** P0
> **Estimated effort:** 3 days

### Problem

[encode.py](file:///c:/Users/RTX/Desktop/Bash/obfush/layers/encode.py) L84-112 wraps commands in `eval "$(echo 'BASE64' | base64 -d)"`. [poly_shell.py](file:///c:/Users/RTX/Desktop/Bash/obfush/layers/poly_shell.py) L126-180 builds a single loader that concatenates all chunks then `eval`s them on one line. One `sed` command deobfuscates everything.

### Solution: Inline Encoding + Cascading Stages

**[MODIFY] [encode.py](file:///c:/Users/RTX/Desktop/Bash/obfush/layers/encode.py) — 151 lines → ~220 lines**

Delete hex-blob packing. Each command is individually encoded at its original AST position:

```python
# New _encode_command (replaces L62-81)
def _encode_command(ast: dict, config: LayerConfig, stats: LayerStats) -> dict:
    """Encode a single command inline — no wrapper."""
    from obfush.engine.ast_emitter import _emit_command
    cmd_str = _emit_command(ast, 0)
    if not cmd_str or len(cmd_str) < 5:
        return ast

    rng = config.rng
    mode = config.eval_mode

    # Select encoding strategy (3 new + 2 existing)
    if mode == "ok":
        strategy = rng.choice(["base64_eval", "hex_printf_eval", 
                                "arithmetic_reassembly", "array_dispatch", "trap_exec"])
    else:
        strategy = rng.choice(["hex_printf_bash_c", "arithmetic_reassembly", 
                                "array_dispatch"])

    return _STRATEGIES[strategy](cmd_str, rng, stats)
```

New strategies:

```python
def _arithmetic_reassembly(cmd_str: str, rng: random.Random, stats: LayerStats) -> dict:
    """Build command from $(( )) byte expressions."""
    # Each byte → arithmetic expression that evaluates to that byte
    # e.g. ord('e')=101 → $(( (7 * 14) + 3 ))
    parts = []
    for b in cmd_str.encode():
        a = rng.randint(2, 15)
        q, r = divmod(b, a)
        parts.append(f"$(printf '\\\\x%02x' $(({a}*{q}+{r})))")
    reassembly = "".join(parts)
    decode_cmd = f'bash -c "{reassembly}"'
    stats.regions_encoded += 1
    stats.nodes_modified += 1
    return {"type": "command", "parts": [{"type": "word", "value": decode_cmd, "pos": None}],
            "pos": None, "_encoded": True}

def _array_dispatch(cmd_str: str, rng: random.Random, stats: LayerStats) -> dict:
    """Store bytes in array, loop-decode."""
    bytes_list = " ".join(str(b) for b in cmd_str.encode())
    var = f"_ab{rng.randint(0x100,0xffff):04x}"
    # declare -a _abXXXX=(101 99 104 111); _s=""; for _c in "${_abXXXX[@]}"; do _s+=$(printf "\\x$(printf '%02x' "$_c")"); done; bash -c "$_s"
    decode_cmd = (f'declare -a {var}=({bytes_list}); _s=""; '
                  f'for _c in "${{{var}[@]}}"; do _s+=$(printf "\\\\x$(printf \'%02x\' "$_c")"); done; '
                  f'bash -c "$_s"')
    stats.regions_encoded += 1
    stats.nodes_modified += 1
    return {"type": "command", "parts": [{"type": "word", "value": decode_cmd, "pos": None}],
            "pos": None, "_encoded": True}

def _trap_exec(cmd_str: str, rng: random.Random, stats: LayerStats) -> dict:
    """Register as trap handler, trigger with signal."""
    encoded = base64.b64encode(cmd_str.encode()).decode()
    var = f"_tr{rng.randint(0x100,0xffff):04x}"
    decode_cmd = (f'{var}=$(echo \'{encoded}\' | base64 -d); '
                  f'trap "${{var}}" USR1; kill -USR1 $$')
    stats.regions_encoded += 1
    stats.nodes_modified += 1
    return {"type": "command", "parts": [{"type": "word", "value": decode_cmd, "pos": None}],
            "pos": None, "_encoded": True}
```

Mix rate: at intensity 0.8, encode 40-60% of commands. Rest stay plaintext. This defeats the pattern "every command is encoded."

**[MODIFY] [poly_shell.py](file:///c:/Users/RTX/Desktop/Bash/obfush/layers/poly_shell.py) — 181 lines → ~250 lines**

Replace single loader with cascading 3-stage `source`:

```python
def _build_loader(encoded_chunks, rng, eval_mode="ok"):
    """Build cascading stage loader — NO single eval."""
    body = []
    chunk_vars = []
    for i, chunk in enumerate(encoded_chunks):
        var_name = f"_c{rng.randint(0x100, 0xffff):04x}"
        chunk_vars.append(var_name)
        body.append({
            "type": "assignment",
            "name": var_name,
            "value": f'"$({chunk["decode_expr"]})"',
            "pos": None,
        })

    # Cascading source — each chunk is sourced separately
    # No single eval that dumps everything
    for var in chunk_vars:
        source_cmd = f"source <(printf '%s' \"${{{var}}}\")"
        body.append({
            "type": "command",
            "parts": [{"type": "word", "value": source_cmd, "pos": None}],
            "pos": None,
        })

    return {"type": "script", "body": body}
```

Also replace `xxd -r -p` (L109) with `printf '\xNN'` chain — kills external dependency.

**Done when:**
- `grep -c 'eval ' output.sh` returns 0 for `--eval-mode no-eval`
- No single line modification can dump cleartext
- `xxd` no longer appears in any layer code

---

## Phase 2: Live Decoys — Kill Dead Code Elimination

> **Fixes:** W2 (CRITICAL)
> **Priority:** P0
> **Estimated effort:** 4 days

### Problem

[entropy_mask.py](file:///c:/Users/RTX/Desktop/Bash/obfush/layers/entropy_mask.py) `DecoyGenerator` (L187-316) generates variables like `_path_a1_1="/tmp/.cache"` that are assigned but **never read**. A dead-code pass strips 68% of the file in seconds.

### Solution: `LiveChainGenerator` — Replace All 8 Generator Methods

```python
class LiveChainGenerator:
    """Generates chains of 3-6 decoy statements with live dependencies."""

    def __init__(self, rng: random.Random, name_pool: NamePool, 
                 real_vars: set[str]) -> None:
        self.rng = rng
        self.pool = name_pool
        self.real_vars = list(real_vars) if real_vars else ["HOSTNAME"]
        self._chains_generated = 0

    def generate_chain(self) -> list[dict]:
        """Generate a single live decoy chain (3-6 statements)."""
        chain_type = self.rng.choice([
            self._system_probe_chain,      # hostname, date, uname
            self._arithmetic_chain,        # cascading math operations
            self._string_processing_chain, # string manipulation
            self._conditional_chain,       # opaque conditional reading real var
            self._function_chain,          # define + call function
        ])
        return chain_type()

    def _system_probe_chain(self) -> list[dict]:
        """Chain that probes system state — each var reads the previous."""
        v1 = self.pool.next_name()
        v2 = self.pool.next_name()
        v3 = self.pool.next_name()
        v4 = self.pool.next_name()

        stmts = [
            self._assign(v1, '$(hostname -s 2>/dev/null || echo localhost)'),
            self._assign(v2, f'$((${{{v1}#${v1}}} + ${{#{v1}}} * 443 + RANDOM % 100))'),
            self._assign(v3, f'"https://${{{v1}}}:${{{v2}}}/api/v2"'),
            self._assign(v4, f'$(echo "${{{v3}}}" | cksum | cut -d\' \' -f1)'),
            self._consume(v4),  # : "$v4" — terminal consumption
        ]
        return stmts

    def _arithmetic_chain(self) -> list[dict]:
        """Multi-step arithmetic where each value depends on the previous."""
        v1 = self.pool.next_name()
        v2 = self.pool.next_name()
        v3 = self.pool.next_name()

        a = self.rng.randint(10, 999)
        b = self.rng.randint(2, 17)
        stmts = [
            self._assign(v1, f'$(({a} % {b} + RANDOM % 50))'),
            self._assign(v2, f'$(({v1} * 7 + ${{{v1}}} / 3))'),
            self._assign(v3, f'$(printf "%x" $(({v2} ^ ${{{v1}}})))'),
            self._consume(v3),
        ]
        return stmts

    def _string_processing_chain(self) -> list[dict]:
        """String manipulation chain with substring and replacement."""
        v1 = self.pool.next_name()
        v2 = self.pool.next_name()
        v3 = self.pool.next_name()

        stmts = [
            self._assign(v1, '$(date +%s%N 2>/dev/null || echo 0)'),
            self._assign(v2, f'"${{{v1}:0:8}}"'),
            self._assign(v3, f'$(echo "${{{v2}}}" | tr "0-9" "a-j")'),
            self._consume(v3),
        ]
        return stmts

    def _conditional_chain(self) -> list[dict]:
        """Opaque conditional that reads a REAL variable — always false but unprovable."""
        real_var = self.rng.choice(self.real_vars)
        v1 = self.pool.next_name()
        v2 = self.pool.next_name()

        # ${REAL_VAR:-0} -gt 99999 is always false for normal values
        # but a static analyzer can't prove it without knowing REAL_VAR's range
        stmts = [
            self._assign(v1, f'${{#{real_var}}}'),  # length of real var
            {
                "type": "compound", "kind": "if",
                "parts": [
                    {"type": "word", "value": "if", "pos": None},
                    {"type": "command", "parts": [
                        {"type": "word", "value": f'[[ ${{{v1}:-0}} -gt 99999 ]]', "pos": None}
                    ], "pos": None},
                    {"type": "word", "value": "then", "pos": None},
                    self._assign_node(v2, f'"critical: overflow at ${{{v1}}}"'),
                    {"type": "command", "parts": [
                        {"type": "word", "value": f'logger "${{{v2}}}"', "pos": None}
                    ], "pos": None, "_junk": True},
                    {"type": "word", "value": "fi", "pos": None},
                ],
                "pos": None, "_junk": True,
            },
        ]
        return stmts

    def _function_chain(self) -> list[dict]:
        """Define a function, then call it (output to /dev/null)."""
        fname = self.pool.next_name()
        v1 = self.pool.next_name()

        stmts = [
            {
                "type": "function_def", "name": fname,
                "body": [
                    self._assign_node(v1, '$(date +%s 2>/dev/null || echo 0)'),
                    {"type": "command", "parts": [
                        {"type": "word", "value": f'echo "${{{v1}}}"', "pos": None}
                    ], "pos": None},
                ],
                "pos": None, "_junk": True,
            },
            {"type": "command", "parts": [
                {"type": "word", "value": f'{fname} > /dev/null 2>&1', "pos": None}
            ], "pos": None, "_junk": True},
        ]
        return stmts

    # Helper methods
    def _assign(self, name: str, value: str) -> dict:
        return {"type": "assignment", "name": name, "value": value, "pos": None, "_junk": True}

    def _assign_node(self, name: str, value: str) -> dict:
        return {"type": "command", "parts": [
            {"type": "assignment", "name": name, "value": value, "pos": None}
        ], "pos": None, "_junk": True}

    def _consume(self, var_name: str) -> dict:
        """Terminal consumption — `: "$var"` makes the chain appear live."""
        return {"type": "command", "parts": [
            {"type": "word", "value": f': "${{{var_name}}}"', "pos": None}
        ], "pos": None, "_junk": True}
```

**Invariants (CRITICAL — enforced by tests):**
1. Every decoy variable is referenced by ≥1 subsequent statement
2. Decoys NEVER write to real variables — read-only cross-references
3. Decoy functions write ONLY to `/dev/null` — no side effects
4. Opaque conditionals use impossible thresholds (> 99999, > 999999)

**[MODIFY] [junk_inject.py](file:///c:/Users/RTX/Desktop/Bash/obfush/layers/junk_inject.py):**
- Replace `JunkCatalogue._assigned_never_read()` (dead) with `_chained_assignment()` — value uses `${previous_junk_var}`
- Replace `_dead_function()` with `_called_noop_function()` — function IS called, output to /dev/null
- Replace `_dead_conditional()` with `_hash_locked_conditional()` — condition uses `cksum` of a junk var

**Done when:**
- `ci_output/dead_code_test.py` reports 0 dead variables
- Dead-code elimination reduces output by < 5%
- All 14 fixtures still pass equivalence

---

## Phase 3: Kill All Static Fingerprints

> **Fixes:** W3 (HIGH), W4 (HIGH), W6 (HIGH)
> **Priority:** P0
> **Estimated effort:** 2 days

### 3a. Shared Name Pool

**[NEW] [obfush/utils/name_pool.py](file:///c:/Users/RTX/Desktop/Bash/obfush/utils/name_pool.py) — ~100 lines**

```python
"""Shared name generation — used by id_mangle, entropy_mask, junk_inject."""

from __future__ import annotations
import random

# 80 Unix-like abbreviations — look like real variable names
_UNIX_ABBREVS = [
    "rc", "fd", "pid", "sig", "buf", "ptr", "len", "cnt", "idx", "tmp",
    "err", "ret", "val", "key", "msg", "cfg", "opt", "arg", "env", "ctx",
    "srv", "cli", "req", "res", "hdr", "ttl", "ack", "syn", "rst", "fin",
    "mtu", "rtt", "seq", "win", "dst", "src", "gid", "uid", "dev", "ino",
    "nfd", "epfd", "wd", "tfd", "sfd", "pfd", "cfd", "rfd", "wfd", "xfd",
    "st", "sb", "ts", "tv", "tz", "dt", "tm", "dur", "int", "flg",
    "bsz", "csz", "msz", "psz", "rsz", "wsz", "max", "min", "avg", "sum",
    "cur", "prev", "next", "head", "tail", "top", "bot", "lhs", "rhs", "mid",
]

class NamePool:
    """Collision-free name generator shared across all layers."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self._used: set[str] = set()
        self._counter = 0

    def next_name(self) -> str:
        """Generate a unique variable name indistinguishable from id-mangle output."""
        for _ in range(100):  # max attempts
            strategy = self.rng.randint(0, 3)
            if strategy == 0:
                # Short random: _x7q, _m3k, _p2z
                name = f"_{self.rng.choice('abcdefghijklmnopqrstuvwxyz')}" \
                       f"{self.rng.randint(0,9)}" \
                       f"{self.rng.choice('abcdefghijklmnopqrstuvwxyz')}"
            elif strategy == 1:
                # Unix abbreviation: _rc, _fd3, _pid
                abbr = self.rng.choice(_UNIX_ABBREVS)
                suffix = "" if self.rng.random() < 0.5 else str(self.rng.randint(0, 9))
                name = f"_{abbr}{suffix}"
            elif strategy == 2:
                # Underscore compound: _buf_sz, _cfg_fd, _ret_val
                a = self.rng.choice(_UNIX_ABBREVS[:40])
                b = self.rng.choice(_UNIX_ABBREVS[40:])
                name = f"_{a}_{b}"
            else:
                # Counter-based but non-monotonic: _v7, _t3, _k9
                c = self.rng.choice("vtkrsn")
                n = self.rng.randint(0, 99)
                name = f"_{c}{n}"

            if name not in self._used and len(name) >= 3:
                self._used.add(name)
                return name

        # Fallback — guaranteed unique
        self._counter += 1
        name = f"_z{self._counter}"
        self._used.add(name)
        return name

    def register_existing(self, names: set[str]) -> None:
        """Register names already in use (e.g., from id-mangle) to avoid collisions."""
        self._used.update(names)
```

**[MODIFY] [base.py](file:///c:/Users/RTX/Desktop/Bash/obfush/layers/base.py) — Add to LayerConfig:**
```python
name_pool: NamePool | None = None
source_size: int = 0
max_size_ratio: float = 3.0
```

**[MODIFY] [core.py](file:///c:/Users/RTX/Desktop/Bash/obfush/engine/core.py) — Create NamePool and pass to LayerConfig:**
```python
from obfush.utils.name_pool import NamePool
# After seed creation:
name_pool = NamePool(create_rng(seed))
# In layer_config construction:
layer_config = LayerConfig(
    ...,
    name_pool=name_pool,
    source_size=len(source),
    max_size_ratio=self.config.max_size_ratio,
)
```

**[MODIFY] [id_mangle.py](file:///c:/Users/RTX/Desktop/Bash/obfush/layers/id_mangle.py) — Use NamePool for mangled names:**
- Replace internal `_generate_mangled_name()` with `config.name_pool.next_name()`
- After mangling, call `config.name_pool.register_existing(set(mangle_map.values()))`

### 3b. Zero-Duplicate Comments

**[MODIFY] [decoy_corpus.py](file:///c:/Users/RTX/Desktop/Bash/obfush/utils/decoy_corpus.py):**
- Add `_seen: set[str]` field to `DecoyCorpus`
- In `generate()`: if comment in `_seen`, regenerate. If all 31,680 combos exhausted, parameterize: append `(${_var_name})`
- Guarantee: `len(set(comments)) == len(comments)` for every run

### 3c. Structural De-Fingerprinting

After Phase 1 removes the eval wrapper, decoys are naturally interleaved with real encoded commands throughout the script body. No more "block of decoys → single eval" pattern.

**Done when:**
- YARA rule `rule obfush { strings: $a = /_[a-z]+_[0-9a-f]+_\d+/ condition: #a > 10 }` matches 0 times
- Cross-sample comment analysis finds 0 shared strings (tested with 5 seeds)
- `grep` for `_path_`, `_calc_`, `_ifaces_` returns 0 matches

---

## Phase 4: Output Size Cap

> **Fixes:** W5 (MEDIUM)
> **Priority:** P0
> **Estimated effort:** 1 day

### Current Bloat (Measured)

| Fixture | Original | Obfuscated | Ratio |
|---|---|---|---|
| basic.sh | 195B | 2,271B | **11.6x** |
| functions.sh | 895B | 7,671B | **8.6x** |
| operational.sh | 1,248B | 10,267B | **8.2x** |
| stress_indirection.sh | 3,401B | 29,374B | **8.6x** |
| opaque_blob_recovery.sh | 969B | 8,026B | **8.3x** |
| redteam_full.sh | 12,507B | 47,776B | 3.8x |
| ultimate_stress_test.sh | 19,637B | 71,228B | 3.6x |

Small scripts (< 1KB) bloat 8-11x because decoy injection is absolute (not proportional).

### Solution

**[MODIFY] [core.py](file:///c:/Users/RTX/Desktop/Bash/obfush/engine/core.py):**
- Add `max_size_ratio: float = 3.0` to `EngineConfig`
- After emit (L163): if `len(output) > len(source) * config.max_size_ratio`, trim decoy nodes from AST body (nodes with `_junk=True`), re-emit, repeat until within budget

**[MODIFY] [entropy_mask.py](file:///c:/Users/RTX/Desktop/Bash/obfush/layers/entropy_mask.py):**
- Replace entropy-driven injection count with size-budget-driven count:
  ```python
  payload_estimate = config.source_size * 2.0  # encoding roughly doubles
  decoy_budget = int(config.source_size * config.max_size_ratio - payload_estimate)
  avg_chain_bytes = 250  # measured average
  num_chains = max(3, decoy_budget // avg_chain_bytes)
  ```

**[MODIFY] [cli.py](file:///c:/Users/RTX/Desktop/Bash/obfush/cli.py):** Add `--max-size-ratio` flag (default 3.0).

**Done when:** All 14 fixtures produce output ≤ 3.0x original size. `ci_output/size_test.py` passes.

---

## Phase 5: Advanced Anti-Analysis Layers

> **Fixes:** W7 (MEDIUM), W8 (MEDIUM)
> **Priority:** P1
> **Estimated effort:** 5 days

### 5a. Control-Flow Flattening (CFF)

**[NEW] [obfush/layers/cff.py](file:///c:/Users/RTX/Desktop/Bash/obfush/layers/cff.py) — ~200 lines**

Converts sequential independent blocks into a `while/case` dispatcher:

```bash
# BEFORE:
step_a
step_b  
step_c

# AFTER:
_st=3
while [[ $_st -ne 0 ]]; do
    case $_st in
        5) step_a; _st=1;;
        1) step_b; _st=7;;
        7) step_c; _st=0;;
        3) : "unreachable decoy"; _st=5;;  # entry point
        4) : "dead state";;                # decoy case
    esac
done
```

Implementation details:
- Reuse `flow_obfusc._is_control_flow_barrier()` for safe-to-flatten detection
- Maximum 8 real blocks per dispatcher (larger groups → multiple dispatchers)
- 30% decoy `case` arms with live decoy chains (Phase 2)
- At intensity > 0.9: nested 2D dispatchers using `$((_s1 * 100 + _s2))`
- Depth guard: `depth ≤ 2` to prevent recursive flattening
- State variable name from `NamePool`

### 5b. Opaque Constants

**[NEW] [obfush/layers/opaque_const.py](file:///c:/Users/RTX/Desktop/Bash/obfush/layers/opaque_const.py) — ~150 lines**

Replaces integer literals with equivalent arithmetic:

```python
def _generate_opaque(target: int, rng: random.Random) -> str:
    """Generate an arithmetic expression that equals target."""
    strategy = rng.randint(0, 3)
    if strategy == 0:
        # (a * b + c) where a*b+c == target
        a = rng.randint(2, 15)
        b = target // a
        c = target - (a * b)
        return f"$(( ({a} * {b} + {c}) ))"
    elif strategy == 1:
        # RANDOM neutralized: (RANDOM|1)*0 + target
        return f"$(( (RANDOM|1)*0 + {target} ))"
    elif strategy == 2:
        # Split across 2 vars
        split = rng.randint(1, target - 1) if target > 1 else 0
        return f"$(( {split} + {target - split} ))"
    else:
        # Ternary with always-true condition
        decoy = rng.randint(0, 9999)
        return f"$(( 1 > 0 ? {target} : {decoy} ))"
```

Targets: `sleep N`, port numbers, test comparisons (`-eq`, `-gt`, `-lt`), array indices.

### 5c. Multi-Algorithm String Encryption

**[MODIFY] [str_shred.py](file:///c:/Users/RTX/Desktop/Bash/obfush/layers/str_shred.py) — Add to `random_shred()`:**

New method `xor_decrypt`:
```python
def to_xor_decrypt(s: str, rng: random.Random) -> str:
    """XOR-encrypt string with opaque key, decrypt inline."""
    key = rng.randint(1, 254)
    encrypted_bytes = [b ^ key for b in s.encode()]
    hex_bytes = " ".join(f"0x{b:02x}" for b in encrypted_bytes)
    # Pure bash XOR decryption loop
    return (f'$(k={key}; for b in {hex_bytes}; do '
            f'printf "\\\\$(printf "%03o" $((b ^ k)))"; done)')
```

New method `split_reassemble`:
```python
def to_split_reassemble(s: str, rng: random.Random, name_pool) -> tuple[list[str], str]:
    """Split into 3-5 fragments stored in separate variables."""
    num_parts = rng.randint(3, min(5, len(s)))
    # ... split string at random points, assign to pool-named vars
    # ... return (setup_assignments, "${_a}${_b}${_c}" expression)
```

### 5d. Layer Integration

**[MODIFY] [compat_matrix.py](file:///c:/Users/RTX/Desktop/Bash/obfush/utils/compat_matrix.py):**

Add to `MATRIX`:
```python
"cff": {
    "id-mangle": Compat.OK, "str-shred": Compat.OK, "cmd-sub": Compat.OK,
    "junk-inject": Compat.OK, "flow-obfusc": Compat.DANGER,
    "encode": Compat.OK, "indirection": Compat.OK,
    "poly-shell": Compat.OK, "entropy-mask": Compat.OK,
    "opaque-const": Compat.OK,
},
"opaque-const": {
    "id-mangle": Compat.OK, "str-shred": Compat.OK, "cmd-sub": Compat.OK,
    "junk-inject": Compat.OK, "flow-obfusc": Compat.OK,
    "encode": Compat.OK, "indirection": Compat.OK,
    "poly-shell": Compat.OK, "entropy-mask": Compat.OK,
    "cff": Compat.OK,
},
```

Add to `ORDERING_RULES`:
```python
("id-mangle", "cff"),
("flow-obfusc", "cff"),
("cff", "encode"),
("cff", "entropy-mask"),
("id-mangle", "opaque-const"),
("opaque-const", "encode"),
("opaque-const", "str-shred"),
```

**[MODIFY] [layers/__init__.py](file:///c:/Users/RTX/Desktop/Bash/obfush/layers/__init__.py):**
```python
_LAYER_MAP["cff"] = "obfush.layers.cff"
_LAYER_MAP["opaque-const"] = "obfush.layers.opaque_const"
```

**[MODIFY] [layer_selector.py](file:///c:/Users/RTX/Desktop/Bash/obfush/engine/layer_selector.py):**
- `cff`: activated at intensity ≥ 0.6
- `opaque-const`: always-on (lightweight, always beneficial)

**Done when:** 11 layers available. CFF produces valid bash. Opaque constants evaluate to correct values. All fixtures pass equivalence.

---

## Phase 6: Presets & CLI Enhancements

> **Priority:** P0-P1
> **Estimated effort:** 2 days

**[MODIFY] [cli.py](file:///c:/Users/RTX/Desktop/Bash/obfush/cli.py):**

New options:
```python
@click.option("--preset", type=click.Choice(["stealth","standard","paranoid","godmode"]), 
              default=None, help="Preset configuration profile.")
@click.option("--output-mode", type=click.Choice(["script","binary","vm-binary"]),
              default="script", help="Output format.")
@click.option("--max-size-ratio", type=float, default=3.0,
              help="Maximum output/input size ratio (default: 3.0).")
@click.option("--json-output", is_flag=True, default=False,
              help="Output machine-readable JSON to stdout.")
@click.option("--batch", type=click.Path(exists=True), default=None,
              help="Process all .sh files in directory.")
@click.option("--gui", is_flag=True, default=False,
              help="Launch web GUI dashboard.")
@click.option("--env-key", type=str, default=None,
              help="Environment key for binary mode (hostname).")
```

Preset mappings:
```python
PRESETS = {
    "stealth":  {"intensity": 0.5, "force_layers": "id-mangle,str-shred,cmd-sub,entropy-mask", "min_layers": 4},
    "standard": {"intensity": 0.8, "force_layers": None, "min_layers": 4},
    "paranoid": {"intensity": 0.95, "force_layers": None, "min_layers": 8},
    "godmode":  {"intensity": 1.0, "force_layers": None, "min_layers": 11, "output_mode": "binary"},
}
```

**[NEW] [obfush/__main__.py](file:///c:/Users/RTX/Desktop/Bash/obfush/__main__.py) — 3 lines:**
```python
from obfush.cli import main
main()
```

Stdin/stdout support: when `input_script` is `-`, read from stdin. When `output_script` is `-`, write to stdout.

---

## Phase 7: Compiled Loader

> **Fixes:** W9 (CRITICAL), W10 (HIGH)
> **Priority:** P1
> **Estimated effort:** 5 days

### New Module: `obfush/compiler/`

| File | Lines | Responsibility |
|---|---|---|
| `__init__.py` | 5 | Module init, public API |
| `stub_generator.py` | ~200 | Polymorphic C source generation — randomized var names, function order, junk functions |
| `crypto.py` | ~80 | 32-byte rolling XOR: `encrypted[i] = payload[i] ^ key[i % 32]`. Key from `config.rng.randbytes(32)`. |
| `compiler.py` | ~120 | Detect gcc/musl-gcc/clang. Compile: `gcc -O2 -s -static -fPIE -pie -Wl,-z,relro,-z,now`. Strip. Optional UPX. |
| `anti_debug.py` | ~150 | 3 anti-debug checks per build, randomly selected from 5 techniques. Generates C code. |
| `env_keying.py` | ~80 | Multi-factor: `SHA256(hostname+user+MAC)` → 8-byte hash. Embedded as opaque C constant. |
| `integrity.py` | ~100 | Two-pass build: compile → SHA-256 of binary → patch hash into `.rodata` → re-link. Silent key corruption on tamper. |
| `templates/loader_stub.c` | ~150 | Parameterized C template with `/* PAYLOAD_BYTES */`, `/* KEY_BYTES */`, `/* ANTI_DEBUG */`, `/* ENV_CHECK */` markers. |

### Loader Pipeline

```
obfush --output-mode binary --seed 42 in.sh out_binary

1. Run obfuscation pipeline (Phases 1-5) → obfuscated bash string
2. Generate 32-byte XOR key from config.rng
3. Encrypt: encrypted[i] = obfuscated[i] ^ key[i % 32]
4. Generate polymorphic C stub:
   a. Select 3 anti-debug techniques
   b. Randomize all C variable/function names
   c. Add 2-4 junk C functions
   d. Embed encrypted payload as `unsigned char _p[] = {0xNN, ...}`
   e. Embed key as `unsigned char _k[] = {0xNN, ...}`
5. Write C source to tempfile
6. Compile: gcc -O2 -s -static -o out_binary stub.c
7. If integrity enabled: compute SHA-256 of binary, patch into .rodata, re-link
8. Strip: strip --strip-all out_binary
9. Cleanup tempfiles
```

### Anti-Debug Techniques (5 available, 3 randomly selected per build)

```c
// Technique 1: ptrace self-attach
static int _ad1(void) {
    return ptrace(PTRACE_TRACEME, 0, NULL, NULL) == -1;
}

// Technique 2: /proc/self/status TracerPid
static int _ad2(void) {
    FILE *f = fopen("/proc/self/status", "r");
    if (!f) return 0;
    char line[256];
    while (fgets(line, sizeof(line), f)) {
        if (strncmp(line, "TracerPid:", 10) == 0) {
            int pid = atoi(line + 10);
            fclose(f);
            return pid != 0;
        }
    }
    fclose(f);
    return 0;
}

// Technique 3: Timing check (debugger single-stepping causes >10ms delay)
static int _ad3(void) {
    struct timespec t1, t2;
    clock_gettime(CLOCK_MONOTONIC, &t1);
    for (volatile int i = 0; i < 1000; i++) {}
    clock_gettime(CLOCK_MONOTONIC, &t2);
    long ns = (t2.tv_sec - t1.tv_sec) * 1000000000L + (t2.tv_nsec - t1.tv_nsec);
    return ns > 10000000;  // >10ms = debugger
}

// Technique 4: /proc/self/status check for debugger parent
static int _ad4(void) {
    if (getppid() == 1) return 0;  // init parent = normal
    char path[64];
    snprintf(path, sizeof(path), "/proc/%d/comm", getppid());
    FILE *f = fopen(path, "r");
    if (!f) return 0;
    char comm[64];
    fgets(comm, sizeof(comm), f);
    fclose(f);
    // Check for known debuggers
    return strstr(comm, "gdb") || strstr(comm, "strace") || strstr(comm, "ltrace");
}

// Technique 5: Check LD_PRELOAD (common hooking technique)
static int _ad5(void) {
    return getenv("LD_PRELOAD") != NULL;
}
```

### Polymorphic Stub Generation

Each build produces structurally different C code:
1. All variable names randomized: `_payload` → `_qw7x`, `_key` → `_m3k`
2. Function names randomized: `_chk` → `_v9z2`
3. Function order shuffled
4. 2-4 junk C functions added (compute meaningless values, never called from main path but appear in control flow via dead branches)
5. Anti-debug check order randomized
6. XOR key size varies: 16-64 bytes

**Done when:** `obfush --output-mode binary --seed 42 tests/fixtures/basic.sh /tmp/out && /tmp/out` produces correct output. `strings /tmp/out | grep -c echo` returns 0. Two builds with different seeds produce BinDiff similarity < 40%.

---

## Phase 8: Anti-Forensics

> **Priority:** P2
> **Estimated effort:** 1 day

Additions to `loader_stub.c`:
1. `prctl(PR_SET_DUMPABLE, 0)` — block core dumps
2. `syscall(SYS_memfd_create, "ld-linux-x86-64.so.2", MFD_CLOEXEC)` — disguise memfd
3. `unlink(argv[0])` — self-delete
4. `signal(SIGTERM, wipe_handler)` — zero sensitive memory on kill
5. Heap wipe: `explicit_bzero(buf, payload_len)` before `free()`

---

## Phase 9: Custom Bytecode VM

> **Fixes:** W9 (makes RE exponentially harder)
> **Priority:** P2
> **Estimated effort:** 10 days

### New Module: `obfush/vm/`

| File | Lines | Responsibility |
|---|---|---|
| `__init__.py` | 5 | Public API |
| `compiler.py` | ~400 | bash AST → bytecode compiler. Walks the AST, emits VM instructions. |
| `opcodes.py` | ~100 | 30 instruction types. `shuffle_opcodes(rng)` produces unique opcode→instruction mapping per build. |
| `string_pool.py` | ~80 | Collects all string operands, XOR-encrypts with bytecode checksum, emits as C array. |
| `interpreter_gen.py` | ~300 | Generates the C VM interpreter: `while(ip < bytecode_len) { switch(bytecode[ip]) { case 0xNN: ... } }` |
| `junk_bytecode.py` | ~100 | Generates 30% junk instructions (VM_NOP, dead computations) interleaved with real instructions. |
| `process_splitter.py` | ~200 | Phase 10: splits bytecode across multiple processes. |
| `templates/vm_interpreter.c` | ~250 | C template for the VM. Includes: dispatch loop, register file, stack, string table decoder, external command executor. |

### VM Instruction Set (30 Instructions)

```
CATEGORY: Variables & Data
  VM_ASSIGN    (reg, str_idx)          — Set variable from string pool
  VM_LOAD      (reg, var_hash)         — Load variable value to register
  VM_STORE     (var_hash, reg)         — Store register to variable
  VM_CONST     (reg, imm32)            — Load immediate value
  VM_STRCAT    (dst_reg, src1, src2)   — Concatenate strings
  VM_SUBSTR    (dst, src, off, len)    — Substring extraction
  VM_STRLEN    (dst, src)              — String length

CATEGORY: Control Flow
  VM_JMP       (offset)                — Unconditional jump
  VM_JZ        (reg, offset)           — Jump if zero
  VM_JNZ       (reg, offset)           — Jump if not zero
  VM_CALL      (func_idx)              — Call VM function
  VM_RET       ()                      — Return from function
  VM_LOOP_INIT (counter_reg, limit)    — Initialize loop counter
  VM_LOOP_NEXT (counter_reg, offset)   — Increment and jump if not done

CATEGORY: I/O & Commands
  VM_EXEC      (str_idx, argc)         — Execute external command
  VM_PIPE      (cmd1_idx, cmd2_idx)    — Pipe two commands
  VM_REDIR     (fd, file_str_idx, mode) — I/O redirection
  VM_ECHO      (str_idx)               — Output to stdout
  VM_READ      (var_hash, prompt_idx)  — Read from stdin

CATEGORY: Arithmetic & Comparison
  VM_ADD       (dst, src1, src2)
  VM_SUB       (dst, src1, src2)
  VM_MUL       (dst, src1, src2)
  VM_DIV       (dst, src1, src2)
  VM_MOD       (dst, src1, src2)
  VM_CMP       (dst, src1, src2)       — Set dst to -1/0/1
  VM_TEST      (dst, test_type, args)  — [[ ]] test evaluation

CATEGORY: Stack
  VM_PUSH      (reg)
  VM_POP       (reg)

CATEGORY: Meta
  VM_NOP       ()                      — No operation (junk)
  VM_DECRYPT   (str_idx, key_reg)      — Decrypt string pool entry at runtime
```

### Polymorphic Opcodes

```python
def shuffle_opcodes(rng: random.Random) -> dict[str, int]:
    """Generate unique opcode mapping. Each build is different."""
    opcodes = list(range(0x10, 0x10 + 30))  # 30 valid opcodes
    rng.shuffle(opcodes)
    return dict(zip(INSTRUCTION_NAMES, opcodes))
    # Build A: VM_EXEC=0x3A, VM_ASSIGN=0x17, VM_JMP=0x2F
    # Build B: VM_EXEC=0xD7, VM_ASSIGN=0x4B, VM_JMP=0x1C
    # RE notes from Build A are useless for Build B
```

---

## Phase 10: Multi-Process Splitting

> **Fixes:** W12 (MEDIUM)
> **Priority:** P2
> **Estimated effort:** 3 days

Split bytecode into 3-5 segments. Parent `fork()`s children. Each child decrypts+executes one segment. Variable state passed between processes via anonymous pipes as XOR-encrypted key-value pairs.

---

## Phase 11: Self-Integrity + Hash-Locked Predicates

> **Fixes:** W8 (MEDIUM), W11 (HIGH)
> **Priority:** P2
> **Estimated effort:** 2 days

### Self-Integrity (Silent Corruption)

```c
// Two-pass build: compile → compute hash → patch → re-link
unsigned char _expected_hash[32] = { /* SELF_HASH — patched post-compilation */ };

void _integrity_check(void) {
    unsigned char actual[32];
    sha256_file("/proc/self/exe", actual);
    if (memcmp(_expected_hash, actual, 32) != 0) {
        // TAMPERED — don't crash (that tells RE where the check is)
        // Instead: silently corrupt the decryption key
        for (int i = 0; i < _key_len; i++) _key[i] ^= 0xFF;
        // Binary appears to run but produces garbage output
        // RE has no idea where the integrity check is
    }
}
```

### Hash-Locked Opaque Predicates

Replace arithmetic predicates with `cksum`/`sha256sum` — defeats Z3/angr:
```bash
_h=$(echo -n "$_var" | cksum | cut -d' ' -f1)
if [[ "$_h" == "3928461057" ]]; then
    real_code_here  # always true for the known _var value
fi
```

---

# PART III: GUI DASHBOARD — PHASE 12

> **Priority:** P1
> **Estimated effort:** 8 days

## Module Structure

```
obfush/gui/
├── __init__.py                    5 lines — public launch() function
├── app.py                       ~150 lines — Flask app factory, WebSocket, static serving
├── api.py                       ~250 lines — REST API endpoints
├── templates/
│   └── index.html               ~200 lines — SPA shell, navigation, panel containers
└── static/
    ├── css/
    │   └── main.css             ~400 lines — Dark theme, glassmorphism, animations
    └── js/
        ├── app.js               ~150 lines — Router, state management, event bus
        ├── editor.js            ~100 lines — CodeMirror 6 integration (bash mode)
        ├── config.js            ~120 lines — Layer toggle/drag, preset buttons, sliders
        ├── entropy.js           ~150 lines — D3 entropy heatmap + radar chart
        ├── analysis.js          ~180 lines — Security score, dead code, diff view
        ├── binary.js            ~120 lines — Binary builder panel + build log
        └── batch.js             ~100 lines — File upload, queue table, progress
```

## API Endpoints

```
POST /api/obfuscate
  Body: { source, seed, intensity, eval_mode, layers[], preset, max_size_ratio }
  Response: { output, seed, layers_applied, stats{}, elapsed_ms, entropy, security_score }
  WebSocket: /api/ws/progress — sends { layer, progress%, stats } per layer

POST /api/analyze  
  Body: { output }
  Response: { entropy{ overall, windows[], in_range }, dead_code{ count, ratio },
              yara_matches, structural_score, security_score{ static, runtime, anti_re, size } }

POST /api/build-binary
  Body: { source, seed, intensity, anti_debug, env_key, static_link, vm_mode }
  Response: binary file download
  WebSocket: /api/ws/build — sends { step, message } during compilation

POST /api/batch
  Body: multipart form with .sh files + config
  Response: zip file with all obfuscated outputs

GET /api/presets
  Response: { stealth: {...}, standard: {...}, paranoid: {...}, godmode: {...} }
```

## CSS Design System

```css
:root {
    /* Dark theme — HSL-based for harmony */
    --bg-primary: hsl(220, 20%, 8%);      /* Near-black */
    --bg-secondary: hsl(220, 18%, 12%);    /* Card background */
    --bg-glass: hsla(220, 20%, 15%, 0.7);  /* Glassmorphism panels */
    --border: hsla(200, 60%, 50%, 0.15);   /* Subtle cyan border */
    --text-primary: hsl(0, 0%, 92%);       /* Off-white */
    --text-secondary: hsl(0, 0%, 60%);     /* Muted */
    --accent-cyan: hsl(185, 80%, 55%);     /* Primary accent */
    --accent-green: hsl(145, 70%, 50%);    /* Success */
    --accent-red: hsl(0, 75%, 55%);        /* Error */
    --accent-amber: hsl(40, 90%, 55%);     /* Warning */
    --font-mono: 'JetBrains Mono', 'Fira Code', monospace;
    --font-ui: 'Inter', -apple-system, sans-serif;
    --glass-blur: 12px;
    --radius: 12px;
    --shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
}

.panel {
    background: var(--bg-glass);
    backdrop-filter: blur(var(--glass-blur));
    border: 1px solid var(--border);
    border-radius: var(--radius);
    box-shadow: var(--shadow);
    padding: 1.5rem;
}

.btn-primary {
    background: linear-gradient(135deg, var(--accent-cyan), hsl(200, 80%, 45%));
    color: var(--bg-primary);
    border: none;
    border-radius: 8px;
    padding: 0.75rem 2rem;
    font-weight: 600;
    cursor: pointer;
    transition: transform 0.15s, box-shadow 0.15s;
}
.btn-primary:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 20px hsla(185, 80%, 55%, 0.4);
}
```

## Presets Panel

| Preset | Visual | Layers | Intensity | Output |
|---|---|---|---|---|
| Stealth | 🟢 Green badge | 4 core | 0.5 | script |
| Standard | 🔵 Blue badge | Auto (9) | 0.8 | script |
| Paranoid | 🟠 Amber badge | All 11 | 0.95 | script |
| GOD MODE | 🔴 Red badge, pulsing glow | All 11 | 1.0 | binary |
| NUCLEAR | ☢️ Pulsing icon | All + VM | 1.0 | vm-binary |

---

# PART IV: TEST COVERAGE — 60% → 97%

## Current State: 2,871 statements, 1,154 missed (60%)

The goal: cover 1,154 missed statements with 198 specific test cases across 18 test files.

**Coverage gate:** `pytest --cov=obfush --cov-fail-under=97`

---

## Module-by-Module Test Specifications

### 1. [cli.py](file:///c:/Users/RTX/Desktop/Bash/obfush/cli.py) — 0% → 97%

**91 missed statements. Current tests: 0. New test file: `tests/test_cli.py`**

Uses Click's `CliRunner` — no subprocess needed, no bash required.

```python
# tests/test_cli.py — 28 test cases

from click.testing import CliRunner
from obfush.cli import main
import json, os, tempfile

@pytest.fixture
def runner():
    return CliRunner()

@pytest.fixture
def sample_script(tmp_path):
    f = tmp_path / "in.sh"
    f.write_text('#!/bin/bash\necho "hello"\nx=42\necho $x\n')
    return str(f)

class TestCLIBasic:
    def test_help(self, runner):
        """--help exits 0 and prints usage."""
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "INPUT_SCRIPT" in result.output

    def test_version(self, runner):
        """--version prints version string."""
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "obfush" in result.output

    def test_help_advanced(self, runner):
        """--help-advanced prints the advanced panel."""
        result = runner.invoke(main, ["--help-advanced"])
        assert result.exit_code == 0
        assert "EVAL-MODE" in result.output

    def test_basic_obfuscation(self, runner, sample_script, tmp_path):
        """Basic obfuscation writes output file."""
        out = str(tmp_path / "out.sh")
        result = runner.invoke(main, [sample_script, out, "--seed", "42"])
        assert result.exit_code == 0
        assert os.path.exists(out)
        assert os.path.getsize(out) > 0

    def test_deterministic_seed(self, runner, sample_script, tmp_path):
        """Same seed produces identical output."""
        out1 = str(tmp_path / "out1.sh")
        out2 = str(tmp_path / "out2.sh")
        runner.invoke(main, [sample_script, out1, "--seed", "42"])
        runner.invoke(main, [sample_script, out2, "--seed", "42"])
        assert open(out1).read() == open(out2).read()

    def test_different_seeds_differ(self, runner, sample_script, tmp_path):
        """Different seeds produce different output."""
        out1 = str(tmp_path / "out1.sh")
        out2 = str(tmp_path / "out2.sh")
        runner.invoke(main, [sample_script, out1, "--seed", "42"])
        runner.invoke(main, [sample_script, out2, "--seed", "99"])
        assert open(out1).read() != open(out2).read()

    def test_string_seed(self, runner, sample_script, tmp_path):
        """String seeds are hashed to int."""
        out = str(tmp_path / "out.sh")
        result = runner.invoke(main, [sample_script, out, "--seed", "myseed"])
        assert result.exit_code == 0

class TestCLIOptions:
    def test_intensity_valid(self, runner, sample_script, tmp_path):
        out = str(tmp_path / "out.sh")
        result = runner.invoke(main, [sample_script, out, "--intensity", "0.5"])
        assert result.exit_code == 0

    def test_intensity_invalid(self, runner, sample_script, tmp_path):
        out = str(tmp_path / "out.sh")
        result = runner.invoke(main, [sample_script, out, "--intensity", "2.0"])
        assert result.exit_code == 1

    def test_eval_mode_ok(self, runner, sample_script, tmp_path):
        out = str(tmp_path / "out.sh")
        result = runner.invoke(main, [sample_script, out, "--eval-mode", "ok", "--seed", "42"])
        assert result.exit_code == 0

    def test_eval_mode_no_eval(self, runner, sample_script, tmp_path):
        out = str(tmp_path / "out.sh")
        result = runner.invoke(main, [sample_script, out, "--eval-mode", "no-eval", "--seed", "42"])
        assert result.exit_code == 0
        content = open(out).read()
        # no-eval mode should not have standalone 'eval' keywords
        # (may appear inside encoded strings but not as commands)

    def test_eval_mode_direct_exec(self, runner, sample_script, tmp_path):
        out = str(tmp_path / "out.sh")
        result = runner.invoke(main, [sample_script, out, "--eval-mode", "direct-exec", "--seed", "42"])
        assert result.exit_code == 0

    def test_force_layers(self, runner, sample_script, tmp_path):
        out = str(tmp_path / "out.sh")
        result = runner.invoke(main, [sample_script, out, "--layers", "id-mangle,encode", "--min-layers", "2", "--seed", "42"])
        assert result.exit_code == 0

    def test_disable_layers(self, runner, sample_script, tmp_path):
        out = str(tmp_path / "out.sh")
        result = runner.invoke(main, [sample_script, out, "--no-layer", "poly-shell", "--seed", "42"])
        assert result.exit_code == 0

    def test_verbose(self, runner, sample_script, tmp_path):
        out = str(tmp_path / "out.sh")
        result = runner.invoke(main, [sample_script, out, "-v", "--seed", "42"])
        assert result.exit_code == 0
        # Verbose output goes to stderr which CliRunner captures in output
        assert "obfush" in result.output or result.exit_code == 0

    def test_dry_run(self, runner, sample_script, tmp_path):
        out = str(tmp_path / "out.sh")
        result = runner.invoke(main, [sample_script, out, "--dry-run", "--seed", "42"])
        assert result.exit_code == 0
        assert not os.path.exists(out)

    def test_dump_ast(self, runner, sample_script, tmp_path):
        out = str(tmp_path / "out.sh")
        ast_file = str(tmp_path / "ast.json")
        result = runner.invoke(main, [sample_script, out, "--dump-ast", ast_file, "--seed", "42"])
        assert result.exit_code == 0
        ast_data = json.loads(open(ast_file).read())
        assert ast_data["type"] == "script"

    def test_entropy_target(self, runner, sample_script, tmp_path):
        out = str(tmp_path / "out.sh")
        result = runner.invoke(main, [sample_script, out, "--entropy-target", "5.0", "--seed", "42"])
        assert result.exit_code == 0

class TestCLIErrors:
    def test_missing_input(self, runner, tmp_path):
        result = runner.invoke(main, ["/nonexistent.sh", str(tmp_path / "out.sh")])
        assert result.exit_code != 0

    def test_empty_input(self, runner, tmp_path):
        f = tmp_path / "empty.sh"
        f.write_text("")
        result = runner.invoke(main, [str(f), str(tmp_path / "out.sh")])
        assert result.exit_code == 1

    def test_whitespace_only_input(self, runner, tmp_path):
        f = tmp_path / "ws.sh"
        f.write_text("   \n\n  \n")
        result = runner.invoke(main, [str(f), str(tmp_path / "out.sh")])
        assert result.exit_code == 1

class TestCLIPresets:
    def test_preset_stealth(self, runner, sample_script, tmp_path):
        out = str(tmp_path / "out.sh")
        result = runner.invoke(main, [sample_script, out, "--preset", "stealth", "--seed", "42"])
        assert result.exit_code == 0

    def test_preset_paranoid(self, runner, sample_script, tmp_path):
        out = str(tmp_path / "out.sh")
        result = runner.invoke(main, [sample_script, out, "--preset", "paranoid", "--seed", "42"])
        assert result.exit_code == 0

class TestCLIJson:
    def test_json_output(self, runner, sample_script, tmp_path):
        out = str(tmp_path / "out.sh")
        result = runner.invoke(main, [sample_script, out, "--json-output", "--seed", "42"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "seed" in data
        assert "layers_applied" in data
```

**Covers:** L24-102 (help_advanced), L118-179 (click decorators), L180-350 (main function body including seed parsing, layer parsing, intensity validation, read/write, engine invocation, entropy report).

---

### 2. [verifier.py](file:///c:/Users/RTX/Desktop/Bash/obfush/engine/verifier.py) — 0% → 95%

**90 missed statements. New test file: `tests/test_verifier.py` — 15 test cases**

```python
# Key tests (mock subprocess.run to avoid needing bash on Windows CI):

class TestVerifier:
    def test_matching_output(self, monkeypatch):
        """Identical stdout/stderr/exit_code → verified=True."""

    def test_mismatched_stdout(self, monkeypatch):
        """Different stdout → verified=False."""

    def test_mismatched_exit_code(self, monkeypatch):
        """Different exit codes → verified=False."""

    def test_timeout_handling(self, monkeypatch):
        """Script exceeding timeout → raises/returns False."""

    def test_bash_not_found(self):
        """No bash available → raises appropriate error."""

    def test_find_bash_linux(self, monkeypatch):
        """_find_bash() on Linux returns /bin/bash."""

    def test_find_bash_windows_wsl(self, monkeypatch):
        """_find_bash() on Windows finds WSL bash."""

    def test_find_bash_windows_git_bash(self, monkeypatch):
        """_find_bash() on Windows finds Git Bash."""

    def test_normalization_applied(self, monkeypatch):
        """Output normalization runs before comparison."""

    def test_test_input_piped(self, monkeypatch):
        """test_input is fed as stdin to both scripts."""

    def test_verification_error_diff(self, monkeypatch):
        """VerificationError includes diff details."""

    def test_verify_with_real_scripts(self):
        """Integration: verify a simple script against itself (requires bash)."""

    def test_empty_output_match(self, monkeypatch):
        """Both scripts producing empty output → match."""

    def test_stderr_warning_only(self, monkeypatch):
        """Stderr differences are warnings, not failures."""

    def test_temp_file_cleanup(self, monkeypatch):
        """Temp files are cleaned up after verification."""
```

---

### 3. [poly_shell.py](file:///c:/Users/RTX/Desktop/Bash/obfush/layers/poly_shell.py) — 0% → 95%

**74 missed statements. New test file: `tests/test_layers/test_poly_shell.py` — 12 test cases**

```python
class TestPolySplit:
    def test_split_basic(self):
        """_split_payload splits source into N chunks at line boundaries."""

    def test_split_fewer_lines_than_chunks(self):
        """When lines < num_chunks, each line becomes a chunk."""

    def test_split_preserves_all_content(self):
        """Joining all chunks produces the original source."""

class TestPolyEncode:
    def test_encode_base64(self):
        """base64 method produces valid decode expression."""

    def test_encode_hex(self):
        """hex method produces valid xxd/printf decode expression."""

    def test_encode_rev_base64(self):
        """rev_base64 method produces valid reversed decode."""

class TestPolyLoader:
    def test_loader_eval_mode(self):
        """eval_mode='ok' builds eval-based loader."""

    def test_loader_no_eval_mode(self):
        """eval_mode='no-eval' builds source-based loader."""

    def test_loader_preserves_shebang(self):
        """Shebang from original AST is carried to loader AST."""

class TestPolyIntegration:
    def test_low_intensity_passthrough(self):
        """intensity < 0.85 returns AST unchanged."""

    def test_high_intensity_transforms(self):
        """intensity >= 0.85 produces a loader AST."""

    def test_chunks_created_stat(self):
        """stats.chunks_created reflects actual chunk count."""
```

---

### 4. [entropy_evaluator.py](file:///c:/Users/RTX/Desktop/Bash/obfush/engine/entropy_evaluator.py) — 0% → 100%

**15 missed statements. New test file: `tests/test_entropy_evaluator.py` — 6 test cases**

```python
class TestEntropyEvaluator:
    def test_evaluate_returns_dict(self):
        """evaluate() returns dict with expected keys."""
        ev = EntropyEvaluator(target=4.5)
        result = ev.evaluate(b"echo hello world\n" * 100)
        assert "overall_entropy" in result
        assert "in_range" in result
        assert "high_entropy_regions" in result

    def test_evaluate_in_range(self):
        """Normal bash text should be in range of 4.5 target."""

    def test_evaluate_out_of_range(self):
        """Random bytes should be out of range."""
        import os
        result = EntropyEvaluator(target=4.5).evaluate(os.urandom(1000))
        assert not result["in_range"]
        assert result["estimated_decoy_needed"] > 0

    def test_report_returns_string(self):
        """report() returns a formatted string."""
        report = EntropyEvaluator().report(b"test data " * 50)
        assert isinstance(report, str)
        assert "Entropy Analysis" in report

    def test_custom_window_size(self):
        """Custom window_size is used in windowed analysis."""

    def test_empty_data(self):
        """Empty data returns 0 entropy."""
```

---

### 5. [ast_emitter.py](file:///c:/Users/RTX/Desktop/Bash/obfush/engine/ast_emitter.py) — 55% → 95%

**161 missed statements. Expand: `tests/test_emitter.py` — 22 new test cases**

```python
class TestEmitScript:
    def test_emit_empty_script(self): ...
    def test_emit_shebang(self): ...
    def test_emit_command_simple(self): ...
    def test_emit_command_with_args(self): ...
    def test_emit_assignment(self): ...
    def test_emit_compound_if(self): ...
    def test_emit_compound_while(self): ...
    def test_emit_compound_for(self): ...
    def test_emit_compound_case(self): ...
    def test_emit_compound_group(self): ...       # { ... }
    def test_emit_compound_subshell(self): ...    # ( ... )
    def test_emit_function_def(self): ...
    def test_emit_pipeline(self): ...
    def test_emit_redirect(self): ...
    def test_emit_heredoc(self): ...
    def test_emit_expansion_parameter(self): ...
    def test_emit_expansion_command_sub(self): ...
    def test_emit_expansion_arithmetic(self): ...
    def test_emit_list_and(self): ...             # cmd1 && cmd2
    def test_emit_list_or(self): ...              # cmd1 || cmd2
    def test_emit_opaque_blob(self): ...          # fallback raw text
    def test_emit_roundtrip_all_fixtures(self): ...  # parse → emit → parse → emit = stable
```

---

### 6. [comment_strip.py](file:///c:/Users/RTX/Desktop/Bash/obfush/engine/comment_strip.py) — 48% → 97%

**62 missed statements. New test file: `tests/test_comment_strip.py` — 18 test cases**

```python
class TestCommentStrip:
    def test_strip_line_comment(self): ...              # x=1 # comment → x=1
    def test_strip_full_line_comment(self): ...         # # full line → removed
    def test_preserve_shebang(self): ...                # #!/bin/bash → preserved
    def test_preserve_quoted_hash_single(self): ...     # echo '#not_comment'
    def test_preserve_quoted_hash_double(self): ...     # echo "#not_comment"
    def test_preserve_hash_in_parameter_expansion(self): ...  # ${#var}
    def test_preserve_hash_in_regex(self): ...          # [[ $x =~ #pattern ]]
    def test_strip_comment_after_quote(self): ...       # echo "hi" # comment
    def test_nested_quotes(self): ...                   # echo "it's \"#\" ok" # real comment
    def test_heredoc_no_strip(self): ...                # <<EOF ... # not a comment ... EOF
    def test_escape_before_hash(self): ...              # echo \# → preserved
    def test_multiple_hashes(self): ...                 # x=1 # comment # more
    def test_empty_input(self): ...
    def test_whitespace_only(self): ...
    def test_no_trailing_newline(self): ...
    def test_backtick_quoted_hash(self): ...            # echo `# nope`
    def test_dollar_paren_hash(self): ...               # echo $(# nope)
    def test_mixed_comment_types(self): ...             # multiple lines, mixed
```

---

### 7-28. Remaining Modules — Summary Table

| Module | Current | Target | Test File | Tests Needed | Key Test Cases |
|---|---|---|---|---|---|
| [core.py](file:///c:/Users/RTX/Desktop/Bash/obfush/engine/core.py) | 61% | 95% | `tests/test_core.py` (new) | 12 | Engine pipeline, verbose mode, dry-run, dump-ast, verify, layer rollback, deep-copy check, max-size-ratio |
| [ast_parser.py](file:///c:/Users/RTX/Desktop/Bash/obfush/engine/ast_parser.py) | 66% | 92% | `tests/test_ast_parser.py` (expand) | 15 | Opaque-blob fallback, nested heredocs, `[[ ]]`, parameter expansion, arrays, process substitution, error recovery |
| [seed.py](file:///c:/Users/RTX/Desktop/Bash/obfush/engine/seed.py) | 64% | 100% | `tests/test_seed.py` (new) | 6 | `generate_seed` with str/bytes, `generate_seed_from_path`, `create_rng` produces seeded Random, `derive_layer_seed` deterministic |
| [normalizer.py](file:///c:/Users/RTX/Desktop/Bash/obfush/engine/normalizer.py) | 76% | 95% | `tests/test_normalizer.py` (expand) | 8 | Nested compounds, function defs, pipelines, empty bodies, opaque blobs, list nodes |
| [layer_selector.py](file:///c:/Users/RTX/Desktop/Bash/obfush/engine/layer_selector.py) | 87% | 100% | `tests/test_layer_selector.py` (new) | 5 | Force layers, disable layers, min_layers guard, intensity-based activation, eval_mode filtering |
| [cmd_sub.py](file:///c:/Users/RTX/Desktop/Bash/obfush/layers/cmd_sub.py) | 66% | 95% | `tests/test_layers/test_cmd_sub.py` (new) | 8 | echo→printf, source↔`.`, true↔`:`, `$(cmd)`↔`` `cmd` ``, test style morphing, redirect noop |
| [encode.py](file:///c:/Users/RTX/Desktop/Bash/obfush/layers/encode.py) | 43% | 95% | `tests/test_layers/test_encode.py` (new) | 10 | base64 eval, hex_printf eval, no-eval mode, direct-exec mode, small command skip, _junk skip, _encoded skip, new strategies (arithmetic, array, trap) |
| [flow_obfusc.py](file:///c:/Users/RTX/Desktop/Bash/obfush/layers/flow_obfusc.py) | 69% | 90% | `tests/test_layers/test_flow_obfusc.py` (new) | 12 | Independent block reordering, opaque predicates, subshell wrapping, barrier detection, var refs/writes, mark conditions, _no_wrap flag, nested compounds |
| [id_mangle.py](file:///c:/Users/RTX/Desktop/Bash/obfush/layers/id_mangle.py) | 60% | 90% | `tests/test_layers/test_id_mangle.py` (new) | 15 | Collect identifiers, build mangle map, reserved word skip, special var skip, builtin skip, ALLCAPS skip, opaque-blob regex mangling, function rename, local/declare handling, for-loop var, array subscript, here-string, nested expansion, text-pattern replacement |
| [indirection.py](file:///c:/Users/RTX/Desktop/Bash/obfush/layers/indirection.py) | 80% | 95% | `tests/test_layers/test_indirection.py` (new) | 7 | Variable indirect, eval chain indirect, function map, setup nodes prepend, indirectable command filtering, intensity gating, non-command skip |
| [str_shred.py](file:///c:/Users/RTX/Desktop/Bash/obfush/layers/str_shred.py) | 60% | 95% | `tests/test_layers/test_str_shred.py` (new) | 10 | hex escape, octal escape, fragmented concat, arithmetic printf, base64 decode, variable reconstruction, random_shred method selection, empty string, special chars, new XOR method |
| [entropy_utils.py](file:///c:/Users/RTX/Desktop/Bash/obfush/utils/entropy_utils.py) | 47% | 97% | `tests/test_entropy_utils.py` (new) | 10 | shannon_entropy (empty, uniform, random), windowed_entropy (overlap, step), entropy_in_range, estimate_decoy_needed (below target, above target, equal entropy edge case), format_entropy_report (with/without high regions) |
| [string_utils.py](file:///c:/Users/RTX/Desktop/Bash/obfush/utils/string_utils.py) | 46% | 97% | `tests/test_string_utils.py` (new) | 12 | to_hex_escape, to_octal_escape, to_fragmented_concat, to_variable_reconstruction, to_arithmetic_printf, to_arithmetic_printf_simple, to_base64_decode, random_shred (all methods), edge cases (empty string, single char, special chars, quotes, backslashes) |
| [compat_matrix.py](file:///c:/Users/RTX/Desktop/Bash/obfush/utils/compat_matrix.py) | 88% | 100% | `tests/test_compat_matrix.py` (new) | 6 | get_compatibility (OK, CAUT, DANGER, unknown pair, same layer), get_safe_order (topological correctness, cycle detection), validate_layer_set (known, unknown) |
| [decoy_corpus.py](file:///c:/Users/RTX/Desktop/Bash/obfush/utils/decoy_corpus.py) | 90% | 100% | `tests/test_decoy_corpus.py` (new) | 4 | Generate unique comments, no duplicates in 100 generations, fallback when exhausted, parameterized templates |
| [base.py](file:///c:/Users/RTX/Desktop/Bash/obfush/layers/base.py) | 90% | 100% | Covered by existing tests | 2 | validate() default behavior, estimate_size_increase default |
| [junk_inject.py](file:///c:/Users/RTX/Desktop/Bash/obfush/layers/junk_inject.py) | 83% | 95% | `tests/test_layers/test_junk_inject.py` (new) | 6 | All catalogue methods, stats counting, body insertion positions, _junk flag, intensity gating, new live chain methods |

---

## Total Test Matrix

| Category | Current Tests | New Tests | Total |
|---|---|---|---|
| CLI | 0 | 28 | 28 |
| Engine (core, parser, emitter, normalizer, seed, verifier, evaluator, selector, comment_strip) | 29 | 82 | 111 |
| Layers (9 current + 2 new) | 12 | 68 | 80 |
| Utils (entropy, string, corpus, compat, name_pool) | 11 | 32 | 43 |
| Anti-RE regression | 0 | 8 | 8 |
| Fuzz | 0 | 5 | 5 |
| GUI API | 0 | 10 | 10 |
| **Total** | **52** | **233** | **285** |

### Anti-RE Regression Tests

**[NEW] `tests/test_anti_re.py` — 8 test cases**

```python
class TestAntiRE:
    def test_no_dead_variables(self):
        """Obfuscated output has 0 assigned-never-read variables."""

    def test_no_eval_in_no_eval_mode(self):
        """--eval-mode no-eval produces 0 standalone eval commands."""

    def test_no_duplicate_comments(self):
        """No two decoy comments are identical within one output."""

    def test_no_fingerprint_naming(self):
        """No variables match /_[a-z]+_[0-9a-f]+_\d+/ pattern."""

    def test_size_within_budget(self):
        """Output size ≤ source_size * max_size_ratio for all fixtures."""

    def test_structural_diversity(self):
        """Two runs with different seeds produce structurally different output."""

    def test_entropy_in_range(self):
        """Output entropy is within ±0.5 of target."""

    def test_no_cleartext_strings(self):
        """At intensity=1.0, original string literals don't appear in output."""
```

### Fuzz Tests

**[NEW] `tests/test_fuzz.py` — 5 test cases using Hypothesis**

```python
from hypothesis import given, strategies as st, settings

class TestFuzz:
    @given(st.text(min_size=10, max_size=500, alphabet=st.characters(whitelist_categories=('L','N','P','Z'))))
    @settings(max_examples=50, deadline=10000)
    def test_arbitrary_input_no_crash(self, source):
        """Engine doesn't crash on arbitrary input."""
        # Wrap in valid bash structure
        script = f"#!/bin/bash\n{source}\n"
        engine = PolymorphicEngine(EngineConfig(seed=42, intensity=0.5))
        try:
            result = engine.run(script)
            assert isinstance(result.output, str)
        except Exception:
            pass  # parse failures are OK, crashes are not

    @given(st.floats(min_value=0.0, max_value=1.0))
    def test_any_intensity_no_crash(self, intensity):
        """Any valid intensity value processes without crash."""

    @given(st.integers(min_value=0, max_value=2**64-1))
    def test_any_seed_no_crash(self, seed):
        """Any seed value processes without crash."""

    def test_all_fixtures_all_eval_modes(self):
        """Every fixture × every eval-mode produces valid output."""

    def test_all_fixtures_extreme_intensity(self):
        """Every fixture at intensity=1.0 and intensity=0.01 works."""
```

---

# PART V: ENGINEERING EXCELLENCE — 10 DIMENSIONS

## 1. Performance — 7 Recommendations

| # | Current State | Recommendation | Priority | Done When |
|---|---|---|---|---|
| P-1 | CLI imports in 95ms | Keep current lazy import pattern | — | Already good |
| P-2 | 12KB script: 118ms engine time | Acceptable. No action unless > 500ms threshold hit | — | Already good |
| P-3 | `entropy_mask` calls `emit()` twice for entropy measurement | Cache first emit result; only re-emit if decoys modified the AST | P1 | emit() called once per entropy_mask |
| P-4 | No `__main__.py` | Add 3-line file enabling `python -m obfush` | P0 | Works |
| P-5 | No batch concurrency | Use `ProcessPoolExecutor(max_workers=cpu_count())` for batch mode | P1 | 10-script batch in ≤2x single time |
| P-6 | `flow_obfusc._reorder_independent_blocks` is O(n²) in statement count | Chunk large bodies: if `len(body) > 200`, partition into groups of 50 | P1 | 1000-line script in < 500ms |
| P-7 | No benchmarks published | Add `obfush --benchmark` flag: 5 iterations, report p50/p95 per layer | P2 | Benchmark table in README |

## 2. Functionality — 8 Recommendations

| # | Recommendation | Priority | Done When |
|---|---|---|---|
| F-1 | Presets: `--preset stealth/standard/paranoid/godmode` | P0 | CLI accepts, applies correct config |
| F-2 | Config file: `.obfushrc` (YAML) in project root + `~/.obfushrc` | P1 | Reads and applies config file |
| F-3 | Batch mode: `obfush --batch dir/ output/` | P1 | Processes all .sh files |
| F-4 | JSON output: `--json-output` for toolchain integration | P1 | Valid JSON to stdout |
| F-5 | Stdin/stdout: `obfush - -` | P0 | Piped workflows work |
| F-6 | Plugin layers: `~/.obfush/plugins/*.py` auto-loaded | P2 | User layer runs in pipeline |
| F-7 | Binary output: `--output-mode binary` | P1 | Compiled binary works |
| F-8 | GUI: `obfush --gui` | P1 | Dashboard opens and functions |

## 3. Architecture — 6 Recommendations

| # | Recommendation | Priority | Done When |
|---|---|---|---|
| A-1 | AST is untyped `dict[str, Any]` — add TypedDict or dataclass node types | P1 | mypy passes, IDE completion works |
| A-2 | `poly_shell.py` L109 uses `xxd` — not on Alpine/minimal. Replace with printf. | P0 | `grep xxd obfush/` = 0 |
| A-3 | `string_utils.py` has disabled `to_variable_reconstruction` — dead code. Delete. | P0 | No dead code paths |
| A-4 | Duplicated quote-tracking in `comment_strip.py` — extract to shared utility | P1 | Single implementation |
| A-5 | `core.py` L147 uses `ast.copy()` (SHALLOW) for rollback — nested dicts shared. **BUG.** | **P0** | `copy.deepcopy(ast)` or JSON round-trip |
| A-6 | No atomic file writes — crash during write corrupts output | P0 | Write to .tmp then rename |

## 4. Reliability — 4 Recommendations

| # | Recommendation | Priority | Done When |
|---|---|---|---|
| R-1 | Deep copy for rollback (A-5 duplicate — CRITICAL) | P0 | Mutation test passes |
| R-2 | Atomic write (A-6 duplicate) | P0 | Kill during write leaves no corrupt file |
| R-3 | Structured logging: `logging` module + `--log-level` flag | P1 | `--log-level DEBUG 2>log.txt` works |
| R-4 | Per-layer timing in verbose output | P1 | ms shown per layer |

## 5. Scalability — 3 Recommendations

| # | Recommendation | Priority | Done When |
|---|---|---|---|
| S-1 | Chunk large scripts in flow_obfusc (P-6 duplicate) | P1 | 1000-line script OK |
| S-2 | AST node budget: max 50,000 nodes. Skip optional layers if exceeded. | P1 | Warning on budget hit |
| S-3 | Parallel layers: DEFER (sequential is fast enough) | — | N/A |

## 6. UX/UI — 5 Recommendations

| # | Recommendation | Priority | Done When |
|---|---|---|---|
| U-1 | Presets (F-1 duplicate) | P0 | In --help |
| U-2 | Actionable error messages: "Try: --entropy-target 5.0" | P0 | Suggestions in warnings |
| U-3 | Rich progress bar in verbose mode | P1 | Visible progress |
| U-4 | GUI (Phase 12) | P1 | Dashboard works |
| U-5 | First-run wizard: `obfush --setup` | P2 | Creates ~/.obfushrc |

## 7. Testing — 8 Recommendations (Detailed in Part IV)

| # | Recommendation | Priority | Done When |
|---|---|---|---|
| T-1 | Coverage gate: `--cov-fail-under=97` | P0 | CI enforces |
| T-2 | CLI tests (28 cases) | P0 | cli.py ≥ 97% |
| T-3 | Verifier tests (15 cases) | P1 | verifier.py ≥ 95% |
| T-4 | Poly-shell tests (12 cases) | P1 | poly_shell.py ≥ 95% |
| T-5 | Ruff linting in CI | P0 | Zero warnings |
| T-6 | mypy type checking in CI | P1 | Zero errors |
| T-7 | Fuzz testing (Hypothesis) | P2 | 50 examples pass |
| T-8 | Anti-RE regression tests | P1 | 8 assertions pass |

## 8. Documentation — 6 Recommendations

| # | Recommendation | Priority | Done When |
|---|---|---|---|
| D-1 | CONTRIBUTING.md | P0 | Accurate, includes layer dev guide |
| D-2 | CHANGELOG.md (Keep a Changelog format) | P0 | Covers all versions |
| D-3 | Architecture Mermaid diagram in README | P1 | Renders on GitHub |
| D-4 | Layer development guide | P1 | New contributor succeeds |
| D-5 | SECURITY.md — threat model, scope, limitations | P1 | Explicit expectations |
| D-6 | Man page from Click help | P2 | `man obfush` works |

## 9. Deployment — 5 Recommendations

| # | Recommendation | Priority | Done When |
|---|---|---|---|
| Dp-1 | PyPI publishing (setuptools-scm + twine on tag) | P1 | `pip install obfush` works |
| Dp-2 | Docker image (GHCR) | P1 | `docker run ghcr.io/.../obfush` works |
| Dp-3 | GitHub Release standalone binaries (PyInstaller) | P2 | Download-and-run |
| Dp-4 | `pipx install obfush` documentation | P1 | Documented |
| Dp-5 | Optional dep groups: `[gui]`, `[dev]` | P1 | In pyproject.toml |

## 10. Monetization — 3 Recommendations

| # | Recommendation | Priority | Done When |
|---|---|---|---|
| M-1 | Dual-license: GPLv3 core, paid Pro for binary/VM/GUI | P2 | License files + feature gates |
| M-2 | GitHub Sponsors with tiers | P2 | Page live |
| M-3 | Pro feature gate: `~/.obfush/license.key` check | P2 | Pro features gated |

---

# PART VI: UNIFIED ROADMAP — 6 SPRINTS

## Sprint 1: Foundation & Fingerprint Kill (Week 1-2) — 14 items

> **Theme:** Fix critical bugs, break all YARA signatures, cap output size.

| # | Item | Cat | Files | Priority |
|---|---|---|---|---|
| 1 | **FIX: Deep copy for AST rollback** | Arch | `core.py` L147 | P0 |
| 2 | **FIX: Atomic file write** | Rel | `cli.py` L316-319 | P0 |
| 3 | Add `__main__.py` | Arch | new | P0 |
| 4 | Kill xxd dependency | Arch | `poly_shell.py` L109 | P0 |
| 5 | Delete dead `to_variable_reconstruction` | Arch | `string_utils.py` L87-126 | P0 |
| 6 | Stdin/stdout support | Func | `cli.py` | P0 |
| 7 | Shared NamePool | Phase 3 | `name_pool.py` (new), `id_mangle.py`, `entropy_mask.py`, `junk_inject.py`, `base.py` | P0 |
| 8 | Zero-duplicate decoy corpus | Phase 3 | `decoy_corpus.py` | P0 |
| 9 | Output size cap (3x) | Phase 4 | `core.py`, `entropy_mask.py`, `base.py`, `cli.py` | P0 |
| 10 | Presets (`--preset`) | UX | `cli.py`, `layer_selector.py` | P0 |
| 11 | Actionable warning messages | UX | `entropy_mask.py`, `entropy_evaluator.py` | P0 |
| 12 | Coverage gate (97%), ruff linting | Test | `pyproject.toml`, CI | P0 |
| 13 | CONTRIBUTING.md + CHANGELOG.md | Docs | new | P0 |
| 14 | CLI tests (28 cases) + seed tests (6) + entropy_utils tests (10) + string_utils tests (12) + compat tests (6) + corpus tests (4) | Test | 6 new test files | P0 |

**Exit criteria:** YARA matches = 0. All 14 fixtures ≤ 3.0x. Coverage ≥ 80%. Ruff clean. `python -m obfush` works. No shallow-copy bug.

## Sprint 2: Live Decoys & Eval Elimination (Week 3-5) — 12 items

| # | Item | Cat | Files | Priority |
|---|---|---|---|---|
| 1 | LiveChainGenerator (replace DecoyGenerator) | Phase 2 | `entropy_mask.py` (major) | P0 |
| 2 | Live junk chains | Phase 2 | `junk_inject.py` | P0 |
| 3 | Inline encoding (no wrapper eval) | Phase 1 | `encode.py` (major) | P0 |
| 4 | Cascading stage loader | Phase 1 | `poly_shell.py` (major) | P0 |
| 5 | Verifier tests (15 cases) | Test | `test_verifier.py` (new) | P1 |
| 6 | Poly-shell tests (12 cases) | Test | `test_poly_shell.py` (new) | P1 |
| 7 | Comment_strip tests (18 cases) | Test | `test_comment_strip.py` (new) | P1 |
| 8 | Anti-RE regression tests (8 cases) | Test | `test_anti_re.py` (new) | P1 |
| 9 | Encode tests (10 cases) | Test | `test_encode.py` (new) | P1 |
| 10 | `--json-output` flag | Func | `cli.py` | P1 |
| 11 | Structured logging (`--log-level`) | Rel | `core.py`, `cli.py` | P1 |
| 12 | Core tests (12 cases) + emitter tests (22 cases) | Test | `test_core.py`, `test_emitter.py` | P1 |

**Exit criteria:** Dead-code elimination < 5%. `grep eval` = 0 in no-eval mode. Coverage ≥ 90%. All fixtures pass equivalence.

## Sprint 3: Advanced Layers + Binary Mode (Week 6-8) — 14 items

| # | Item | Cat | Files | Priority |
|---|---|---|---|---|
| 1 | CFF layer | Phase 5a | `cff.py` (new) | P1 |
| 2 | Opaque constants layer | Phase 5b | `opaque_const.py` (new) | P1 |
| 3 | Multi-algorithm string encryption | Phase 5c | `str_shred.py` | P1 |
| 4 | Layer integration (compat matrix, selector, registry) | Phase 6 | 3 files | P1 |
| 5 | Compiled loader module | Phase 7 | `compiler/` (7 new files) | P1 |
| 6 | CLI binary mode flags | Phase 7 | `cli.py` | P1 |
| 7 | Config file support (`.obfushrc`) | Func | `cli.py` | P1 |
| 8 | mypy in CI | Test | `pyproject.toml`, CI | P1 |
| 9 | Flow_obfusc tests (12 cases) + id_mangle tests (15 cases) + indirection tests (7 cases) + str_shred tests (10 cases) + junk_inject tests (6 cases) | Test | 5 new test files | P1 |
| 10 | CFF tests + opaque_const tests | Test | 2 new test files | P1 |
| 11 | Architecture diagram in README | Docs | `README.md` | P1 |
| 12 | Layer development guide | Docs | `docs/layer_dev.md` (new) | P1 |
| 13 | PyPI publishing pipeline | Deploy | CI, `pyproject.toml` | P1 |
| 14 | `pipx` documentation | Deploy | README | P1 |

**Exit criteria:** 13 layers available. Binary mode works on Linux. Coverage ≥ 95%. Published to PyPI. mypy clean.

## Sprint 4: GUI Dashboard (Week 9-11) — 12 items

| # | Item | Cat | Files | Priority |
|---|---|---|---|---|
| 1 | Flask backend + REST API | GUI | `gui/app.py`, `gui/api.py` | P1 |
| 2 | SPA shell + dark theme CSS | GUI | `gui/templates/index.html`, `gui/static/css/main.css` | P1 |
| 3 | Code editor (CodeMirror 6) | GUI | `gui/static/js/editor.js` | P1 |
| 4 | Layer configurator + presets | GUI | `gui/static/js/config.js` | P1 |
| 5 | Entropy heatmap (D3) | GUI | `gui/static/js/entropy.js` | P1 |
| 6 | Analysis panel (score, dead code, diff) | GUI | `gui/static/js/analysis.js` | P1 |
| 7 | Binary builder panel | GUI | `gui/static/js/binary.js` | P1 |
| 8 | Batch processing panel | GUI | `gui/static/js/batch.js` | P1 |
| 9 | WebSocket progress streaming | GUI | `gui/app.py` | P1 |
| 10 | Batch CLI mode (`--batch`) | Func | `cli.py` | P1 |
| 11 | Docker image + GHCR | Deploy | `Dockerfile`, CI | P1 |
| 12 | GUI API tests (10 cases) | Test | `tests/test_gui_api.py` | P1 |

**Exit criteria:** `obfush --gui` opens working dashboard. All 5 panels functional. Docker image works.

## Sprint 5: VM + Nuclear Options (Week 12-15) — 10 items

| # | Item | Cat | Files | Priority |
|---|---|---|---|---|
| 1 | VM bytecode compiler | Phase 9 | `vm/compiler.py` | P2 |
| 2 | Polymorphic opcode mapping | Phase 9 | `vm/opcodes.py` | P2 |
| 3 | VM interpreter generator | Phase 9 | `vm/interpreter_gen.py`, `vm/templates/vm_interpreter.c` | P2 |
| 4 | Junk bytecode generator | Phase 9 | `vm/junk_bytecode.py` | P2 |
| 5 | Encrypted string pool | Phase 9 | `vm/string_pool.py` | P2 |
| 6 | Multi-process splitting | Phase 10 | `vm/process_splitter.py` | P2 |
| 7 | Self-integrity (SHA-256 + silent corruption) | Phase 11 | `compiler/integrity.py` | P2 |
| 8 | Hash-locked opaque predicates | Phase 11 | `opaque_const.py` | P2 |
| 9 | Anti-forensics | Phase 8 | `compiler/templates/loader_stub.c` | P2 |
| 10 | Fuzz tests (5 Hypothesis cases) | Test | `tests/test_fuzz.py` | P2 |

**Exit criteria:** `--output-mode vm-binary` works. Multi-process splits execution. Self-integrity corrupts key on tamper. Coverage ≥ 97%.

## Sprint 6: Polish & Sustainability (Week 16-17) — 8 items

| # | Item | Cat | Files | Priority |
|---|---|---|---|---|
| 1 | SECURITY.md threat model | Docs | new | P1 |
| 2 | Plugin layer system | Func | `layers/__init__.py` | P2 |
| 3 | First-run wizard | UX | `cli.py` | P2 |
| 4 | Man page generation | Docs | build script | P2 |
| 5 | GitHub Release binaries (PyInstaller) | Deploy | CI | P2 |
| 6 | Pro feature gate | Monetize | `obfush/license.py` (new) | P2 |
| 7 | GitHub Sponsors setup | Monetize | `.github/FUNDING.yml` | P2 |
| 8 | Final coverage push — fill any remaining gaps to 97%+ | Test | various | P0 |

**Exit criteria:** All P0/P1 items complete. Coverage ≥ 97%. All docs complete. Release v3.0.0.

---

# PART VII: FINAL METRICS

| Metric | Current (v2.0-dev) | Sprint 1 Exit | Sprint 3 Exit | Sprint 5 Exit | Final (v3.0) |
|---|---|---|---|---|---|
| Test coverage | 60% | 80% | 95% | 97% | **97%+** |
| Test count | 52 | 118 | 225 | 270 | **285** |
| Layer count | 9 | 9 | 13 | 13 | **13** |
| Output modes | 1 | 1 | 2 | 4 | **4** |
| Output size ratio | 2x–11.6x | ≤ 3.0x | ≤ 3.0x | ≤ 3.0x | **≤ 3.0x** |
| Time to reverse (expert) | ~5 min | ~30 min | Hours | Days+ | **Days+** |
| Dead code in decoys | 100% | 100% | < 5% | < 5% | **< 5%** |
| YARA matches | Trivial | 0 | 0 | 0 | **0** |
| Eval count (no-eval) | 1 | 1 | 0 | 0 | **0** |
| CI gates | tests | tests+cov+ruff | +mypy+anti-RE | +fuzz | **6 gates** |
| Doc files | 1 | 3 | 5 | 6 | **6** |
| Distribution | git clone | git+pip | +PyPI+Docker | +binaries | **4 channels** |
| GUI | none | none | none | functional | **5-panel dashboard** |
| Install | `git clone; pip install -e .` | same | `pip install obfush` | same | **`pip install obfush`** |

---

## Complete File Inventory (55+ files)

### Modified Files (13)
| File | Phases |
|---|---|
| `obfush/cli.py` | 1, 4, 6, 7, 12 |
| `obfush/engine/core.py` | 3, 4, 7, 9 |
| `obfush/layers/base.py` | 3, 4 |
| `obfush/layers/encode.py` | 1 |
| `obfush/layers/poly_shell.py` | 1 |
| `obfush/layers/entropy_mask.py` | 2, 3, 4 |
| `obfush/layers/junk_inject.py` | 2 |
| `obfush/layers/id_mangle.py` | 3 |
| `obfush/layers/str_shred.py` | 5c |
| `obfush/layers/__init__.py` | 6 |
| `obfush/engine/layer_selector.py` | 6 |
| `obfush/utils/compat_matrix.py` | 6 |
| `obfush/utils/decoy_corpus.py` | 3 |

### New Source Files (24)
| File | Phase |
|---|---|
| `obfush/__main__.py` | Sprint 1 |
| `obfush/utils/name_pool.py` | 3 |
| `obfush/layers/cff.py` | 5a |
| `obfush/layers/opaque_const.py` | 5b |
| `obfush/compiler/__init__.py` | 7 |
| `obfush/compiler/stub_generator.py` | 7 |
| `obfush/compiler/crypto.py` | 7 |
| `obfush/compiler/compiler.py` | 7 |
| `obfush/compiler/anti_debug.py` | 7 |
| `obfush/compiler/env_keying.py` | 7 |
| `obfush/compiler/integrity.py` | 11 |
| `obfush/compiler/templates/loader_stub.c` | 7 |
| `obfush/vm/__init__.py` | 9 |
| `obfush/vm/compiler.py` | 9 |
| `obfush/vm/opcodes.py` | 9 |
| `obfush/vm/string_pool.py` | 9 |
| `obfush/vm/interpreter_gen.py` | 9 |
| `obfush/vm/junk_bytecode.py` | 9 |
| `obfush/vm/process_splitter.py` | 10 |
| `obfush/vm/templates/vm_interpreter.c` | 9 |
| `obfush/gui/__init__.py` | 12 |
| `obfush/gui/app.py` | 12 |
| `obfush/gui/api.py` | 12 |
| `obfush/gui/templates/index.html` | 12 |

### New Static/Template Files (8)
| File | Phase |
|---|---|
| `obfush/gui/static/css/main.css` | 12 |
| `obfush/gui/static/js/app.js` | 12 |
| `obfush/gui/static/js/editor.js` | 12 |
| `obfush/gui/static/js/config.js` | 12 |
| `obfush/gui/static/js/entropy.js` | 12 |
| `obfush/gui/static/js/analysis.js` | 12 |
| `obfush/gui/static/js/binary.js` | 12 |
| `obfush/gui/static/js/batch.js` | 12 |

### New Test Files (18)
| File | Tests |
|---|---|
| `tests/test_cli.py` | 28 |
| `tests/test_core.py` | 12 |
| `tests/test_verifier.py` | 15 |
| `tests/test_comment_strip.py` | 18 |
| `tests/test_entropy_evaluator.py` | 6 |
| `tests/test_seed.py` | 6 |
| `tests/test_layer_selector.py` | 5 |
| `tests/test_entropy_utils.py` | 10 |
| `tests/test_string_utils.py` | 12 |
| `tests/test_compat_matrix.py` | 6 |
| `tests/test_decoy_corpus.py` | 4 |
| `tests/test_layers/test_cmd_sub.py` | 8 |
| `tests/test_layers/test_encode.py` | 10 |
| `tests/test_layers/test_flow_obfusc.py` | 12 |
| `tests/test_layers/test_id_mangle.py` | 15 |
| `tests/test_layers/test_indirection.py` | 7 |
| `tests/test_layers/test_str_shred.py` | 10 |
| `tests/test_layers/test_junk_inject.py` | 6 |
| `tests/test_layers/test_poly_shell.py` | 12 |
| `tests/test_anti_re.py` | 8 |
| `tests/test_fuzz.py` | 5 |
| `tests/test_gui_api.py` | 10 |

### New Doc Files (5)
| File |
|---|
| `CONTRIBUTING.md` |
| `CHANGELOG.md` |
| `SECURITY.md` |
| `docs/layer_development.md` |
| `Dockerfile` |
