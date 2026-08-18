"""Layer ordering and compatibility tests."""

import pytest

from obfush.utils.compat_matrix import (
    Compat,
    get_compatibility,
    get_safe_order,
    validate_layer_set,
)


def test_compatibility_defaults_and_known_values():
    assert get_compatibility("id-mangle", "id-mangle") is Compat.OK
    assert get_compatibility("junk-inject", "str-shred") is Compat.CAUT
    assert get_compatibility("flow-obfusc", "id-mangle") is Compat.DANGER
    assert get_compatibility("unknown", "other") is Compat.OK


def test_safe_order_respects_all_applicable_dependencies():
    requested = [
        "poly-shell", "entropy-mask", "cmd-sub", "str-shred", "encode",
        "indirection", "junk-inject", "id-mangle", "flow-obfusc", "opaque-const",
        "cff",
    ]
    ordered = get_safe_order(requested)
    assert set(ordered) == set(requested)
    assert ordered.index("flow-obfusc") < ordered.index("junk-inject")
    assert ordered.index("flow-obfusc") < ordered.index("encode")
    assert ordered.index("id-mangle") < ordered.index("str-shred")
    assert ordered.index("id-mangle") < ordered.index("opaque-const")
    assert ordered.index("flow-obfusc") < ordered.index("opaque-const")
    assert ordered.index("opaque-const") < ordered.index("str-shred")
    assert ordered.index("opaque-const") < ordered.index("encode")
    assert ordered.index("id-mangle") < ordered.index("cff")
    assert ordered.index("flow-obfusc") < ordered.index("cff")
    assert ordered.index("opaque-const") < ordered.index("cff")
    assert ordered.index("cff") < ordered.index("encode")
    assert ordered.index("cff") < ordered.index("str-shred")
    assert ordered.index("encode") < ordered.index("poly-shell")
    assert ordered.index("junk-inject") < ordered.index("entropy-mask")


def test_safe_order_is_stable_without_constraints():
    assert get_safe_order(["junk-inject", "encode"]) == ["junk-inject", "encode"]


def test_cycle_detection(monkeypatch):
    monkeypatch.setattr(
        "obfush.utils.compat_matrix.ORDERING_RULES",
        [("id-mangle", "encode"), ("encode", "id-mangle")],
    )
    with pytest.raises(ValueError, match="Cycle detected"):
        get_safe_order(["id-mangle", "encode"])


def test_validate_layer_set_rejects_unknown_names():
    assert validate_layer_set(["encode"]) == ["encode"]
    with pytest.raises(ValueError, match="Unknown layer"):
        validate_layer_set(["not-a-layer"])
