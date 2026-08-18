# Contributing

## Access And Scope

This is proprietary internal software, not an open-source contribution program. Contributions are accepted only from people authorized by the copyright holder and the applicable organization. Possession of a checkout does not grant redistribution rights; `LICENSE` controls use and distribution.

Funding and sponsorship details are not configured because no authorized funding handle or program has been designated. That decision is externally pending; do not add funding metadata or payment links without owner approval.

## Development

Use Python 3.11 or newer and isolate development dependencies:

```console
python -m venv .venv
python -m pip install -e ".[dev]"
python -m pytest tests
ruff check obfush tests ci scripts
```

Bash is required for fixture and equivalence checks. Treat every script executed by tests or `--verify` as code execution and use only reviewed benign fixtures in an isolated environment.

Keep changes narrow, deterministic, and compatible with existing architecture. Preserve Bash semantics and add focused regression tests. Layer changes must follow `docs/layer-development.md`, including compatibility-DAG integration. CLI changes must regenerate the manual:

```console
python scripts/generate_man.py
python -m pytest tests/test_man_generation.py
```

## Review

Changes require internal code review. Describe the threat-model impact, compatibility implications, tests run, and any behavior that could execute input or invoke a compiler. Do not include engagement data, payloads, credentials, environment keys, customer identifiers, or operational infrastructure details in commits, fixtures, logs, or workflow artifacts.

Security-sensitive findings follow `SECURITY.md` and must not be placed in public issue trackers or external services. Release preparation follows `docs/release-process.md`; repository workflows build artifacts but do not publish them.
