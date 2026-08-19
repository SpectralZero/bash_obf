"""Side-effect classification for differential test material.

Generated corpus cases are *pure by construction*.  Real-world fixtures may not
be, so they are classified and gated: only ``PURE`` and ``FILE_ONLY`` scripts are
executed by default; ``NETWORKED`` and ``DANGEROUS`` scripts require explicit
opt-in (and, in CI, a disposable container with no network / read-only root).

The heuristic errs on the side of *over*-classifying danger: a false "dangerous"
merely skips a script, whereas a false "pure" could execute a destructive
command on the host.
"""

from __future__ import annotations

import enum
import re


class SideEffect(enum.IntEnum):
    """Ordered by escalating blast radius."""

    PURE = 0        # no external effects; safe to run freely
    FILE_ONLY = 1   # writes only under a sandbox dir it is handed; safe in a tmp cwd
    NETWORKED = 2   # may touch the network; run only against localhost / offline
    DANGEROUS = 3   # may mutate host state irreversibly; disposable container only


# Irreversible / host-mutating commands and privilege escalation.
_DANGEROUS_RE = re.compile(
    r"""(?x)
    (^|[\s;&|(`$])
    (
        rm \s+ (-[^\s]*\s+)* (-[rf]|/|~|\*|\$HOME) |   # recursive/forced/root removal
        rmdir\b | shred\b | mkfs\b | dd\b |
        (:\s*\(\s*\)\s*\{\s*:\|:) |                     # fork-bomb signature
        crontab\b | at\b | systemctl\b | service\b |
        chmod\b | chown\b | chattr\b | mount\b | umount\b |
        iptables\b | nft\b | ufw\b | setenforce\b |
        useradd\b | userdel\b | usermod\b | passwd\b | visudo\b | sudo\b | su\b |
        kill(all)?\b | pkill\b | reboot\b | shutdown\b | halt\b | poweroff\b |
        modprobe\b | insmod\b | rmmod\b | sysctl\b |
        > \s* /(dev|etc|proc|sys|boot|bin|sbin|usr|var|lib)\b   # writing system paths
    )
    """
)

_NETWORK_RE = re.compile(
    r"""(?x)
    (^|[\s;&|(`$])
    (
        curl\b | wget\b | nc\b | ncat\b | netcat\b | ssh\b | scp\b | sftp\b |
        ftp\b | telnet\b | ping\b | dig\b | nslookup\b | host\b |
        /dev/(tcp|udp)/ | openssl\s+s_client\b | python[0-9.]*\s+-m\s+http |
        socat\b | rsync\b .* :: | git\s+(clone|pull|push|fetch)\b
    )
    """
)

# File writes / process launches that are safe only inside a sandbox cwd.
_FILE_RE = re.compile(
    r"""(?x)
    (^|[\s;&|(`$])
    (
        mkdir\b | touch\b | tee\b | cp\b | mv\b | ln\b | truncate\b | install\b |
        mktemp\b | > | >> | tar\b | zip\b | unzip\b | gzip\b | gunzip\b
    )
    """
)


def classify(script: str) -> SideEffect:
    """Best-effort static classification of a script's blast radius."""
    if _DANGEROUS_RE.search(script):
        return SideEffect.DANGEROUS
    if _NETWORK_RE.search(script):
        return SideEffect.NETWORKED
    if _FILE_RE.search(script):
        return SideEffect.FILE_ONLY
    return SideEffect.PURE


# Explicit, curated annotations for the checked-in fixtures.  These override the
# heuristic (which is intentionally conservative and would flag most of them
# DANGEROUS on sight of ``rm``/``curl`` even when they are simulated/no-op).
FIXTURE_CLASSIFICATION: dict[str, SideEffect] = {
    "basic.sh": SideEffect.PURE,
    "functions.sh": SideEffect.PURE,
    "pipelines.sh": SideEffect.FILE_ONLY,
    "comprehensive.sh": SideEffect.FILE_ONLY,
    "full_syntax.sh": SideEffect.FILE_ONLY,
    "demo_test.sh": SideEffect.PURE,
    "fix_validation.sh": SideEffect.FILE_ONLY,
    "fix_verification_test.sh": SideEffect.FILE_ONLY,
    "user_report_test.sh": SideEffect.FILE_ONLY,
    "opaque_blob_recovery.sh": SideEffect.FILE_ONLY,
    "stress_indirection.sh": SideEffect.PURE,
    # Red-team fixtures simulate harmful actions; treat as dangerous → sandbox only.
    "operational.sh": SideEffect.DANGEROUS,
    "real_payload_smoke.sh": SideEffect.DANGEROUS,
    "redteam_full.sh": SideEffect.DANGEROUS,
    "ultimate_stress_test.sh": SideEffect.FILE_ONLY,
}


def is_runnable(cls: SideEffect, *, allow_file: bool = True,
                allow_network: bool = False, allow_dangerous: bool = False) -> bool:
    """Whether a script of class ``cls`` may run under the current policy."""
    if cls == SideEffect.PURE:
        return True
    if cls == SideEffect.FILE_ONLY:
        return allow_file
    if cls == SideEffect.NETWORKED:
        return allow_network
    return allow_dangerous
