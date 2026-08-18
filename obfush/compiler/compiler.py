"""Linux C toolchain detection and binary build orchestration."""

from __future__ import annotations

import hashlib
import os
import random
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from obfush.compiler.crypto import encrypt_payload
from obfush.compiler.env_keying import derive_environment_tag
from obfush.compiler.stub_generator import generate_stub


class CompilerError(RuntimeError):
    """Raised when binary output cannot be generated safely."""


@dataclass(frozen=True)
class _CompileAttempt:
    succeeded: bool
    stderr: str


@dataclass(frozen=True)
class CompilerCapability:
    backend: str
    compiler: str
    target: str
    static_supported: bool


@dataclass(frozen=True)
class BinaryBuildResult:
    output_path: str
    output_bytes: int
    sha256: str
    compiler: str
    backend: str
    target: str
    static_linked: bool
    key_size: int
    anti_debug_checks: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def detect_compiler() -> CompilerCapability:
    """Detect native Linux or WSL GCC-compatible toolchains."""
    for executable in ("musl-gcc", "gcc", "clang", "cc"):
        path = shutil.which(executable)
        if path and os.name != "nt":
            return CompilerCapability("native", path, "linux", executable == "musl-gcc")

    if os.name == "nt" and shutil.which("bash"):
        probe = subprocess.run(
            ["bash", "-lc", "command -v musl-gcc || command -v gcc || command -v clang || command -v cc"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        compiler = probe.stdout.strip().splitlines()
        if probe.returncode == 0 and compiler:
            selected = compiler[-1]
            return CompilerCapability("wsl", selected, "linux-x86_64", "musl-gcc" in selected)
    raise CompilerError("No supported Linux C compiler found (musl-gcc, gcc, clang, or cc)")


def build_binary(
    payload: str,
    output_path: str,
    *,
    seed: int,
    anti_debug: bool = True,
    environment_key: str | None = None,
    integrity: bool = False,
) -> BinaryBuildResult:
    """Encrypt payload, generate a C stub, and atomically install an ELF binary.

    ``integrity`` is intentionally reserved for a future signed-build format.
    A self-hash embedded in the same mutable binary is not a meaningful trust
    boundary, so this implementation rejects the option rather than implying
    tamper resistance it cannot provide.
    """
    if integrity:
        raise CompilerError(
            "self-integrity is not available: use an external signature or checksum"
        )
    capability = detect_compiler()
    rng = random.Random(seed ^ 0x434F4D50494C4552)
    key_size = rng.randint(16, 64)
    encrypted = encrypt_payload(payload.encode("utf-8"), rng, key_size)
    environment_tag = derive_environment_tag(environment_key) if environment_key else None
    stub = generate_stub(
        encrypted,
        rng,
        anti_debug=anti_debug,
        environment_tag=environment_tag,
    )

    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="obfush-build-") as temporary:
        source_path = Path(temporary) / "loader.c"
        binary_path = Path(temporary) / "loader"
        source_path.write_text(stub.source, encoding="utf-8", newline="\n")
        static_linked = _compile(capability, source_path, binary_path)
        if not binary_path.is_file() or binary_path.stat().st_size == 0:
            raise CompilerError("Compiler reported success without producing an artifact")
        temporary_output = destination.with_name(f".{destination.name}.tmp-{os.getpid()}")
        shutil.copyfile(binary_path, temporary_output)
        os.replace(temporary_output, destination)
        if os.name != "nt":
            destination.chmod(0o755)

    data = destination.read_bytes()
    return BinaryBuildResult(
        output_path=str(destination),
        output_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        compiler=capability.compiler,
        backend=capability.backend,
        target=capability.target,
        static_linked=static_linked,
        key_size=stub.key_size,
        anti_debug_checks=stub.anti_debug_checks,
    )


def _compile(capability: CompilerCapability, source: Path, output: Path) -> bool:
    common = ["-O2", "-s", "-fPIE", "-pie", "-Wl,-z,relro,-z,now"]
    static_flags = [*common, "-static"]
    if capability.backend == "native":
        static = _run_compile([capability.compiler, *static_flags, str(source), "-o", str(output)])
        if static.succeeded:
            return True
        dynamic = _run_compile([capability.compiler, *common, str(source), "-o", str(output)])
        if not dynamic.succeeded:
            raise CompilerError(
                f"C compiler failed for static and dynamic builds: {dynamic.stderr or static.stderr}"
            )
        return False

    source_linux = _wsl_path(source)
    output_linux = _wsl_path(output)
    wsl = shutil.which("wsl.exe") or shutil.which("wsl")
    if not wsl:
        raise CompilerError("WSL compiler detected but wsl.exe is unavailable")
    static = _run_compile([
        wsl, "--exec", capability.compiler,
        *static_flags, source_linux, "-o", output_linux,
    ])
    if static.succeeded:
        return True
    dynamic = _run_compile([
        wsl, "--exec", capability.compiler,
        *common, source_linux, "-o", output_linux,
    ])
    if not dynamic.succeeded:
        raise CompilerError(
            f"WSL C compiler failed for static and dynamic builds: "
            f"{dynamic.stderr or static.stderr}"
        )
    return False


def _run_compile(command: list[str]) -> _CompileAttempt:
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    return _CompileAttempt(result.returncode == 0, result.stderr.strip())


def _wsl_path(path: Path) -> str:
    wsl = shutil.which("wsl.exe") or shutil.which("wsl")
    if not wsl:
        raise CompilerError("wsl.exe is unavailable")
    result = subprocess.run(
        [wsl, "--exec", "wslpath", "-a", str(path)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise CompilerError(f"Could not translate path for WSL: {path}")
    return result.stdout.strip()
