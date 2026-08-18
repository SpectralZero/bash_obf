"""Collision-free identifier generation shared by transformation layers."""

from __future__ import annotations

import random


_ABBREVIATIONS = (
    "rc", "fd", "pid", "sig", "buf", "ptr", "len", "cnt", "idx", "tmp",
    "err", "ret", "val", "key", "msg", "cfg", "opt", "arg", "env", "ctx",
    "srv", "cli", "req", "res", "hdr", "ttl", "ack", "seq", "win", "dst",
    "src", "gid", "uid", "dev", "ino", "epfd", "tfd", "pfd", "rfd", "wfd",
    "st", "ts", "dur", "flg", "bsz", "csz", "rsz", "max", "min", "avg",
    "sum", "cur", "prev", "next", "head", "tail", "lhs", "rhs", "mid",
)


class NamePool:
    """Generate valid Bash identifiers without cross-layer collisions."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self._used: set[str] = set()
        self._counter = 0

    def next_name(self) -> str:
        for _ in range(256):
            strategy = self.rng.randrange(4)
            if strategy == 0:
                name = (
                    f"_{self.rng.choice('abcdefghijklmnopqrstuvwxyz')}"
                    f"{self.rng.randrange(10)}"
                    f"{self.rng.choice('abcdefghijklmnopqrstuvwxyz')}"
                )
            elif strategy == 1:
                suffix = "" if self.rng.random() < 0.5 else str(self.rng.randrange(10))
                name = f"_{self.rng.choice(_ABBREVIATIONS)}{suffix}"
            elif strategy == 2:
                name = f"_{self.rng.choice(_ABBREVIATIONS)}_{self.rng.choice(_ABBREVIATIONS)}"
            else:
                name = f"_{self.rng.choice('vtkrsn')}{self.rng.randrange(100)}"

            if name not in self._used:
                self._used.add(name)
                return name

        while True:
            self._counter += 1
            name = f"_z{self._counter}"
            if name not in self._used:
                self._used.add(name)
                return name

    def register_existing(self, names: set[str]) -> None:
        self._used.update(names)

    def is_registered(self, name: str) -> bool:
        return name in self._used
