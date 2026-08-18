"""Side-effect-contained live decoy chains for AST transformation layers."""

from __future__ import annotations

import random

from obfush.utils.name_pool import NamePool


class LiveChainGenerator:
    """Build atomic Bash chains in which every synthetic value is consumed."""

    def __init__(
        self,
        rng: random.Random,
        name_pool: NamePool | None = None,
        marker: str = "_decoy",
    ) -> None:
        self.rng = rng
        self.name_pool = name_pool
        self.marker = marker
        self._counter = 0

    def generate(self, seed_text: str | None = None) -> dict:
        """Return one removable compound node containing a complete live chain."""
        if seed_text is not None:
            return self._string_chain(seed_text)
        return self.rng.choice((
            self._arithmetic_chain,
            self._environment_chain,
            self._function_chain,
        ))()

    def generate_function_chain(self) -> dict:
        """Return a live chain that defines and invokes a synthetic function."""
        return self._function_chain()

    def _next_name(self) -> str:
        if self.name_pool is not None:
            return self.name_pool.next_name()
        self._counter += 1
        return f"_v{self._counter}_{self.rng.randrange(0x100, 0x10000):04x}"

    @staticmethod
    def _assignment(name: str, value: str) -> dict:
        return {
            "type": "assignment",
            "name": name,
            "value": value,
            "pos": None,
        }

    def _consume(self, name: str) -> dict:
        """Terminal consumption — vary pattern to prevent fingerprinting."""
        strategy = self.rng.randint(0, 3)
        if strategy == 0:
            # Classic colon consumption
            return {
                "type": "command",
                "parts": [
                    {"type": "word", "value": ":", "pos": None},
                    {"type": "word", "value": f'"${{{name}}}"', "pos": None},
                ],
                "pos": None,
            }
        elif strategy == 1:
            # printf to /dev/null — looks like logging code
            cmd = f'printf \'%s\' "${{{name}}}" > /dev/null'
            return {
                "type": "command",
                "parts": [
                    {"type": "word", "value": cmd, "raw": cmd, "pos": None},
                ],
                "pos": None,
            }
        elif strategy == 2:
            # test -n — looks like validation code
            cmd = f'[[ -n "${{{name}}}" ]] || true'
            return {
                "type": "command",
                "parts": [
                    {"type": "word", "value": cmd, "raw": cmd, "pos": None},
                ],
                "pos": None,
            }
        else:
            # Hash/checksum — looks like integrity checking
            cmd = f'echo "${{{name}}}" | cksum > /dev/null 2>&1'
            return {
                "type": "command",
                "parts": [
                    {"type": "word", "value": cmd, "raw": cmd, "pos": None},
                ],
                "pos": None,
            }

    def _group(
        self,
        parts: list[dict],
        variables: list[str],
        functions: list[str] | None = None,
    ) -> dict:
        """Wrap decoy chain — mix wrapper types to prevent fingerprinting."""
        strategy = self.rng.randint(0, 3)
        base = {
            "pos": None,
            self.marker: True,
            "_live_chain": True,
            "_synthetic_vars": variables,
            "_synthetic_functions": functions or [],
            "_junk": True,
        }

        if strategy == 0:
            # Brace group — looks like a regular code block
            return {"type": "compound", "kind": "{", "parts": parts, **base}
        elif strategy == 1:
            # Subshell — only 25% of the time now (was 100%)
            return {"type": "compound", "kind": "(", "parts": parts, **base}
        elif strategy == 2:
            # If-guarded — wrap all parts in a brace group as then-branch
            predicate = self._simple_opaque_predicate()
            then_body = {"type": "compound", "kind": "{", "parts": parts, "pos": None}
            return {
                "type": "compound", "kind": "if",
                "parts": [predicate, then_body],
                **base,
            }
        else:
            # Bare compound (brace group, alternate style)
            return {"type": "compound", "kind": "{", "parts": parts, **base}

    def _simple_opaque_predicate(self) -> dict:
        """Generate a simple always-true predicate for wrapping decoys."""
        a = self.rng.randint(2, 97)
        b = self.rng.randint(2, 97)
        c = a * b
        pred = f'[[ $(( {a} * {b} )) -eq {c} ]]'
        return {
            "type": "command",
            "parts": [{"type": "word", "value": pred, "pos": None}],
            "pos": None,
            "_no_wrap": True,
        }

    def _string_chain(self, seed_text: str) -> dict:
        first, second, third = (self._next_name() for _ in range(3))
        quoted = "'" + seed_text.replace("'", "'\\''") + "'"
        parts = [
            self._assignment(first, quoted),
            self._assignment(second, f'"${{{first}}}:${{#{first}}}"'),
            self._assignment(third, f'"${{{second}// /_}}"'),
            self._consume(third),
        ]
        return self._group(parts, [first, second, third])

    def _arithmetic_chain(self) -> dict:
        first, second, third = (self._next_name() for _ in range(3))
        initial = self.rng.randrange(11, 997)
        multiplier = self.rng.randrange(2, 13)
        offset = self.rng.randrange(1, 97)
        parts = [
            self._assignment(first, f"$(( {initial} ))"),
            self._assignment(second, f"$(( ${{{first}}} * {multiplier} + {offset} ))"),
            self._assignment(third, f"$(( ${{{second}}} ^ ${{{first}}} ))"),
            self._consume(third),
        ]
        return self._group(parts, [first, second, third])

    def _environment_chain(self) -> dict:
        first, second, third = (self._next_name() for _ in range(3))
        parts = [
            self._assignment(first, '"${HOSTNAME:-localhost}"'),
            self._assignment(second, f'"${{#{first}}}"'),
            self._assignment(third, f'"${{{first}:0:1}}${{{second}}}"'),
            self._consume(third),
        ]
        return self._group(parts, [first, second, third])

    def _function_chain(self) -> dict:
        function = self._next_name()
        first, second = (self._next_name() for _ in range(2))
        function_body = {
            "type": "compound",
            "kind": "{",
            "parts": [
                self._assignment(first, f'"{self.rng.randrange(100, 1000)}"'),
                self._assignment(second, f'"${{{first}}}:ready"'),
                self._consume(second),
            ],
            "pos": None,
        }
        parts = [
            {
                "type": "function_def",
                "name": function,
                "body": function_body,
                "pos": None,
            },
            {
                "type": "command",
                "parts": [{"type": "word", "value": function, "pos": None}],
                "pos": None,
            },
        ]
        return self._group(parts, [first, second], [function])  # type: ignore[arg-type]
