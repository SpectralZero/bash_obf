"""Polymorphic Linux anti-debug C fragments for binary output mode."""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class AntiDebugFragment:
    name: str
    source: str


def generate_anti_debug(
    rng: random.Random,
    names: list[str],
    count: int = 3,
) -> list[AntiDebugFragment]:
    """Select deterministic fail-closed checks available on Linux."""
    if len(names) < 5:
        raise ValueError("five function names are required")
    templates = [
        ("tracerpid", _tracer_pid),
        ("parent", _debugger_parent),
        ("preload", _preload),
        ("dumpable", _dumpable),
        ("timing", _timing),
    ]
    selected = rng.sample(list(enumerate(templates)), k=min(count, len(templates)))
    fragments = []
    for index, (label, factory) in selected:
        fragments.append(AntiDebugFragment(label, factory(names[index])))
    rng.shuffle(fragments)
    return fragments


def _tracer_pid(name: str) -> str:
    return f"""static int {name}(void) {{
    FILE *f = fopen("/proc/self/status", "r");
    char line[256];
    if (!f) return 0;
    while (fgets(line, sizeof(line), f)) {{
        if (strncmp(line, "TracerPid:", 10) == 0) {{
            int traced = atoi(line + 10) != 0;
            fclose(f);
            return traced;
        }}
    }}
    fclose(f);
    return 0;
}}"""


def _debugger_parent(name: str) -> str:
    return f"""static int {name}(void) {{
    char path[64], comm[64] = {{0}};
    snprintf(path, sizeof(path), "/proc/%d/comm", getppid());
    FILE *f = fopen(path, "r");
    if (!f) return 0;
    (void)fgets(comm, sizeof(comm), f);
    fclose(f);
    return strstr(comm, "gdb") || strstr(comm, "strace") || strstr(comm, "ltrace");
}}"""


def _preload(name: str) -> str:
    return f"""static int {name}(void) {{
    const char *v = getenv("LD_PRELOAD");
    return v != NULL && *v != '\\0';
}}"""


def _dumpable(name: str) -> str:
    return f"""static int {name}(void) {{
    return prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) == -1;
}}"""


def _timing(name: str) -> str:
    return f"""static int {name}(void) {{
    struct timespec a, b;
    volatile unsigned long x = 0;
    clock_gettime(CLOCK_MONOTONIC, &a);
    for (unsigned long i = 0; i < 1000; ++i) x ^= i;
    clock_gettime(CLOCK_MONOTONIC, &b);
    long ns = (b.tv_sec - a.tv_sec) * 1000000000L + (b.tv_nsec - a.tv_nsec);
    return x == ULONG_MAX || ns > 100000000L;
}}"""
