"""Flask API coverage for the synchronous local GUI."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from obfush.cli import PRESETS
from obfush.gui.app import create_app
from obfush.layers import ALL_LAYER_NAMES
from obfush.layers.base import LayerStats


@pytest.fixture
def client():
    app = create_app({"TESTING": True})
    return app.test_client()


@dataclass
class _Result:
    source: str
    output: str
    seed: int = 42
    layers_applied: list[str] = field(default_factory=lambda: ["id-mangle"])
    layer_stats: dict[str, LayerStats] = field(
        default_factory=lambda: {"id-mangle": LayerStats(nodes_modified=1, elapsed_ms=0.25)}
    )
    elapsed_ms: float = 1.5
    verified: bool = False


class _Engine:
    configs = []

    def __init__(self, config):
        self.config = config
        self.configs.append(config)

    def run(self, source):
        if "FAIL" in source:
            raise ValueError("invalid test source")
        return _Result(source=source, output=f"# obfuscated\n{source}", seed=self.config.seed or 42)


@pytest.fixture
def fake_engine(monkeypatch):
    _Engine.configs.clear()
    monkeypatch.setattr("obfush.gui.api.PolymorphicEngine", _Engine)
    return _Engine


def test_index_serves_operational_workspace(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b'id="source-editor"' in response.data
    assert b'id="batch-list"' in response.data


def test_presets_returns_canonical_profiles(client):
    response = client.get("/api/presets")
    assert response.status_code == 200
    assert response.get_json() == PRESETS


def test_layers_returns_layer_catalog(client):
    response = client.get("/api/layers")
    assert response.status_code == 200
    assert response.get_json() == {"layers": list(ALL_LAYER_NAMES)}


def test_obfuscate_forwards_entropy_target(client, fake_engine):
    response = client.post("/api/obfuscate", json={
        "source": "echo hello\n",
        "entropy_target": 6.0,
    })
    body = response.get_json()
    assert response.status_code == 200
    assert body["entropy"]["target"] == 6.0
    assert fake_engine.configs[-1].entropy_target == 6.0


def test_obfuscate_returns_output_metrics_and_stats(client, fake_engine):
    response = client.post("/api/obfuscate", json={
        "source": "echo hello\n",
        "preset": "stealth",
        "seed": "42",
        "intensity": 0.6,
        "layers": ["id-mangle"],
        "max_size_ratio": 2.0,
    })
    body = response.get_json()
    assert response.status_code == 200
    assert body["output"].startswith("# obfuscated")
    assert body["seed"] == 42
    assert body["stats"]["id-mangle"]["nodes_modified"] == 1
    assert 0 <= body["security_score"] <= 100
    assert body["analysis"]["source_size_ratio"] > 1
    config = fake_engine.configs[-1]
    assert config.force_layers == ["id-mangle"]
    assert config.min_layers == 1
    assert config.intensity == 0.6


@pytest.mark.parametrize("payload, field", [
    ({}, "source"),
    ({"source": "  "}, "source"),
    ({"source": "echo ok", "preset": "missing"}, "preset"),
    ({"source": "echo ok", "intensity": True}, "intensity"),
    ({"source": "echo ok", "layers": ["missing"]}, "layers"),
    ({"source": "echo ok", "unexpected": 1}, None),
])
def test_obfuscate_rejects_invalid_payloads(client, payload, field):
    response = client.post("/api/obfuscate", json=payload)
    body = response.get_json()
    assert response.status_code == 400
    assert body["error"]["code"] == "validation_error"
    if field is not None:
        assert body["error"]["field"] == field


def test_api_requires_valid_json_object(client):
    wrong_type = client.post("/api/analyze", data="output=echo", content_type="text/plain")
    malformed = client.post("/api/analyze", data="{", content_type="application/json")
    array = client.post("/api/analyze", json=["echo ok"])
    assert wrong_type.status_code == 400
    assert malformed.status_code == 400
    assert array.status_code == 400


def test_request_body_is_capped_at_one_mibibyte(client):
    response = client.post("/api/obfuscate", json={"source": "x" * 1_048_576})
    assert response.status_code == 413
    assert response.get_json()["error"]["code"] == "payload_too_large"


def test_source_field_has_an_explicit_one_mibibyte_cap():
    client = create_app({
        "TESTING": True,
        "MAX_CONTENT_LENGTH": 2_097_152,
    }).test_client()
    source = "x" * 1_048_577
    response = client.post("/api/obfuscate", json={"source": source})
    assert response.status_code == 413
    assert response.get_json()["error"]["code"] == "payload_too_large"
    assert response.get_json()["error"]["field"] == "source"


def test_analyze_reports_security_and_entropy_metrics(client):
    source = "eval payload\ndead=value\n"
    response = client.post("/api/analyze", json={"output": source, "entropy_target": 4.0})
    body = response.get_json()
    assert response.status_code == 200
    assert body["analysis"]["standalone_eval_count"] == 1
    assert body["analysis"]["assigned_never_read_candidates"] == ["dead"]
    assert body["entropy"]["target"] == 4.0
    assert body["security_score"] < 100


def test_analyze_compares_output_with_original_source(client):
    original = "eval original\n"
    response = client.post("/api/analyze", json={
        "output": original + "eval introduced\n",
        "original_source": original,
    })
    analysis = response.get_json()["analysis"]
    assert analysis["baseline_eval_count"] == 1
    assert analysis["introduced_eval_count"] == 1
    assert analysis["source_size_ratio"] == pytest.approx(
        len((original + "eval introduced\n").encode("utf-8"))
        / len(original.encode("utf-8"))
    )


def test_batch_processes_json_file_queue(client, fake_engine):
    response = client.post("/api/batch", json={
        "files": [
            {"name": "one.sh", "source": "echo one\n"},
            {"name": "two.sh", "source": "echo two\n"},
        ],
        "config": {"seed": 7, "layers": ["id-mangle"]},
    })
    body = response.get_json()
    assert response.status_code == 200
    assert body["summary"] == {"total": 2, "succeeded": 2, "failed": 0}
    assert [item["name"] for item in body["items"]] == ["one.sh", "two.sh"]
    assert all(item["status"] == "ok" for item in body["items"])
    assert fake_engine.configs[0].seed != fake_engine.configs[1].seed


def test_batch_retains_individual_processing_errors(client, fake_engine):
    response = client.post("/api/batch", json={
        "files": [
            {"name": "good.sh", "source": "echo good\n"},
            {"name": "bad.sh", "source": "FAIL\n"},
        ]
    })
    body = response.get_json()
    assert response.status_code == 200
    assert body["summary"] == {"total": 2, "succeeded": 1, "failed": 1}
    assert body["items"][1] == {
        "name": "bad.sh", "status": "error", "error": "invalid test source",
    }


@pytest.mark.parametrize("files", [
    [],
    [{"name": "../bad.sh", "source": "echo no"}],
    [{"name": "not-shell.txt", "source": "echo no"}],
    [
        {"name": "same.sh", "source": "echo one"},
        {"name": "same.sh", "source": "echo two"},
    ],
])
def test_batch_validates_file_queue(client, files):
    response = client.post("/api/batch", json={"files": files})
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "validation_error"
