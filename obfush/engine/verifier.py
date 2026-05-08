"""
Equivalence verifier — executes original and obfuscated scripts
and compares their behaviour.

On Windows, uses WSL/Git Bash if available. Full container-based
sandboxing requires a Linux environment.

Normalization is delegated to obfush.engine.normalize (single source
of truth shared with the CI equivalence checker).
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tempfile
from typing import Any

from obfush.engine.normalize import normalize_stdout, normalize_stderr


class VerificationError(Exception):
    """Raised when obfuscated script produces different output."""

    def __init__(self, message: str, diff: dict | None = None) -> None:
        super().__init__(message)
        self.diff = diff


class Verifier:
    """Sandbox equivalence tester.

    Executes original and obfuscated scripts and compares:
    - stdout (after normalization)
    - stderr (after normalization — warnings only, not failures)
    - exit code

    Args:
        timeout: Maximum execution time per script (seconds).
        bash_path: Path to bash executable (auto-detected if None).
        normalize: Whether to normalize output before comparison.
    """

    def __init__(
        self,
        timeout: int = 30,
        bash_path: str | None = None,
        normalize: bool = True,
    ) -> None:
        self.timeout = timeout
        self.bash_path = bash_path or self._find_bash()
        self.normalize = normalize

    def verify(
        self,
        original_source: str,
        obfuscated_source: str,
        test_input: str | None = None,
    ) -> bool:
        """Run both scripts and compare behaviour.

        Args:
            original_source:   Original bash script.
            obfuscated_source: Obfuscated bash script.
            test_input:        Optional stdin to feed both scripts.

        Returns:
            True if behaviour is identical.

        Raises:
            VerificationError: If outputs differ, with diff details.
        """
        if not self.bash_path:
            import warnings
            warnings.warn(
                "No bash found — skipping equivalence verification. "
                "Install WSL, Git Bash, or Cygwin for verification support.",
                RuntimeWarning,
                stacklevel=2,
            )
            return False

        stdin_data = None
        if test_input:
            if os.path.isfile(test_input):
                with open(test_input, "rb") as f:
                    stdin_data = f.read()
            else:
                stdin_data = test_input.encode("utf-8")

        # Run original
        orig_result = self._run_script(original_source, stdin_data)

        # Run obfuscated
        obf_result = self._run_script(obfuscated_source, stdin_data)

        # Optionally normalise
        if self.normalize:
            orig_stdout = normalize_stdout(orig_result["stdout"])
            obf_stdout = normalize_stdout(obf_result["stdout"])
            orig_stderr = normalize_stderr(orig_result["stderr"])
            obf_stderr = normalize_stderr(obf_result["stderr"])
        else:
            orig_stdout = orig_result["stdout"]
            obf_stdout = obf_result["stdout"]
            orig_stderr = orig_result["stderr"]
            obf_stderr = obf_result["stderr"]

        # Compare
        diff: dict[str, Any] = {}
        match = True

        if orig_stdout != obf_stdout:
            diff["stdout"] = {
                "original": orig_stdout[:500].decode("utf-8", errors="replace"),
                "obfuscated": obf_stdout[:500].decode("utf-8", errors="replace"),
            }
            match = False

        if orig_stderr != obf_stderr:
            diff["stderr"] = {
                "original": orig_stderr[:500].decode("utf-8", errors="replace"),
                "obfuscated": obf_stderr[:500].decode("utf-8", errors="replace"),
            }
            # stderr differences are warnings, not failures

        if orig_result["exit_code"] != obf_result["exit_code"]:
            diff["exit_code"] = {
                "original": orig_result["exit_code"],
                "obfuscated": obf_result["exit_code"],
            }
            match = False

        if not match:
            raise VerificationError(
                f"Equivalence check FAILED: {list(diff.keys())}",
                diff=diff,
            )

        return True

    def verify_json(
        self,
        original_source: str,
        obfuscated_source: str,
        test_input: str | None = None,
    ) -> dict:
        """Like verify(), but returns a structured JSON-ready result
        suitable for CI consumption instead of raising.

        Returns:
            dict with keys: passed, stdout_match, exit_code_match,
            stderr_warning, diff (if any)
        """
        try:
            passed = self.verify(original_source, obfuscated_source, test_input)
            return {
                "passed": passed,
                "stdout_match": True,
                "exit_code_match": True,
                "stderr_warning": False,
                "diff": None,
            }
        except VerificationError as e:
            diff = e.diff or {}
            return {
                "passed": False,
                "stdout_match": "stdout" not in diff,
                "exit_code_match": "exit_code" not in diff,
                "stderr_warning": "stderr" in diff,
                "diff": diff,
            }

    def _run_script(
        self,
        source: str,
        stdin_data: bytes | None = None,
    ) -> dict:
        """Execute a bash script and capture output."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False, encoding="utf-8",
        ) as f:
            f.write(source)
            script_path = f.name

        try:
            result = subprocess.run(
                [self.bash_path, script_path],
                input=stdin_data,
                capture_output=True,
                timeout=self.timeout,
                env=self._safe_env(),
            )
            return {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {
                "stdout": b"",
                "stderr": b"TIMEOUT",
                "exit_code": -1,
            }
        except Exception as e:
            return {
                "stdout": b"",
                "stderr": str(e).encode(),
                "exit_code": -2,
            }
        finally:
            try:
                os.unlink(script_path)
            except OSError:
                pass

    def _safe_env(self) -> dict[str, str]:
        """Create a restricted environment for script execution."""
        env = os.environ.copy()
        for key in ("AWS_SECRET_ACCESS_KEY", "API_KEY", "TOKEN",
                     "PASSWORD", "PRIVATE_KEY"):
            env.pop(key, None)
        return env

    @staticmethod
    def _find_bash() -> str | None:
        """Auto-detect bash executable."""
        bash = shutil.which("bash")
        if bash:
            return bash

        if platform.system() == "Windows":
            candidates = [
                r"C:\Windows\System32\bash.exe",           # WSL
                r"C:\Program Files\Git\bin\bash.exe",      # Git Bash
                r"C:\Program Files (x86)\Git\bin\bash.exe",
                r"C:\cygwin64\bin\bash.exe",               # Cygwin
                r"C:\msys64\usr\bin\bash.exe",             # MSYS2
            ]
            for candidate in candidates:
                if os.path.isfile(candidate):
                    return candidate

        return None
