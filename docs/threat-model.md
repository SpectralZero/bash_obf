# Threat Model

## Purpose And Authorization

`obfush` is proprietary tooling for authorized internal red-team operations, defensive research, controlled education, and engagements covered by written authorization. Operators must follow the repository license and the applicable rules of engagement. Obfuscation does not expand authorization.

## Assets

- Bash source text, including proprietary techniques and environment identifiers.
- Generated scripts and optional native loaders.
- Configuration, seeds, test input, logs, and environment-binding values.
- Internal build artifacts and their checksums.

## Intended Adversary

The transformation is intended to increase the cost of casual static inspection, straightforward string matching, and comparison of independently generated artifacts. The adversary may possess a generated artifact and normal static-analysis tools.

The design does not assume secrecy once an adversary can observe execution, instrument Bash, inspect process memory, trace system calls, control the host, replace dependencies or the compiler, or obtain both source and output. A determined analyst can recover behavior from executable code.

## Security Boundaries

- Generated code preserves the input's behavior and privileges; it is not a sandbox.
- `--verify` executes both scripts. Untrusted input can run arbitrary commands and must be tested only inside an operator-provided isolation boundary.
- Binary mode invokes a local compiler and produces a loader that decrypts source in process memory before executing `/bin/bash`.
- Environment binding is an operational guard, not cryptographic identity, authorization, DRM, or tamper resistance.
- Best-effort anti-debug checks are not a security boundary and can be bypassed.
- Seeds provide reproducibility, not confidentiality. Logs and JSON metadata may expose seeds, paths, layer names, and analysis results.
- Containers package the CLI but do not make processing hostile scripts safe. Bind mounts and container permissions remain operator responsibilities.

## Threats And Mitigations

| Threat | Mitigation | Residual risk |
| --- | --- | --- |
| Source comments disclose sensitive context | Comments are stripped before parsing | Sensitive literals and behavior may remain observable |
| A failed transform changes semantics | Structural validation, rollback, size budgets, tests, optional equivalence verification | Bash is complex; testing cannot prove equivalence for every script |
| Generated artifacts are replaced | Internal provenance, review, SHA-256 checksums, restricted artifact access | Checksums are not signatures and must come from a trusted channel |
| Dependency or compiler compromise | Review dependency changes and build in controlled infrastructure | The current metadata specifies ranges rather than a locked dependency set |
| Secrets leak through output or logs | Avoid embedding secrets; restrict generated files and logs | Obfuscation is not encryption and runtime recovery remains possible |
| Tool is used outside authorization | Proprietary license, internal distribution, access control, operator procedures | Technical controls cannot replace governance |

## Non-Goals

The project does not hide system calls, file activity, network activity, child processes, or command effects from `strace`, eBPF, audit systems, EDR, or an administrator. It does not erase logs, manipulate timestamps, establish persistence, bypass endpoint controls, or guarantee source irreversibility.

VM bytecode, opcodes, an interpreter, a VM string pool, junk bytecode, and multi-process VM execution are not present and are explicitly deferred.
