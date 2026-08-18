"""Executable scalability budgets for large scripts and concurrent batches."""

import time

from obfush.batch import process_batch
from obfush.cli import _write_output_atomic
from obfush.engine.core import EngineConfig, PolymorphicEngine
from obfush.layers.flow_obfusc import (
    _LARGE_BODY_THRESHOLD,
    _REORDER_WINDOW_SIZE,
    _reorder_independent_blocks,
)


class _ReverseShuffle:
    @staticmethod
    def shuffle(items):
        items.reverse()


def _assignment(name: str, value: str) -> dict:
    return {"type": "assignment", "name": name, "value": value, "pos": None}


def test_large_reorder_is_bounded_to_fixed_windows():
    body = [_assignment(f"v{index}", str(index)) for index in range(120)]
    reordered = _reorder_independent_blocks(
        body, _ReverseShuffle(), max_group_size=_REORDER_WINDOW_SIZE,
    )
    for offset in range(0, len(body), _REORDER_WINDOW_SIZE):
        expected = {
            node["name"] for node in body[offset:offset + _REORDER_WINDOW_SIZE]
        }
        actual = {
            node["name"] for node in reordered[offset:offset + _REORDER_WINDOW_SIZE]
        }
        assert actual == expected


def test_reorder_preserves_dependencies_and_barriers():
    first = _assignment("value", "one")
    dependent = _assignment("copy", '"${value}"')
    barrier = {
        "type": "command",
        "parts": [{"type": "word", "value": "printf", "pos": None}],
        "pos": None,
    }
    after = _assignment("later", "two")
    reordered = _reorder_independent_blocks(
        [first, dependent, barrier, after], _ReverseShuffle(),
    )
    assert reordered.index(first) < reordered.index(dependent)
    assert reordered.index(dependent) < reordered.index(barrier)
    assert reordered.index(barrier) < reordered.index(after)


def test_thousand_statement_flow_run_completes_under_budget():
    source = "#!/bin/bash\n" + "".join(
        f"v{index}={index}\n" for index in range(1000)
    ) + "printf 'done\\n'\n"
    started = time.perf_counter()
    result = PolymorphicEngine(EngineConfig(
        seed=42,
        intensity=0.8,
        force_layers=["flow-obfusc"],
        min_layers=1,
        max_size_ratio=3.0,
    )).run(source)
    elapsed = time.perf_counter() - started
    assert elapsed < 1.0
    assert result.layer_stats["flow-obfusc"].custom["reorder_window_size"] == 50
    assert result.layer_stats["flow-obfusc"].elapsed_ms < 500
    assert len(source.splitlines()) > _LARGE_BODY_THRESHOLD


def test_ten_file_parallel_batch_completes_under_budget(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    for index in range(10):
        (input_dir / f"script-{index:02d}.sh").write_text(
            f"#!/bin/bash\nvalue={index}\nprintf '%s\\n' \"$value\"\n",
            encoding="utf-8",
        )
    config = EngineConfig(
        seed=42,
        intensity=0.5,
        force_layers=["id-mangle", "str-shred"],
        min_layers=1,
        eval_mode="no-eval",
    )
    started = time.perf_counter()
    results = process_batch(
        input_dir,
        output_dir,
        config,
        workers=4,
        write_output=_write_output_atomic,
    )
    elapsed = time.perf_counter() - started
    assert elapsed < 5.0
    assert all(result.status == "ok" for result in results)
    assert len(list(output_dir.glob("*.sh"))) == 10
