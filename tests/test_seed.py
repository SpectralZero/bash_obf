"""Seed generation and derivation tests."""

from obfush.engine.seed import (
    create_rng,
    derive_layer_seed,
    generate_seed,
    generate_seed_from_path,
)


def test_generate_seed_accepts_text_and_bytes(monkeypatch):
    monkeypatch.setattr("obfush.engine.seed.os.urandom", lambda size: b"\x01" * size)
    monkeypatch.setattr("obfush.engine.seed.time.time", lambda: 123.5)
    assert generate_seed("echo hello") == generate_seed(b"echo hello")


def test_generate_seed_from_path_reads_bytes(tmp_path, monkeypatch):
    source = tmp_path / "source.sh"
    source.write_bytes(b"echo hello\n")
    monkeypatch.setattr("obfush.engine.seed.os.urandom", lambda size: b"\x02" * size)
    monkeypatch.setattr("obfush.engine.seed.time.time", lambda: 200.0)
    assert generate_seed_from_path(str(source)) == generate_seed(source.read_bytes())


def test_create_rng_is_deterministic_and_independent():
    first = create_rng(42)
    second = create_rng(42)
    assert [first.randrange(1000) for _ in range(20)] == [
        second.randrange(1000) for _ in range(20)
    ]


def test_layer_seed_is_deterministic_and_layer_specific():
    assert derive_layer_seed(42, "encode") == derive_layer_seed(42, "encode")
    assert derive_layer_seed(42, "encode") != derive_layer_seed(42, "str-shred")
    assert 0 <= derive_layer_seed(42, "encode") <= 0xFFFFFFFFFFFFFFFF
