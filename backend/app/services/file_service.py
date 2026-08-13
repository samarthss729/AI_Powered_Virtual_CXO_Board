"""Upload parsing and normalization for company data grounding."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

import pandas as pd

ALLOWED_EXTENSIONS = {".csv", ".json"}
MAX_PREVIEW_CHARS = 1200


class FileServiceError(Exception):
    """Raised for invalid uploads."""


def _extension(filename: str) -> str:
    name = filename.lower().strip()
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1]


def validate_upload(filename: str, raw_bytes: bytes, max_bytes: int) -> None:
    if not filename:
        raise FileServiceError("Filename is required.")
    ext = _extension(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise FileServiceError("Only CSV and JSON uploads are supported.")
    if not raw_bytes:
        raise FileServiceError("Uploaded file is empty.")
    if len(raw_bytes) > max_bytes:
        mb = max_bytes / (1024 * 1024)
        raise FileServiceError(f"File exceeds the {mb:.1f} MB upload limit.")


def parse_and_normalize(filename: str, raw_bytes: bytes) -> dict[str, Any]:
    ext = _extension(filename)
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise FileServiceError("File must be UTF-8 encoded.") from exc

    if ext == ".json":
        return _normalize_json(text)
    if ext == ".csv":
        return _normalize_csv(text)
    raise FileServiceError("Unsupported file type.")


def _normalize_json(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FileServiceError(f"Invalid JSON: {exc.msg}") from exc

    if isinstance(data, dict):
        records = [data]
        shape = "object"
    elif isinstance(data, list):
        if not data:
            raise FileServiceError("JSON array is empty.")
        if not all(isinstance(item, dict) for item in data):
            raise FileServiceError("JSON array must contain objects.")
        records = data
        shape = "array"
    else:
        raise FileServiceError("JSON root must be an object or an array of objects.")

    flat_keys = sorted({str(k) for row in records for k in row.keys()})
    return {
        "format": "json",
        "shape": shape,
        "record_count": len(records),
        "fields": flat_keys,
        "records": records[:50],
        "summary_stats": _numeric_summary(records),
    }


def _normalize_csv(text: str) -> dict[str, Any]:
    try:
        df = pd.read_csv(io.StringIO(text))
    except Exception as exc:  # noqa: BLE001
        raise FileServiceError(f"Could not parse CSV: {exc}") from exc

    if df.empty:
        raise FileServiceError("CSV has no data rows.")

    df.columns = [str(c).strip() for c in df.columns]
    records = json.loads(df.head(50).to_json(orient="records", date_format="iso"))
    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    summary: dict[str, Any] = {}
    for col in numeric_cols:
        series = df[col].dropna()
        if series.empty:
            continue
        summary[col] = {
            "min": _to_number(series.min()),
            "max": _to_number(series.max()),
            "mean": _to_number(series.mean()),
            "latest": _to_number(series.iloc[-1]),
        }

    # Also keep a compact row-oriented preview for agents.
    sample_rows: list[dict[str, Any]] = []
    reader = csv.DictReader(io.StringIO(text))
    for i, row in enumerate(reader):
        if i >= 20:
            break
        sample_rows.append({k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()})

    return {
        "format": "csv",
        "shape": "tabular",
        "record_count": int(len(df)),
        "fields": list(df.columns),
        "records": records,
        "sample_rows": sample_rows,
        "summary_stats": summary,
    }


def _numeric_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, list[float]] = {}
    for row in records:
        for key, value in row.items():
            num = _try_float(value)
            if num is None:
                continue
            buckets.setdefault(str(key), []).append(num)
    out: dict[str, Any] = {}
    for key, values in buckets.items():
        out[key] = {
            "min": min(values),
            "max": max(values),
            "mean": sum(values) / len(values),
            "latest": values[-1],
        }
    return out


def _try_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").replace("%", "").strip()
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _to_number(value: Any) -> float | int:
    number = float(value)
    if number.is_integer():
        return int(number)
    return round(number, 4)


def build_context_block(normalized: dict[str, Any], filename: str) -> str:
    """Create a compact grounding string for agent prompts."""
    payload = {
        "filename": filename,
        "format": normalized.get("format"),
        "record_count": normalized.get("record_count"),
        "fields": normalized.get("fields"),
        "summary_stats": normalized.get("summary_stats"),
        "records": normalized.get("records", [])[:20],
    }
    text = json.dumps(payload, indent=2, default=str)
    if len(text) > 8000:
        text = text[:8000] + "\n...[truncated]"
    return text


def preview_text(raw_text: str) -> str:
    cleaned = raw_text.strip()
    if len(cleaned) <= MAX_PREVIEW_CHARS:
        return cleaned
    return cleaned[:MAX_PREVIEW_CHARS] + "..."
