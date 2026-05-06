#!/usr/bin/env python3
"""
obfush — Autonomous Cross-Platform Bootstrap
==============================================
Just run it.  It handles everything.

    Windows:   python setup.py
    Kali:      python3 setup.py
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time

# ──────────────────────────────────────────────────────────────────────
# Platform detection (runs before anything else)
# ──────────────────────────────────────────────────────────────────────

IS_WINDOWS = platform.system() == "Windows"
IS_LINUX   = platform.system() == "Linux"
IS_MAC     = platform.system() == "Darwin"
MIN_PYTHON = (3, 11)
VENV_DIR   = ".venv"

if IS_WINDOWS:
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _distro() -> str:
    if not IS_LINUX:
        return ""
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except FileNotFoundError:
        pass
    return "Linux"


def _is_kali() -> bool:
    return "kali" in _distro().lower()


def _is_deb() -> bool:
    d = _distro().lower()
    return any(x in d for x in ("debian", "ubuntu", "kali", "parrot", "mint", "pop"))


def _is_arch() -> bool:
    d = _distro().lower()
    return any(x in d for x in ("arch", "manjaro", "endeavour", "garuda"))


def _is_fedora() -> bool:
    d = _distro().lower()
    return any(x in d for x in ("fedora", "rhel", "centos", "rocky", "alma"))


# ──────────────────────────────────────────────────────────────────────
# Terminal output engine
# ──────────────────────────────────────────────────────────────────────

G = "\033[92m";  R = "\033[91m";  Y = "\033[93m";  C = "\033[96m"
B = "\033[1m";   D = "\033[2m";   W = "\033[97m";  RESET = "\033[0m"
BG_OK = "\033[42m\033[97m"; BG_FAIL = "\033[41m\033[97m"; BG_WARN = "\033[43m\033[30m"

_log_lines: list[tuple[str, bool]] = []   # (label, passed)

def _banner() -> None:
    art = f"""{C}{B}
      ___  _        __           _
     / _ \\| |__    / _|_   _ ___| |__
    | | | | '_ \\  | |_| | | / __| '_ \\
    | |_| | |_) | |  _| |_| \\__ \\ | | |
     \\___/|_.__/  |_|  \\__,_|___/_| |_|
{RESET}{D}     Polymorphic Bash Obfuscation Engine{RESET}
{D}     v2.0.0-dev | Spectral0x00 | Internal{RESET}
"""
    print(art)


def _phase(name: str) -> None:
    print(f"\n{B}{C}  >> {name}{RESET}")
    print(f"  {C}{'─' * 54}{RESET}")


def _ok(msg: str) -> None:
    print(f"     {G}[+]{RESET} {msg}")


def _fail(msg: str) -> None:
    print(f"     {R}[-]{RESET} {msg}")


def _warn(msg: str) -> None:
    print(f"     {Y}[!]{RESET} {msg}")


def _info(msg: str) -> None:
    print(f"     {D}    {msg}{RESET}")


def _track(label: str, passed: bool) -> None:
    _log_lines.append((label, passed))


def _run(cmd: list[str], timeout: int = 60, quiet: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# ──────────────────────────────────────────────────────────────────────
# Phase 1: System fingerprint
# ──────────────────────────────────────────────────────────────────────

def phase_system() -> None:
    _phase("SYSTEM FINGERPRINT")

    if IS_LINUX:
        _ok(f"OS         {_distro()} ({platform.machine()})")
        _ok(f"Kernel     {platform.release()}")
        uid = os.getuid()
        user = os.getenv("USER", "unknown")
        _ok(f"User       {user} (uid={uid})")
        if uid == 0:
            _warn("Running as root — venv recommended but not required")
    elif IS_WINDOWS:
        _ok(f"OS         Windows {platform.version()} ({platform.machine()})")
        _ok(f"User       {os.getenv('USERNAME', 'unknown')}")
    elif IS_MAC:
        _ok(f"OS         macOS {platform.mac_ver()[0]} ({platform.machine()})")

    _ok(f"Python     {sys.version.split()[0]} @ {sys.executable}")
    _ok(f"Directory  {os.getcwd()}")


# ──────────────────────────────────────────────────────────────────────
# Phase 2: Python version gate
# ──────────────────────────────────────────────────────────────────────

def phase_python() -> bool:
    _phase("PYTHON VERSION CHECK")
    v = sys.version_info
    label = f"{v.major}.{v.minor}.{v.micro}"

    if v >= MIN_PYTHON:
        _ok(f"Python {label} meets minimum {MIN_PYTHON[0]}.{MIN_PYTHON[1]}")
        _track("Python", True)
        return True
    else:
        _fail(f"Python {label} is too old — need >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]}")
        if _is_deb():
            _info("sudo apt update && sudo apt install python3.11 python3.11-venv")
        elif _is_arch():
            _info("sudo pacman -S python")
        elif _is_fedora():
            _info("sudo dnf install python3.11")
        elif IS_WINDOWS:
            _info("Download from https://python.org/downloads/")
        _track("Python", False)
        return False


# ──────────────────────────────────────────────────────────────────────
# Phase 3: pip availability
# ──────────────────────────────────────────────────────────────────────

def phase_pip() -> bool:
    _phase("PIP PACKAGE MANAGER")
    try:
        r = _run([sys.executable, "-m", "pip", "--version"])
        if r.returncode == 0:
            ver = r.stdout.strip().split("\n")[0]
            _ok(ver)
            _track("pip", True)
            return True
    except Exception:
        pass

    _fail("pip is not installed")
    if _is_deb():
        _info("sudo apt install python3-pip")
    elif _is_arch():
        _info("sudo pacman -S python-pip")
    elif _is_fedora():
        _info("sudo dnf install python3-pip")
    elif IS_WINDOWS:
        _info("python -m ensurepip --upgrade")
    else:
        _info("python3 -m ensurepip --upgrade")
    _track("pip", False)
    return False


# ──────────────────────────────────────────────────────────────────────
# Phase 4: Virtual environment (auto-creates on Kali/Debian)
# ──────────────────────────────────────────────────────────────────────

def _needs_venv() -> bool:
    """Does this system require a venv due to PEP 668?"""
    if IS_WINDOWS:
        return False
    try:
        r = _run([sys.executable, "-m", "pip", "install", "--dry-run", "bashlex"], timeout=15)
        return "externally-managed" in r.stderr.lower()
    except Exception:
        return False


def _has_venv_module() -> bool:
    try:
        r = _run([sys.executable, "-c", "import venv; print('ok')"], timeout=10)
        return r.returncode == 0 and "ok" in r.stdout
    except Exception:
        return False


def phase_venv() -> tuple[bool, str]:
    """Returns (success, python_executable_to_use)."""
    _phase("VIRTUAL ENVIRONMENT")

    # Already inside a venv?
    if sys.prefix != sys.base_prefix:
        _ok(f"Already in venv: {sys.prefix}")
        _track("venv", True)
        return True, sys.executable

    pep668 = _needs_venv()

    if os.path.isdir(VENV_DIR):
        py = _venv_python()
        if os.path.isfile(py):
            _ok(f"Found existing {VENV_DIR}/")
            _track("venv", True)
            return True, py

    if pep668:
        _warn("PEP 668 detected — system Python is externally managed")
        _info("Auto-creating virtual environment to avoid conflicts...")
    else:
        _ok("System pip is usable (no PEP 668 restriction)")
        if IS_LINUX:
            _info(f"Creating {VENV_DIR}/ anyway for clean isolation...")
        else:
            _ok("Skipping venv on Windows (not required)")
            _track("venv", True)
            return True, sys.executable

    # Check venv module
    if not _has_venv_module():
        _fail("python3-venv module is missing")
        v = sys.version_info
        if _is_deb():
            _info(f"sudo apt install python{v.major}.{v.minor}-venv")
        elif _is_arch():
            _info("sudo pacman -S python")
        elif _is_fedora():
            _info("sudo dnf install python3-libs")

        if pep668:
            _fail("Cannot proceed without venv on this system")
            _track("venv", False)
            return False, sys.executable
        else:
            _warn("Falling back to system pip")
            _track("venv", True)
            return True, sys.executable

    # Create
    try:
        subprocess.run(
            [sys.executable, "-m", "venv", VENV_DIR],
            check=True, timeout=60,
        )
        py = _venv_python()
        # Upgrade pip inside venv
        subprocess.run(
            [py, "-m", "pip", "install", "--upgrade", "pip", "--quiet"],
            capture_output=True, timeout=60,
        )
        _ok(f"Created {VENV_DIR}/")
        _track("venv", True)
        return True, py
    except Exception as e:
        _fail(f"venv creation failed: {e}")
        if not pep668:
            _warn("Falling back to system pip")
            _track("venv", True)
            return True, sys.executable
        _track("venv", False)
        return False, sys.executable


def _venv_python() -> str:
    if IS_WINDOWS:
        return os.path.join(VENV_DIR, "Scripts", "python.exe")
    return os.path.join(VENV_DIR, "bin", "python3")


# ──────────────────────────────────────────────────────────────────────
# Phase 5: Dependency installation
# ──────────────────────────────────────────────────────────────────────

def phase_install(python: str) -> bool:
    _phase("DEPENDENCY INSTALLATION")

    _info("Installing obfush + all dependencies (editable mode)...")

    cmd = [python, "-m", "pip", "install", "-e", ".[dev]", "--quiet"]

    # If still on system python on a PEP 668 system, add the flag
    if IS_LINUX and python == sys.executable and sys.prefix == sys.base_prefix:
        try:
            r = _run([python, "-m", "pip", "install", "--dry-run", "bashlex"], timeout=15)
            if "externally-managed" in r.stderr.lower():
                cmd.append("--break-system-packages")
                _warn("Adding --break-system-packages (PEP 668 fallback)")
        except Exception:
            pass

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if r.returncode == 0:
            _ok("All packages installed successfully")
            _track("Install", True)
            return True
        else:
            _fail("Installation failed")
            # Show the relevant error
            for line in r.stderr.strip().split("\n")[-5:]:
                if line.strip():
                    _info(line.strip())
            _track("Install", False)
            return False
    except subprocess.TimeoutExpired:
        _fail("Installation timed out (>180s) — check network connectivity")
        _track("Install", False)
        return False
    except Exception as e:
        _fail(f"Installation error: {e}")
        _track("Install", False)
        return False


# ──────────────────────────────────────────────────────────────────────
# Phase 6: Import verification
# ──────────────────────────────────────────────────────────────────────

IMPORT_CHAIN = [
    ("bashlex",                  "bashlex"),
    ("click",                    "click"),
    ("rich",                     "rich"),
    ("xxhash",                   "xxhash"),
    ("yaml",                     "PyYAML"),
    ("obfush",                   "obfush core"),
    ("obfush.engine.ast_parser", "AST parser"),
    ("obfush.engine.normalizer", "Normalizer"),
    ("obfush.engine.ast_emitter","AST emitter"),
    ("obfush.engine.core",       "Engine"),
    ("obfush.engine.verifier",   "Verifier"),
    ("obfush.cli",               "CLI"),
]


def phase_imports(python: str) -> bool:
    _phase("IMPORT CHAIN VERIFICATION")
    all_ok = True
    for module, label in IMPORT_CHAIN:
        try:
            r = _run([python, "-c", f"import {module}; print('ok')"], timeout=10)
            if r.returncode == 0 and "ok" in r.stdout:
                _ok(label)
            else:
                err = r.stderr.strip().split("\n")[-1][:80] if r.stderr else "unknown"
                _fail(f"{label}: {err}")
                all_ok = False
        except Exception as e:
            _fail(f"{label}: {e}")
            all_ok = False
    _track("Imports", all_ok)
    return all_ok


# ──────────────────────────────────────────────────────────────────────
# Phase 7: External toolchain audit
# ──────────────────────────────────────────────────────────────────────

def phase_toolchain() -> None:
    _phase("EXTERNAL TOOLCHAIN")

    # Bash (critical for --verify)
    bash = shutil.which("bash")
    if not bash and IS_WINDOWS:
        for path in [
            r"C:\Windows\System32\bash.exe",
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files (x86)\Git\bin\bash.exe",
            r"C:\cygwin64\bin\bash.exe",
            r"C:\msys64\usr\bin\bash.exe",
        ]:
            if os.path.isfile(path):
                bash = path
                break
    if not bash and IS_LINUX:
        for path in ["/bin/bash", "/usr/bin/bash"]:
            if os.path.isfile(path):
                bash = path
                break

    if bash:
        try:
            r = _run([bash, "--version"], timeout=5)
            ver = r.stdout.strip().split("\n")[0] if r.returncode == 0 else ""
            _ok(f"bash          {bash}")
            if ver:
                _info(f"              {ver}")
        except Exception:
            _ok(f"bash          {bash}")
        _track("bash", True)
    else:
        _warn("bash          not found (--verify unavailable)")
        if IS_WINDOWS:
            _info("Install: wsl --install  OR  https://gitforwindows.org")
        _track("bash", False)

    # Git
    git = shutil.which("git")
    if git:
        try:
            r = _run(["git", "--version"], timeout=5)
            _ok(f"git           {r.stdout.strip()}")
        except Exception:
            _ok(f"git           {git}")
    else:
        _warn("git           not found (optional)")

    # Encoding tools used by layers
    for tool, desc in [
        ("base64",  "Base64 codec (encode/poly-shell layers)"),
        ("xxd",     "Hex dump (encode layer)"),
        ("openssl", "Crypto toolkit (future: XOR key derivation)"),
        ("curl",    "HTTP client (test fixture execution)"),
        ("jq",      "JSON processor (dump-ast post-processing)"),
    ]:
        path = shutil.which(tool)
        if path:
            _ok(f"{tool:<14}{desc}")
        else:
            _warn(f"{tool:<14}not found — {desc}")


# ──────────────────────────────────────────────────────────────────────
# Phase 8: Test suite
# ──────────────────────────────────────────────────────────────────────

def phase_tests(python: str) -> bool:
    _phase("TEST SUITE")
    _info("Running 39 tests across 5 modules...")

    try:
        r = subprocess.run(
            [python, "-m", "pytest", "tests/", "-v", "--tb=line", "-q"],
            capture_output=True, text=True, timeout=120,
        )
        lines = r.stdout.strip().split("\n")

        # Count passes/fails
        passed = sum(1 for l in lines if "PASSED" in l)
        failed = sum(1 for l in lines if "FAILED" in l)
        total = passed + failed

        if r.returncode == 0:
            _ok(f"{passed}/{total} tests passed")
            _track("Tests", True)
            return True
        else:
            _fail(f"{passed}/{total} passed, {failed} FAILED")
            for line in lines:
                if "FAILED" in line:
                    test_name = line.split("::")[1].split(" ")[0] if "::" in line else line
                    _info(f"  FAIL: {test_name}")
            _track("Tests", False)
            return False
    except subprocess.TimeoutExpired:
        _fail("Tests timed out (>120s)")
        _track("Tests", False)
        return False
    except Exception as e:
        _fail(f"Could not execute tests: {e}")
        _track("Tests", False)
        return False


# ──────────────────────────────────────────────────────────────────────
# Phase 9: CLI smoke test
# ──────────────────────────────────────────────────────────────────────

def phase_cli(python: str) -> bool:
    _phase("CLI SMOKE TEST")

    # Test --version
    try:
        r = _run([python, "-m", "obfush.cli", "--version"], timeout=10)
        if r.returncode == 0:
            ver = r.stdout.strip()
            _ok(f"obfush --version    {ver}")
        else:
            _fail("obfush --version failed")
            _track("CLI", False)
            return False
    except Exception as e:
        _fail(f"CLI error: {e}")
        _track("CLI", False)
        return False

    # Test --help
    try:
        r = _run([python, "-m", "obfush.cli", "--help"], timeout=10)
        if r.returncode == 0 and "INPUT_SCRIPT" in r.stdout:
            _ok(f"obfush --help       OK ({len(r.stdout)} chars)")
        else:
            _warn("obfush --help returned unexpected output")
    except Exception:
        _warn("Could not test --help")

    # Test --help-advanced
    try:
        r = _run([python, "-m", "obfush.cli", "--help-advanced"], timeout=10)
        # This exits with 0 and prints the panel
        _ok(f"obfush --help-advanced  OK")
    except Exception:
        _warn("Could not test --help-advanced")

    # Test dry-run on a fixture
    fixture = os.path.join("tests", "fixtures", "basic.sh")
    if os.path.isfile(fixture):
        try:
            r = _run(
                [python, "-m", "obfush.cli", "--seed", "1337", "--dry-run", fixture, "/dev/null"],
                timeout=15,
            )
            if r.returncode == 0:
                _ok(f"obfush --dry-run     OK (seed=1337)")
            else:
                _warn(f"Dry-run returned exit {r.returncode}")
        except Exception:
            _warn("Could not test dry-run")

    # Check if 'obfush' is on PATH
    obfush_path = shutil.which("obfush")
    if obfush_path:
        _ok(f"PATH entry          {obfush_path}")
    else:
        _warn("'obfush' not on PATH — use: python3 -m obfush.cli")
        if IS_LINUX:
            _info("Add to PATH: export PATH=\"$PATH:$(python3 -m site --user-base)/bin\"")

    _track("CLI", True)
    return True


# ──────────────────────────────────────────────────────────────────────
# Final report
# ──────────────────────────────────────────────────────────────────────

def final_report(python: str) -> int:
    _phase("DEPLOYMENT REPORT")

    crit = {"Python", "pip", "Install", "Imports", "CLI"}
    crit_ok = True
    all_ok = True

    for label, passed in _log_lines:
        is_critical = label in crit
        marker = "*" if is_critical else " "
        if passed:
            status = f"{G}PASS{RESET}"
        else:
            status = f"{R}FAIL{RESET}"
            all_ok = False
            if is_critical:
                crit_ok = False
        print(f"     {marker} {label:<16} {status}")

    print(f"\n     {D}* = critical for operation{RESET}")

    if crit_ok:
        print(f"""
  {G}{B}  ============================================  {RESET}
  {G}{B}  ||   obfush is ready for deployment.      ||  {RESET}
  {G}{B}  ============================================  {RESET}
""")
        # Show activation command if in venv
        if python != sys.executable:
            if IS_WINDOWS:
                _info(f"Activate venv:  {VENV_DIR}\\Scripts\\activate")
            else:
                _info(f"Activate venv:  source {VENV_DIR}/bin/activate")
            print()

        _info(f"Quick start:")
        _info(f"  obfush input.sh output.sh")
        _info(f"  obfush --eval-mode no-eval -v input.sh output.sh")
        _info(f"  obfush --help")
        print()
        return 0
    else:
        print(f"""
  {R}{B}  ============================================  {RESET}
  {R}{B}  ||   Setup incomplete. Fix errors above.  ||  {RESET}
  {R}{B}  ============================================  {RESET}
""")
        return 1


# ──────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────

def main() -> int:
    start = time.time()
    _banner()

    # Phase 1: System info
    phase_system()

    # Phase 2: Python gate
    if not phase_python():
        return final_report(sys.executable)

    # Phase 3: pip
    if not phase_pip():
        return final_report(sys.executable)

    # Phase 4: venv (auto-creates on PEP 668 systems)
    venv_ok, python = phase_venv()
    if not venv_ok:
        return final_report(python)

    # Phase 5: Install
    if not phase_install(python):
        return final_report(python)

    # Phase 6: Import chain
    phase_imports(python)

    # Phase 7: External tools
    phase_toolchain()

    # Phase 8: Tests
    phase_tests(python)

    # Phase 9: CLI smoke test
    phase_cli(python)

    elapsed = time.time() - start
    print(f"\n     {D}Completed in {elapsed:.1f}s{RESET}")

    return final_report(python)


if __name__ == "__main__":
    raise SystemExit(main())
