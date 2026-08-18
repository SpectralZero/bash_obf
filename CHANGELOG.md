# Changelog

This changelog records shipped or repository-complete behavior. The project is proprietary internal software; entries do not imply public availability or a configured publication channel.

## Unreleased

### Added

- Deterministic `scripts/generate_man.py` generation of `docs/obfush.1` from plain Click help, with a regression test.
- Non-root Docker image exposing the `obfush` CLI.
- Manual-only container and Python release artifact workflows with no external publication or credential steps.
- Internal installation, release, architecture, threat-model, contribution, security, and layer-development guidance.
- Optional PyInstaller specification for authorized local executable builds.

### Policy

- Documented proprietary internal distribution and authorized-use requirements.
- Explicitly deferred all VM bytecode, opcode, interpreter, string-pool, junk-bytecode, and multi-process VM work.
- Recorded funding metadata as externally pending because no approved handle is known.

## 2.0.0-dev

- Development version represented by the current package metadata and runtime version.
- No external release or package publication is asserted by this entry.
