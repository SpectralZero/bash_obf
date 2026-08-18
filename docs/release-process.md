# Internal Release Process

## Policy

Releases are proprietary internal distributions. The repository does not configure publishing to PyPI, GitHub Releases, a container registry, or any other external service. Both release workflows require `workflow_dispatch`, have read-only repository permissions, use no publication credentials, and retain only GitHub Actions run artifacts for authorized retrieval.

The absence of a deploy step is intentional. Artifact promotion, signing, approval, and transfer into an organizational repository are external operational responsibilities and remain pending until an internal owner and destination are designated.

## Prepare

1. Select a reviewed commit. Confirm the version in package metadata and runtime code agree.
2. Update `CHANGELOG.md` with verified behavior; do not advertise planned or untested features.
3. Regenerate `docs/obfush.1` and require a clean diff after a second generation.
4. Run the test suite and the relevant Bash equivalence matrix in the target Linux environment.
5. Review `LICENSE`, `SECURITY.md`, the threat model, dependencies, and generated artifact contents for proprietary or sensitive data.

## Build Python Artifacts

Run the `Build release artifacts` workflow manually with the reviewed commit or tag in `source_ref`. It runs tests, verifies the generated man page, builds wheel and source distributions, validates their metadata, creates SHA-256 checksums, and uploads an internal workflow artifact bundle. Separate Linux and Windows jobs build and smoke-test standalone PyInstaller CLI artifacts, including the GUI package data.

Equivalent local commands are:

```console
python -m pip install --upgrade build twine ".[dev]"
python -m pytest tests
python scripts/generate_man.py
python -m build
python -m twine check dist/*
```

## Build Container Artifact

Run `Build container artifact` manually. It builds the image, checks the CLI, verifies the runtime UID is non-root, performs a streaming smoke test, exports the image as `obfush-container.tar.gz`, and uploads it as a workflow artifact. It does not log in to or push to a registry.

## Promote Internally

An authorized release owner must retrieve the workflow artifact, verify `SHA256SUMS` through a trusted channel, record the source commit and workflow run, perform any organization-required malware scanning and signing, and transfer it only to an approved internal repository. Do not use `twine upload`, registry push, or public release commands without separate written authorization and reviewed infrastructure changes.

## Rollback

Internal consumers should retain the previous approved artifact and its provenance record. If a defect or security issue is found, revoke access to the affected artifact in the organizational distribution system, notify authorized users through the internal incident process, and issue a newly built version from a corrective commit. Do not replace an artifact while retaining its old checksum or provenance record.
