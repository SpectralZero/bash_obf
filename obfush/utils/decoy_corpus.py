"""
Procedural Decoy Corpus — generates realistic bash comments, log messages,
and inline annotations from combinatorial templates.

The static corpus in entropy_mask.py had ~54 phrases.  An analyst who sees
the same "Verify configuration loaded correctly" across multiple obfuscated
scripts can cluster them.  This generator produces 18,000+ unique combos
from ~80 seed words, making clustering analysis orders of magnitude harder.

All generation uses a seeded RNG so output is deterministic per-seed.
"""

from __future__ import annotations

import random
from typing import Sequence


# ── Template slots ───────────────────────────────────────────────────

ACTIONS: list[str] = [
    "Initialize", "Validate", "Configure", "Rotate", "Flush",
    "Mount", "Verify", "Resolve", "Negotiate", "Bind",
    "Pull", "Execute", "Emit", "Update", "Sample",
    "Enforce", "Sanitize", "Establish", "Check", "Load",
    "Warm", "Notify", "Rollback", "Parse", "Prepare",
    "Restart", "Collect", "Dispatch", "Enumerate", "Provision",
    "Synchronize", "Terminate", "Discover", "Authenticate", "Decrypt",
    "Compress", "Serialize", "Aggregate", "Reconcile", "Replicate",
]

COMPONENTS: list[str] = [
    "connection pool", "SSL certificate", "DNS cache",
    "kernel parameters", "file descriptors", "iptables rules",
    "container image", "database migration", "HMAC signature",
    "API token", "metrics endpoint", "health check",
    "worker processes", "session store", "audit trail",
    "TLS handshake", "MTU settings", "subnet mask",
    "NAT traversal rules", "upstream proxy", "cron schedule",
    "systemd service", "log rotation", "encrypted volume",
    "artifact checksum", "ephemeral port", "CIDR notation",
    "service mesh", "gRPC channel", "load balancer",
    "rate limiter", "circuit breaker", "retry policy",
    "credential vault", "PKI chain", "RBAC policy",
]

CONTEXTS: list[str] = [
    "for high throughput", "before resolution", "if not already present",
    "on connection failure", "within grace period", "against staging endpoint",
    "for audit trail", "after deployment", "during initialization",
    "on startup", "before shutdown", "in production mode",
    "for the worker pool", "across all replicas", "per the API docs",
    "using system defaults", "from the container registry",
    "with backoff enabled", "as per RFC 7231", "on certificate expiry",
    "when cache miss occurs", "for upstream relay",
]

# ── Inline comment prefixes ──────────────────────────────────────────

INLINE_PREFIXES: list[str] = [
    "# TODO:", "# FIXME:", "# NOTE:", "# HACK:",
    "# XXX:", "# REVIEW:", "# OPTIMIZE:",
    "# IMPORTANT:", "# WARNING:", "# REFACTOR:",
]

INLINE_DESCRIPTIONS: list[str] = [
    "add retry logic for transient failures",
    "handle edge case when config is empty",
    "this timeout value is tuned for production",
    "fallback to default if environment variable is unset",
    "skip validation in debug mode",
    "upstream requires Content-Type: application/json",
    "rate limit: 100 req/s per the API docs",
    "see RFC 7231 section 6.5.1 for status code semantics",
    "keep-alive interval must match server configuration",
    "workaround for bash 4.x quoting bug",
    "refactor after migration to systemd-based service",
    "move hardcoded value to environment config",
    "handle SIGTERM gracefully during batch processing",
    "consider using jq for JSON parsing instead of grep",
    "verify TLS certificate pinning is enforced",
    "ensure idempotency for retry scenarios",
    "swap to async I/O when concurrency exceeds threshold",
    "watch for race condition on shared lock file",
    "parameterize this for multi-tenant deployments",
    "profiling shows bottleneck in DNS resolution step",
    "confirm backward compatibility with bash 4.2",
    "add structured logging for observability pipeline",
    "decompose into smaller functions for testability",
    "investigate memory leak in long-running daemon mode",
]

INLINE_METADATA: list[str] = [
    "# Author: auto-generated configuration block",
    "# Last verified: 2024-11-15",
    "# Do not modify — managed by deployment pipeline",
    "# Ref: internal KB article #4821",
    "# Version: 2.1.0-rc3",
    "# Approved by: platform-security team",
    "# Coverage: integration test suite #7",
    "# Upstream: https://internal.example.com/api/v2",
    "# SLA: 99.95% availability target",
    "# Deprecated: migrate to v3 endpoint by Q2",
]

# ── Log levels & messages ────────────────────────────────────────────

LOG_LEVELS: list[str] = ["INFO", "DEBUG", "TRACE", "NOTICE", "WARN"]

LOG_ACTIONS: list[str] = [
    "validated", "initialized", "started", "completed",
    "warmed", "flushed", "rotated", "synchronized",
    "dispatched", "reconciled", "terminated", "provisioned",
]

LOG_SUBJECTS: list[str] = [
    "configuration", "service dependency", "cache", "worker thread",
    "health check endpoint", "metrics collection", "connection pool",
    "TLS session", "database connection", "message queue",
    "scheduler task", "background job", "auth token",
]


class DecoyCorpus:
    """Procedural decoy generator for entropy camouflage.

    Generates unique, realistic-looking bash comments and log messages
    from combinatorial templates.  With 40 actions × 36 components × 22
    contexts = 31,680 possible comment strings.

    All generation uses the provided RNG for deterministic output.
    """

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self._used_comments: set[str] = set()
        self._used_inline: set[str] = set()

    def generate_comment(self) -> str:
        """Generate a realistic noop-comment string.

        Format: "{Action} {component} {context}"
        Example: "Validate SSL certificate before resolution"
        """
        # Try up to 5 times to avoid repeats within the same script
        for _ in range(5):
            action = self.rng.choice(ACTIONS)
            component = self.rng.choice(COMPONENTS)
            context = self.rng.choice(CONTEXTS)
            comment = f"{action} {component} {context}"
            if comment not in self._used_comments:
                self._used_comments.add(comment)
                return comment
        # Fallback: just return whatever we got
        return f"{self.rng.choice(ACTIONS)} {self.rng.choice(COMPONENTS)} {self.rng.choice(CONTEXTS)}"

    def generate_inline_comment(self) -> str:
        """Generate a realistic developer-style inline comment.

        Randomly picks between:
        - Prefixed description: "# TODO: add retry logic for transient failures"
        - Metadata annotation:  "# Last verified: 2024-11-15"
        """
        if self.rng.random() < 0.7:
            prefix = self.rng.choice(INLINE_PREFIXES)
            desc = self.rng.choice(INLINE_DESCRIPTIONS)
            return f"{prefix} {desc}"
        else:
            return self.rng.choice(INLINE_METADATA)

    def generate_log_message(self) -> str:
        """Generate a log-style message.

        Format: "[LEVEL] {subject} {action}"
        Example: "[INFO] Configuration validated"
        """
        level = self.rng.choice(LOG_LEVELS)
        subject = self.rng.choice(LOG_SUBJECTS)
        action = self.rng.choice(LOG_ACTIONS)
        return f"[{level}] {subject} {action}"

    def generate_var_name(self, base: str = "") -> str:
        """Generate a realistic variable name for decoy assignments.

        Uses common sysadmin/devops naming patterns.
        """
        prefixes = [
            "log_rotate", "max_retry", "cache_ttl", "upstream_timeout",
            "worker_pool", "gc_threshold", "buffer_flush", "health_check",
            "metric_prefix", "session_idle", "conn_backlog", "sync_batch",
            "dns_resolve", "tls_verify", "rate_limit", "circuit_break",
            "shard_count", "replica_lag", "heartbeat_ms", "queue_depth",
        ]
        suffix = f"_{self.rng.randint(0x10, 0xff):02x}"
        return self.rng.choice(prefixes) + suffix
