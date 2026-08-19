"""Deterministic edge coverage for non-VM transformation layers."""

from __future__ import annotations

import random
import subprocess

import pytest

import obfush.layers.cff as cff
import obfush.layers.encode as encode
import obfush.layers.flow_obfusc as flow
import obfush.layers.id_mangle as id_mangle
import obfush.layers.opaque_const as opaque_const
from obfush.engine.ast_emitter import emit
from obfush.layers.base import LayerConfig, LayerStats
from obfush.utils.name_pool import NamePool


class ScriptedRandom:
    """Minimal RNG with explicit outputs and stable first-item fallbacks."""

    def __init__(
        self,
        *,
        randoms: tuple[float, ...] = (),
        choices: tuple[object, ...] = (),
        randints: tuple[int, ...] = (),
        randranges: tuple[int, ...] = (),
    ) -> None:
        self.randoms = iter(randoms)
        self.choices = iter(choices)
        self.randints = iter(randints)
        self.randranges = iter(randranges)

    def random(self) -> float:
        return next(self.randoms, 0.0)

    def choice(self, values):
        selected = next(self.choices, None)
        return values[0] if selected is None else selected

    def randint(self, lower: int, upper: int) -> int:
        return next(self.randints, lower)

    def randrange(self, *args: int) -> int:
        return next(self.randranges, 0)

    def shuffle(self, values) -> None:
        values.reverse()

    def sample(self, population, count: int):
        return list(population[:count])


def _config(
    *,
    rng=None,
    intensity: float = 1.0,
    eval_mode: str = "ok",
    name_pool=None,
) -> LayerConfig:
    return LayerConfig(
        intensity=intensity,
        seed=73,
        rng=rng or random.Random(73),
        eval_mode=eval_mode,
        name_pool=name_pool,
    )


def _word(value: str, **extra) -> dict:
    return {"type": "word", "value": value, "pos": None, **extra}


def _assignment(name: str, value: object = "") -> dict:
    return {"type": "assignment", "name": name, "value": value, "pos": None}


def _command(name: str, *args: str, **extra) -> dict:
    return {
        "type": "command",
        "parts": [_word(name), *(_word(arg) for arg in args)],
        "pos": None,
        **extra,
    }


def _run_bash(source: str) -> subprocess.CompletedProcess[bytes]:
    syntax = subprocess.run(
        ["bash", "-n"], input=source.encode(), capture_output=True, timeout=10
    )
    assert syntax.returncode == 0, syntax.stderr.decode(errors="replace")
    return subprocess.run(
        ["bash"], input=source.encode(), capture_output=True, timeout=10
    )


def test_layer_size_estimates_cover_configuration_boundaries():
    low = _config(intensity=0.0)
    high = _config(intensity=1.0)

    assert id_mangle.LayerImpl().estimate_size_increase(low) == 1.1
    assert flow.LayerImpl().estimate_size_increase(low) == 1.4
    assert opaque_const.LayerImpl().estimate_size_increase(high) == 1.35
    assert cff.LayerImpl().estimate_size_increase(high) == 2.0
    assert encode.LayerImpl().estimate_size_increase(high) == 2.5


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (None, False),
        ("", False),
        ("two-words", False),
        ("if", False),
        ("?", False),
        ("echo", False),
        ("grep", False),
        ("PATH", False),
        ("x", True),
    ],
)
def test_id_mangle_name_eligibility_edges(name, expected):
    assert id_mangle._is_mangleable(name) is expected


def test_id_mangle_collects_opaque_declarations_and_both_for_styles():
    raw = """function worker() { :; }
for item in a b; do :; done
for (( index=0; index<1; index++ )); do :; done
declare -A colors
local_value=one
echo "function if() for while in"
"""
    ast = {"type": "script", "body": [_word(raw, raw=raw)]}

    assert id_mangle._collect_identifiers(ast) == {
        "worker",
        "item",
        "index",
        "colors",
        "local_value",
    }


def test_id_mangle_structured_collection_handles_declarations_and_noise():
    ast = {
        "type": "script",
        "body": [
            None,
            _assignment("plain", "$read_only"),
            _assignment("PATH", "/bin"),
            {"type": "function_def", "name": "worker", "body": "not-a-node"},
            {"type": "function_def", "name": "if", "body": []},
            {
                "type": "command",
                "parts": [
                    _word("declare"),
                    _word("-A"),
                    _word("table"),
                    _word("count=2"),
                    _word("PATH=/tmp"),
                    _assignment("nested", "3"),
                ],
            },
        ],
        "test_parts": {"type": "assignment", "name": "from_dict", "value": "4"},
    }

    assert id_mangle._collect_identifiers(ast) == {
        "plain",
        "worker",
        "table",
        "count",
        "nested",
        "from_dict",
    }


def test_id_mangle_pool_selection_and_name_collision_fallbacks():
    assert id_mangle._select_pool(ScriptedRandom(choices=("mixed",)), 0.9) == "mixed"
    assert id_mangle._select_pool(ScriptedRandom(choices=("hex",)), 0.5) == "hex"
    assert id_mangle._select_pool(ScriptedRandom(), 0.49) == "deceptive"

    collision_rng = ScriptedRandom(randints=(11, 11, 12))
    assert id_mangle._generate_hex_name(collision_rng, {"_0x000b"}) == "_0x000c"
    assert id_mangle._generate_deceptive_name(
        ScriptedRandom(), {"used"}, ["used"]
    ).startswith("_0x")
    assert id_mangle._generate_deceptive_name(
        ScriptedRandom(choices=("free",)), {"used"}, ["used", "free"]
    ) == "free"


@pytest.mark.parametrize(
    ("pool", "rng", "prefix"),
    [
        ("hex", ScriptedRandom(randints=(31,)), "_0x"),
        ("deceptive", ScriptedRandom(), ""),
        ("mixed", ScriptedRandom(randoms=(0.0,), randints=(32,)), "_0x"),
        ("mixed", ScriptedRandom(randoms=(1.0,)), ""),
        ("unknown", ScriptedRandom(randints=(33,)), "_0x"),
    ],
)
def test_id_mangle_build_map_covers_every_pool(pool, rng, prefix):
    mapped = id_mangle._build_mangle_map({"source"}, rng, pool)
    assert mapped["source"].startswith(prefix)


def test_id_mangle_applies_all_structured_contexts_and_scope():
    mapping = {"worker": "fn", "item": "it", "table": "tbl", "count": "num"}
    ast = {
        "type": "script",
        "_scope": {
            "globals": {"table", "external"},
            "assignments": {"count"},
            "reads": {"item"},
            "locals": {"worker": {"item", "other"}},
        },
        "body": [
            None,
            _assignment("worker", "worker"),
            _assignment("count", 7),
            {"type": "function_def", "name": "worker", "body": []},
            {"type": "function_def", "name": "other", "body": []},
            _command("worker"),
            {
                "type": "command",
                "parts": [
                    _word("declare"),
                    _word("-A"),
                    _word("table"),
                    _word("count+=2"),
                    _word("other=x"),
                    _assignment("ignored", "x"),
                ],
            },
            _word("", var_refs=[]),
            _word("$[count + 1] ${item}", var_refs=["count", "item", "free"]),
            {"type": "expansion", "kind": "parameter", "value": "item", "var_name": "count"},
        ],
    }

    transformed = id_mangle._apply_mangle_map(ast, mapping)

    assert transformed["body"][1]["name"] == "fn"
    assert transformed["body"][1]["value"] == "fn"
    assert transformed["body"][2]["value"] == 7
    assert transformed["body"][3]["name"] == "fn"
    assert transformed["body"][4]["name"] == "other"
    assert transformed["body"][5]["parts"][0]["value"] == "fn"
    declaration = transformed["body"][6]["parts"]
    assert [part.get("value") for part in declaration[:5]] == [
        "declare",
        "-A",
        "tbl",
        "num+=2",
        "other=x",
    ]
    assert transformed["body"][8]["value"] == "$[num + 1] ${it}"
    assert transformed["body"][8]["var_refs"] == ["num", "it", "free"]
    assert transformed["body"][9]["value"] == "it"
    assert transformed["body"][9]["var_name"] == "num"
    assert transformed["_scope"] == {
        "globals": {"tbl", "external"},
        "assignments": {"num"},
        "reads": {"it"},
        "locals": {"fn": {"it", "other"}},
    }


def test_id_mangle_opaque_contexts_preserve_bash_semantics():
    source = """worker() { printf '%s' "$item"; }
item=ok
for (( count=0; count<1; count++ )); do
worker
done
unset item
[[ -z ${item:-} ]]
"""
    ast = {"type": "script", "body": [_word(source, raw=source)]}
    transformed = id_mangle._apply_mangle_map(
        ast, {"worker": "fn", "item": "it", "count": "num"}
    )
    output = transformed["body"][0]["value"]
    process = _run_bash(output)

    assert process.returncode == 0, process.stderr.decode(errors="replace")
    assert process.stdout == b"ok"
    assert "for (( num=" in output
    assert "unset it" in output


def test_id_mangle_transform_uses_shared_name_pool():
    pool = NamePool(random.Random(5))
    ast = {"type": "script", "body": [_assignment("value", "1")]}

    transformed, stats = id_mangle.LayerImpl().transform(
        ast, _config(name_pool=pool, intensity=0.0)
    )

    assert transformed["body"][0]["name"] != "value"
    assert stats.identifiers_mangled == 1


def test_flow_condition_marking_handles_keyword_and_synthetic_shapes():
    nested = {"type": "list", "parts": [_command("test", "x"), "noise"]}
    keyword_if = {
        "type": "compound",
        "kind": "if",
        "parts": [
            _word("if"),
            nested,
            _word("then"),
            _command("printf", "body"),
            _word("elif"),
            _command("test", "y"),
            _word("then"),
            _command("printf", "other"),
        ],
    }
    flow._mark_condition_children(keyword_if)
    assert nested["_no_wrap"] is True
    assert nested["parts"][0]["_no_wrap"] is True
    assert keyword_if["parts"][3].get("_no_wrap") is None
    assert keyword_if["parts"][5]["_no_wrap"] is True

    synthetic = {"type": "compound", "kind": "while", "parts": [_command("true")]}
    flow._mark_condition_children(synthetic)
    assert synthetic["parts"][0]["_no_wrap"] is True

    flow._mark_condition_children({"type": "compound", "kind": "if", "parts": []})
    flow._mark_condition_children({"type": "compound", "kind": "(", "parts": [_command(":")]})
    flow._mark_condition_children({"type": "compound", "kind": "if", "parts": ["condition"]})


def test_flow_reference_and_write_walkers_cover_irregular_ast_shapes():
    ast = {
        "type": "script",
        "var_refs": ["annotated"],
        "body": [
            None,
            _assignment("written", "$read"),
            _assignment("numeric", 7),
            {"type": "expansion", "kind": "parameter", "value": "expanded"},
            {"type": "expansion", "kind": "parameter", "value": 8},
            _word("$word_ref"),
            {"type": "word", "value": 9},
            {
                "type": "command",
                "parts": [
                    _word("local"),
                    _word("-r"),
                    _word("plain"),
                    _word("with_value=1"),
                    _word("-=ignored"),
                    _assignment("nested", "$dependency"),
                ],
            },
        ],
        "parts": {"type": "word", "value": "$dict_child"},
        "test_parts": "scalar",
    }

    assert flow._get_var_refs(ast) == {
        "annotated",
        "read",
        "expanded",
        "word_ref",
        "dependency",
        "dict_child",
    }
    assert flow._get_var_writes(ast) == {
        "written",
        "numeric",
        "plain",
        "with_value",
        "nested",
    }
    assert flow._get_var_refs("not-a-node") == set()
    assert flow._get_var_writes("not-a-node") == set()


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        ("not-a-node", False),
        (_command("echo", "x"), True),
        ({"type": "command", "parts": [_assignment("x", "1")]}, False),
        ({"type": "command", "parts": []}, True),
        ({"type": "pipeline"}, True),
        ({"type": "word", "value": "literal"}, False),
    ],
)
def test_flow_barrier_classification(node, expected):
    assert flow._is_control_flow_barrier(node) is expected


def test_flow_reorder_respects_dependencies_barriers_and_window():
    first = _assignment("a", "1")
    second = _assignment("b", "2")
    dependent = _assignment("c", "$a")
    barrier = _command("printf", "middle")
    tail = _assignment("d", "4")

    reordered = flow._reorder_independent_blocks(
        [first, second, dependent, barrier, tail], ScriptedRandom(), max_group_size=1
    )

    assert set(map(id, reordered)) == {id(first), id(second), id(dependent), id(barrier), id(tail)}
    assert reordered.index(first) < reordered.index(dependent)
    assert reordered.index(barrier) < reordered.index(tail)


def test_flow_wraps_commands_without_corrupting_conditions():
    condition = _command("true")
    body_command = _command("printf", "ok")
    ast = {
        "type": "compound",
        "kind": "if",
        "parts": [condition, body_command],
    }
    stats = LayerStats()

    transformed = flow._flow_walk(
        ast,
        _config(rng=ScriptedRandom(randoms=(0.0, 1.0, 1.0, 1.0))),
        stats,
    )

    assert transformed["parts"][0]["_no_wrap"] is True
    assert transformed["parts"][0]["type"] == "command"
    assert transformed["parts"][1]["type"] == "compound"
    assert stats.nodes_modified >= 1
    assert flow._flow_walk("not-a-node", _config(), LayerStats()) == "not-a-node"


def test_flow_subshell_escape_and_function_extraction_edges():
    assert flow._has_variable_escape(_command("declare", "x"))
    assert flow._has_variable_escape({"type": "command", "parts": [_assignment("x", "1")]})
    assert not flow._has_variable_escape(_command("printf", "ok"))

    short = [_command("printf", str(index)) for index in range(3)]
    assert flow._extract_functions(short, ScriptedRandom()) is short

    unsafe = [_command("declare", f"v{index}=x") for index in range(4)]
    assert flow._extract_functions(unsafe, ScriptedRandom()) is unsafe

    safe = [_command("printf", str(index)) for index in range(4)]
    extracted = flow._extract_functions(
        safe, ScriptedRandom(randints=(2, 0x123, 0x124))
    )
    assert [node["type"] for node in extracted[:2]] == ["function_def", "function_def"]
    assert [node["parts"][0]["value"] for node in extracted[2:4]] == [
        "_blk_0123",
        "_blk_0124",
    ]


def test_opaque_const_structured_test_and_command_edges_execute():
    ast = {
        "type": "script",
        "body": [
            {"type": "command", "parts": []},
            {"type": "command", "parts": ["invalid"]},
            {
                "type": "command",
                "parts": [_word("sleep"), "noise", _word("0", raw="0")],
            },
            {
                "type": "test_expr",
                "test_parts": [
                    {"type": "operator", "value": "("},
                    _word("7", raw="7"),
                    _word("-eq"),
                    _word("7", raw="7"),
                ],
            },
        ],
    }
    transformed, stats = opaque_const.LayerImpl().transform(
        ast, _config(rng=ScriptedRandom(randranges=(1, 2, 3), randints=(20, 3, 4)))
    )

    sleep_value = transformed["body"][2]["parts"][2]["value"]
    test_parts = transformed["body"][3]["test_parts"]
    assert sleep_value.startswith("$((")
    assert "raw" not in transformed["body"][2]["parts"][2]
    assert test_parts[1]["value"].startswith("$((")
    assert test_parts[3]["value"].startswith("$((")
    assert int(stats.custom["constants_obfuscated"]) == 3

    process = _run_bash(
        f"sleep {sleep_value}\n[[ {test_parts[1]['value']} -eq {test_parts[3]['value']} ]]\n"
    )
    assert process.returncode == 0


def test_opaque_const_raw_constructs_cover_selection_and_rejections():
    stats = LayerStats()
    rng = ScriptedRandom(
        randoms=(1.0, 0.0, 0.0, 0.0),
        randranges=(0, 1, 2),
        randints=(2, 20, 3),
    )
    config = _config(rng=rng)
    ast = {
        "type": "script",
        "body": [
            _word("(( 1 + 2 + 1000000001 ))", raw="(( 1 + 2 + 1000000001 ))"),
            _word("[[ 3 -gt 2 ]]", raw="[[ 3 -gt 2 ]]"),
            _word("[[ 4 == 4 ]]", raw="[[ 4 == 4 ]]"),
            _word("plain 5", raw="plain 5"),
            _word("test 6"),
            {"type": "word", "value": 7, "raw": "7"},
            "not-a-node",
        ],
    }

    transformed = opaque_const._opaque_walk(ast, config, stats)

    assert transformed["body"][0]["value"].startswith("(( 1 + (")
    assert "1000000001" in transformed["body"][0]["value"]
    assert "$((" in transformed["body"][1]["value"]
    assert transformed["body"][2]["value"] == "[[ 4 == 4 ]]"
    assert transformed["body"][3]["value"] == "plain 5"
    assert transformed["body"][4]["value"] == "test 6"
    assert opaque_const._opaque_walk("not-a-node", config, stats) == "not-a-node"


@pytest.mark.parametrize(
    ("value", "arithmetic", "numeric_test", "eligible"),
    [
        ("$((1 + 2))", True, False, False),
        (" ((1)) ", True, False, False),
        ("[ 1 -eq 1 ]", False, True, False),
        ("test 1 -ne 2", False, True, False),
        ("[[ 1 =~ 1 ]]", False, False, False),
        ("01", False, False, False),
        ("-1000000000", False, False, True),
    ],
)
def test_opaque_const_construct_and_integer_classification(
    value, arithmetic, numeric_test, eligible
):
    assert opaque_const._is_arithmetic_construct(value) is arithmetic
    assert opaque_const._is_numeric_test_construct(value) is numeric_test
    assert opaque_const._eligible_integer(value) is eligible


class CollisionRandom(ScriptedRandom):
    def __init__(self) -> None:
        super().__init__(randints=(11, 11, 12, 13))


def test_cff_unique_states_retries_collisions_and_honors_exclusions():
    assert cff._unique_states(2, CollisionRandom(), exclude={11}) == [12, 13]


@pytest.mark.parametrize(
    "node",
    [
        {"type": "command", "parts": []},
        {"type": "command", "parts": [_word("echo"), "noise"]},
        {"type": "command", "parts": [_word("echo"), {"type": "redirect"}]},
        _command("printf", "$?"),
        {"type": "command", "parts": [_assignment("x", "$(date)")]},
        {"type": "command", "parts": [_assignment("x", "`date`")]},
        _command("cd", "/tmp"),
        {"type": "command", "parts": [_word("echo")], "_cff": True},
    ],
)
def test_cff_rejects_ineligible_statement_edges(node):
    assert not cff._is_eligible_statement(node)


def test_cff_statement_and_compound_walk_edges_preserve_execution():
    pool = NamePool(random.Random(19))
    config = _config(rng=random.Random(19), name_pool=pool)
    compound = {
        "type": "compound",
        "kind": "group",
        "parts": [_command("printf", "a"), _command("printf", "b"), _command("printf", "c")],
    }
    ast = {
        "type": "script",
        "body": [compound, "barrier", _command("printf", "tail")],
    }
    stats = LayerStats()

    transformed = cff._flatten_walk(ast, config, stats, depth=0)
    output = emit(transformed)
    process = _run_bash(output.replace("barrier\n", ""))

    assert process.returncode == 0, process.stderr.decode(errors="replace")
    assert process.stdout == b"abctail"
    assert transformed["body"][0]["parts"][0]["_cff"] is True
    assert cff._flatten_walk("not-a-node", config, LayerStats(), 0) == "not-a-node"


def test_cff_flushes_short_runs_around_barriers():
    first = _command("echo", "one")
    second = _command("echo", "two")
    barrier = _command("cd", "/tmp")
    result = cff._flatten_statement_list(
        [first, second, barrier, _command("echo", "three")],
        _config(name_pool=NamePool(random.Random(2))),
        LayerStats(),
    )
    assert result == [first, second, barrier, result[-1]]
    assert not any(node.get("_cff") for node in result)


@pytest.mark.parametrize("method", ["base64", "hex_printf", "octal_printf"])
def test_encode_eval_methods_execute_in_real_bash(method):
    stats = LayerStats()
    encoded = encode._encode_eval(
        "printf encoded", ScriptedRandom(choices=(method,)), stats
    )
    process = _run_bash(emit({"type": "script", "body": [encoded]}))

    assert process.returncode == 0, process.stderr.decode(errors="replace")
    assert process.stdout == b"encoded"
    assert stats.regions_encoded == stats.nodes_modified == 1


@pytest.mark.parametrize("method", ["base64", "hex", "octal"])
@pytest.mark.parametrize("mode", ["no-eval", "direct-exec"])
def test_encode_subprocess_decoder_methods_execute_in_real_bash(method, mode):
    config = _config(rng=ScriptedRandom(choices=(method,)), eval_mode=mode)
    encoded = encode._encode_command(_command("printf", "encoded"), config, LayerStats())
    process = _run_bash(emit({"type": "script", "body": [encoded]}))

    assert process.returncode == 0, process.stderr.decode(errors="replace")
    assert process.stdout == b"encoded"


@pytest.mark.parametrize(
    ("ast", "cmd_str"),
    [
        ({}, ""),
        ({"parts": []}, ""),
        ({"parts": ["printf"]}, "printf"),
        ({"parts": [{"type": "assignment", "value": "printf"}]}, "printf"),
        (_command(""), ""),
        (_command("cd", "/tmp"), "cd /tmp"),
        (_command("worker", "arg"), "worker arg"),
        (_command("printf", "$value"), "printf $value"),
        (_command("printf", "`date`"), "printf `date`"),
    ],
)
def test_encode_subprocess_safety_rejection_edges(ast, cmd_str):
    assert not encode._is_subprocess_safe(ast, cmd_str)


def test_encode_walk_handles_markers_nested_body_and_short_commands():
    stats = LayerStats()
    ast = {
        "type": "script",
        "body": {
            "type": "script",
            "body": [
                _command(":"),
                _command("printf", "junk", _junk=True),
                _command("printf", "encoded", _encoded=True),
                "literal",
            ],
        },
    }
    transformed = encode._encode_walk(ast, _config(rng=ScriptedRandom()), stats)

    assert transformed["body"]["body"][0]["parts"][0]["value"] == ":"
    assert transformed["body"]["body"][1]["_junk"] is True
    assert transformed["body"]["body"][2]["_encoded"] is True
    assert encode._encode_walk("not-a-node", _config(), LayerStats()) == "not-a-node"


def test_encode_unknown_mode_leaves_command_unchanged():
    command = _command("printf", "hello")

    class InvalidConfig:
        rng = ScriptedRandom()
        eval_mode = "unknown"

    assert encode._encode_command(command, InvalidConfig(), LayerStats()) is command


def test_references_positional_params_detection():
    # Positional references -> True (covers the found=True return path).
    for val in ("$*", "$@", "$#", "$1", "${@}", "${*}", "${#}", "${10}"):
        node = {"type": "command", "parts": [{"type": "word", "value": val}]}
        assert flow._references_positional_params(node) is True
    # Nested inside list and dict children (both recursion branches).
    nested = {
        "type": "compound",
        "body": [
            {"type": "command", "parts": [{"type": "word", "value": "safe"}]},
            {"type": "word", "value": "$@"},
        ],
    }
    assert flow._references_positional_params(nested) is True
    assert flow._references_positional_params(
        {"type": "x", "test_parts": {"type": "word", "value": "$1"}}) is True
    # A non-dict child with nothing found -> exercises the `not isinstance` guard.
    assert flow._references_positional_params(
        {"type": "x", "parts": ["not-a-dict", {"type": "word", "value": "plain"}]}) is False
    # Positional found early, with a later item -> exercises the `if found` short-circuit.
    assert flow._references_positional_params(
        {"type": "x", "parts": [{"type": "word", "value": "$@"},
                                {"type": "word", "value": "later"}]}) is True
    # Named vars, string length ${#name}, and indirect ${!ref} are NOT positional.
    for val in ("$foo", "${bar}", "${#name}", "${!ref}", "plain"):
        node = {"type": "command", "parts": [{"type": "word", "value": val}]}
        assert flow._references_positional_params(node) is False
    assert flow._references_positional_params({"type": "x"}) is False
