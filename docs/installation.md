# Installation

## Distribution Status

`obfush` is proprietary internal software. Source and built artifacts may be provided only through channels authorized by the copyright holder and the receiving organization. The repository contains build recipes, but no public package index, container registry, release destination, or automated external publication is configured.

Obtain a reviewed source checkout or an internally supplied artifact and verify its provenance and checksum before installation.

## Source Installation

Python 3.11 or newer is required. Bash is required to execute generated scripts and to use equivalence verification. In a virtual environment:

```console
python -m venv .venv
```

Activate the environment using the command appropriate to the operating system, then install from the authorized checkout:

```console
python -m pip install .
obfush --version
```

For repository development:

```console
python -m pip install -e ".[dev]"
python -m pytest tests
```

Binary output additionally needs a Linux `musl-gcc`, GCC, Clang, or compatible `cc`. On Windows, the implementation can use a supported compiler through WSL. Binary output targets Linux and executes `/bin/bash`; it is not a native Windows executable.

## Container

Build locally from an authorized checkout:

```console
docker build -t obfush:local .
docker run --rm obfush:local --version
```

The image entry point is `obfush` and runs as the unprivileged `obfush` user. Stream a script through standard input and output:

```console
docker run --rm -i obfush:local - - --no-config --seed 42 < input.sh > output.sh
```

For mounted files, provide a writable output directory owned or permissioned for the container's non-root user. The default image includes Bash but not a C compiler, so it supports script output and verification but not `--output-mode binary` without a derived internal image.

## Man Page

The checked-in `docs/obfush.1` is generated from plain Click help. Regenerate and verify it after CLI changes:

```console
python scripts/generate_man.py
python -m pytest tests/test_man_generation.py
```

On Unix-like systems, authorized administrators may install it into the local man path, for example `/usr/local/share/man/man1/obfush.1`, according to local packaging policy.

## Optional Local Executable

`obfush.spec` is an optional PyInstaller recipe for an authorized local build. PyInstaller is not a runtime or development dependency of the project, and the repository release workflow does not build or publish this executable. In an isolated build environment:

```console
python -m pip install . pyinstaller
pyinstaller --clean obfush.spec
dist/obfush --version
```

Build on each target operating system, review the bundled dependencies, and distribute the result only through the approved internal process. The PyInstaller CLI executable is distinct from the optional Linux loader produced by `--output-mode binary`.
