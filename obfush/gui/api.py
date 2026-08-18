"""Synchronous JSON API used by the obfush GUI."""

from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import xxhash
from flask import Blueprint, current_app, jsonify, request
from werkzeug.exceptions import BadRequest, UnsupportedMediaType

from obfush.batch import derive_batch_seed
from obfush.cli import PRESETS
from obfush.engine.core import EngineConfig, EngineResult, PolymorphicEngine
from obfush.engine.security_analyzer import SourceAnalysis, analyze_source
from obfush.layers import ALL_LAYER_NAMES
from obfush.utils.entropy_utils import entropy_in_range, shannon_entropy, windowed_entropy


JSON_LIMIT_BYTES = 1_048_576
SOURCE_LIMIT_BYTES = 1_048_576
MAX_BATCH_FILES = 100
_MAX_SEED = (1 << 64) - 1
_CONFIG_FIELDS = {
    "preset",
    "seed",
    "intensity",
    "eval_mode",
    "layers",
    "min_layers",
    "entropy_target",
    "max_size_ratio",
}

api = Blueprint("api", __name__, url_prefix="/api")


class APIError(ValueError):
    """A client-facing request validation error."""

    def __init__(self, message: str, *, field: str | None = None, status: int = 400):
        super().__init__(message)
        self.field = field
        self.status = status


@api.errorhandler(APIError)
def handle_api_error(error: APIError):
    payload: dict[str, Any] = {
        "code": (
            "validation_error"
            if error.status == 400
            else "payload_too_large"
            if error.status == 413
            else "processing_error"
        ),
        "message": str(error),
    }
    if error.field is not None:
        payload["field"] = error.field
    return jsonify({"error": payload}), error.status


@api.get("/presets")
def presets():
    """Return the canonical CLI preset definitions."""
    return jsonify(PRESETS)


@api.get("/layers")
def layers_catalog():
    """Return the authoritative layer execution catalog.

    The GUI uses this as the source of truth for the layer toggles instead of
    scraping a preset's force_layers, so the list stays correct even if preset
    definitions change.
    """
    return jsonify({"layers": list(ALL_LAYER_NAMES)})


@api.post("/obfuscate")
def obfuscate():
    payload = _json_object(_CONFIG_FIELDS | {"source"})
    source = _source(payload, "source")
    config = _engine_config(payload)
    try:
        result = PolymorphicEngine(config).run(source)
    except Exception as exc:
        current_app.logger.exception("Obfuscation failed")
        raise APIError(str(exc) or "Obfuscation failed", status=422) from exc
    return jsonify(_result_payload(result, source, config.entropy_target))


@api.post("/analyze")
def analyze():
    payload = _json_object({"output", "original_source", "entropy_target"})
    output = _source(payload, "output")
    original = _optional_source(payload, "original_source")
    target = _number(payload.get("entropy_target", 4.5), "entropy_target", 0.0, 8.0)
    analysis = analyze_source(
        output,
        original_size=len(original.encode("utf-8")) if original else None,
        baseline_source=original,
    )
    return jsonify(_analysis_payload(output, analysis, target))


@api.post("/batch")
def batch():
    payload = _json_object({"files", "config"})
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise APIError("files must be a non-empty list", field="files")
    if len(files) > MAX_BATCH_FILES:
        raise APIError(f"files must contain at most {MAX_BATCH_FILES} items", field="files")

    raw_config = payload.get("config", {})
    if not isinstance(raw_config, dict):
        raise APIError("config must be an object", field="config")
    unknown = sorted(set(raw_config) - _CONFIG_FIELDS)
    if unknown:
        raise APIError(f"Unknown config field(s): {', '.join(unknown)}", field="config")
    config = _engine_config(raw_config)

    normalized: list[tuple[str, str]] = []
    names: set[str] = set()
    for index, item in enumerate(files):
        field = f"files[{index}]"
        if not isinstance(item, dict):
            raise APIError("Each file must be an object", field=field)
        unknown_item = sorted(set(item) - {"name", "source"})
        if unknown_item:
            raise APIError(
                f"Unknown file field(s): {', '.join(unknown_item)}",
                field=field,
            )
        name = item.get("name")
        if (
            not isinstance(name, str)
            or not name
            or len(name) > 255
            or Path(name).name != name
            or not name.lower().endswith(".sh")
        ):
            raise APIError("name must be a base .sh filename of at most 255 characters", field=field)
        if name in names:
            raise APIError(f"Duplicate filename: {name}", field=field)
        names.add(name)
        normalized.append((name, _source(item, "source", field_prefix=field)))

    items = [_batch_item(name, source, config) for name, source in normalized]
    succeeded = sum(item["status"] == "ok" for item in items)
    return jsonify({
        "items": items,
        "summary": {
            "total": len(items),
            "succeeded": succeeded,
            "failed": len(items) - succeeded,
        },
    })


def _json_object(allowed: set[str]) -> dict[str, Any]:
    if not request.is_json:
        raise APIError("Content-Type must be application/json")
    try:
        payload = request.get_json()
    except (BadRequest, UnsupportedMediaType) as exc:
        raise APIError("Request body contains malformed JSON") from exc
    if not isinstance(payload, dict):
        raise APIError("JSON request body must be an object")
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise APIError(f"Unknown field(s): {', '.join(unknown)}")
    return payload


def _source(
    payload: dict[str, Any],
    field: str,
    *,
    field_prefix: str | None = None,
) -> str:
    value = payload.get(field)
    location = f"{field_prefix}.{field}" if field_prefix else field
    if not isinstance(value, str):
        raise APIError(f"{field} must be a string", field=location)
    if not value.strip():
        raise APIError(f"{field} must not be empty", field=location)
    if len(value.encode("utf-8")) > SOURCE_LIMIT_BYTES:
        raise APIError(f"{field} must not exceed 1 MiB", field=location, status=413)
    return value


def _optional_source(payload: dict[str, Any], field: str) -> str | None:
    if field not in payload or payload[field] is None:
        return None
    return _source(payload, field)


def _engine_config(payload: dict[str, Any]) -> EngineConfig:
    preset = payload.get("preset")
    if preset is not None and (not isinstance(preset, str) or preset not in PRESETS):
        raise APIError(
            f"preset must be one of: {', '.join(PRESETS)}",
            field="preset",
        )

    values: dict[str, Any] = dict(PRESETS[preset]) if preset else {}
    for key in _CONFIG_FIELDS - {"preset", "layers"}:
        if key in payload:
            values[key] = payload[key]

    layers = payload.get("layers")
    if layers is not None:
        values["force_layers"] = _layers(layers)
        if "min_layers" not in payload and values["force_layers"]:
            values["min_layers"] = len(values["force_layers"])
    elif "force_layers" in values:
        forced = values["force_layers"]
        values["force_layers"] = forced.split(",") if forced else None

    seed = values.get("seed")
    if seed is not None:
        values["seed"] = _seed(seed)
    values["intensity"] = _number(values.get("intensity", 0.8), "intensity", 0.0, 1.0)
    values["entropy_target"] = _number(
        values.get("entropy_target", 4.5), "entropy_target", 0.0, 8.0,
    )
    values["max_size_ratio"] = _number(
        values.get("max_size_ratio", 3.0), "max_size_ratio", 1.0, 100.0,
    )
    values["min_layers"] = _integer(
        values.get("min_layers", 4), "min_layers", 1, len(ALL_LAYER_NAMES),
    )

    eval_mode = values.get("eval_mode", "ok")
    if not isinstance(eval_mode, str) or eval_mode not in {"ok", "no-eval", "direct-exec"}:
        raise APIError("eval_mode must be ok, no-eval, or direct-exec", field="eval_mode")
    values["eval_mode"] = eval_mode
    return EngineConfig(**values)


def _layers(value: Any) -> list[str] | None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise APIError("layers must be a list of layer names", field="layers")
    if len(value) != len(set(value)):
        raise APIError("layers must not contain duplicates", field="layers")
    unknown = sorted(set(value) - set(ALL_LAYER_NAMES))
    if unknown:
        raise APIError(f"Unknown layer(s): {', '.join(unknown)}", field="layers")
    return value or None


def _seed(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise APIError("seed must be an integer or string", field="seed")
    if isinstance(value, str):
        if not value or len(value) > 256:
            raise APIError("seed string must contain 1-256 characters", field="seed")
        try:
            value = int(value)
        except ValueError:
            value = xxhash.xxh64(value.encode("utf-8")).intdigest()
    if not 0 <= value <= _MAX_SEED:
        raise APIError("seed integer must be unsigned and at most 64 bits", field="seed")
    return value


def _number(value: Any, field: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise APIError(f"{field} must be numeric", field=field)
    value = float(value)
    if not minimum <= value <= maximum:
        raise APIError(f"{field} must be between {minimum} and {maximum}", field=field)
    return value


def _integer(value: Any, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise APIError(f"{field} must be an integer", field=field)
    if not minimum <= value <= maximum:
        raise APIError(f"{field} must be between {minimum} and {maximum}", field=field)
    return value


def _result_payload(result: EngineResult, source: str, target: float) -> dict[str, Any]:
    analysis = analyze_source(
        result.output,
        original_size=len(source.encode("utf-8")),
        baseline_source=source,
    )
    payload = _analysis_payload(result.output, analysis, target)
    payload.update({
        "output": result.output,
        "seed": result.seed,
        "layers_applied": result.layers_applied,
        "stats": {name: asdict(stats) for name, stats in result.layer_stats.items()},
        "elapsed_ms": round(result.elapsed_ms, 3),
        "verified": result.verified,
    })
    return payload


def _analysis_payload(
    source: str,
    analysis: SourceAnalysis,
    target: float,
) -> dict[str, Any]:
    encoded = source.encode("utf-8")
    overall = shannon_entropy(encoded)
    windows = [
        {"offset": offset, "entropy": round(entropy, 4)}
        for offset, entropy in windowed_entropy(encoded)
    ]
    return {
        "analysis": analysis.to_dict(),
        "entropy": {
            "overall": round(overall, 4),
            "target": target,
            "in_range": entropy_in_range(overall, target),
            "windows": windows,
        },
        "security_score": _security_score(analysis, overall, target),
    }


def _security_score(analysis: SourceAnalysis, entropy: float, target: float) -> int:
    """Produce a bounded operational indicator from analyzer findings."""
    deductions = (
        analysis.standalone_eval_count * 12
        + analysis.xxd_command_count * 10
        + analysis.legacy_fingerprint_count * 10
        + len(analysis.assigned_never_read_candidates) * 2
        + len(analysis.uncalled_function_candidates) * 3
    )
    deductions += min(15, round(abs(entropy - target) * 5))
    return max(0, min(100, 100 - deductions))


def _batch_item(name: str, source: str, config: EngineConfig) -> dict[str, Any]:
    item_seed = derive_batch_seed(config.seed, Path(name), source)
    try:
        result = PolymorphicEngine(replace(config, seed=item_seed)).run(source)
        payload = _result_payload(result, source, config.entropy_target)
        return {"name": name, "status": "ok", **payload}
    except Exception as exc:
        current_app.logger.exception("Batch obfuscation failed for %s", name)
        return {
            "name": name,
            "status": "error",
            "error": str(exc) or "Obfuscation failed",
        }
