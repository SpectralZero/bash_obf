"""
Layer 12: Anti-Trace — Anti-Debugging & Anti-Analysis Preamble

Injects lightweight detection of common analysis techniques:
  - bash -x (xtrace) detection
  - strace/ltrace/gdb parent process detection
  - script/tee recording detection
  - optional self-delete on exit

This layer runs LAST so the preamble appears at the top of the final output.
"""

from __future__ import annotations

from obfush.layers.base import Layer, LayerConfig, LayerStats


class LayerImpl(Layer):
    name = "anti-trace"
    description = "Anti-debugging & anti-analysis preamble"

    def transform(self, ast: dict, config: LayerConfig) -> tuple[dict, LayerStats]:
        stats = LayerStats()
        rng = config.rng

        # Only inject at intensity >= 0.5
        if config.intensity < 0.5:
            return ast, stats

        preamble_nodes = []

        # 1. Detect bash -x (xtrace): if enabled, exit silently
        xtrace_check = _make_raw_command(
            '[[ "$-" == *x* ]] && exit 1',
        )
        preamble_nodes.append(xtrace_check)
        stats.nodes_modified += 1

        # 2. Detect strace/ltrace/gdb parent process
        if rng.random() < config.intensity:
            parent_var = config.name_pool.next_name() if config.name_pool else "_pp"
            parent_check = _make_raw_command(
                f'{parent_var}=$(cat /proc/$PPID/comm 2>/dev/null); '
                f'[[ "${{{parent_var}}}" == *trace* || '
                f'"${{{parent_var}}}" == *gdb* || '
                f'"${{{parent_var}}}" == *stap* ]] && exit 1',
            )
            preamble_nodes.append(parent_check)
            stats.nodes_modified += 1

        # 3. Detect script/tee recording
        if rng.random() < config.intensity * 0.8:
            script_check = _make_raw_command(
                '[[ -n "$SCRIPT" || -n "$TYPESCRIPT" ]] && exit 1',
            )
            preamble_nodes.append(script_check)
            stats.nodes_modified += 1

        # 4. Disable core dumps (prevent memory analysis)
        if rng.random() < config.intensity * 0.6:
            ulimit_check = _make_raw_command(
                'ulimit -c 0 2>/dev/null',
            )
            preamble_nodes.append(ulimit_check)
            stats.nodes_modified += 1

        # 5. Unset sensitive environment variables
        if rng.random() < config.intensity * 0.7:
            unset_cmd = _make_raw_command(
                'unset HISTFILE HISTSIZE HISTFILESIZE HISTCONTROL 2>/dev/null',
            )
            preamble_nodes.append(unset_cmd)
            stats.nodes_modified += 1

        # Prepend to script body
        if ast.get("type") == "script" and preamble_nodes:
            ast["body"] = preamble_nodes + ast.get("body", [])

        return ast, stats

    def estimate_size_increase(self, config: LayerConfig) -> float:
        return 1.0 + config.intensity * 0.05  # ~200 bytes max


def _make_raw_command(cmd: str) -> dict:
    """Create a raw command node (pre-rendered shell syntax)."""
    return {
        "type": "command",
        "parts": [
            {"type": "word", "value": cmd, "raw": cmd, "pos": None},
        ],
        "pos": None,
        "_anti_trace": True,
    }
