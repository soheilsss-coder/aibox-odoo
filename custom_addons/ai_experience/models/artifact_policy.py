"""Shared bounds for artifact generation across tool and HTTP ingress."""

import json


MAX_ARTIFACT_REQUEST_BYTES = 512 * 1024
MAX_ARTIFACT_ROWS = 1000
MAX_ARTIFACT_COLUMNS = 50
MAX_ARTIFACT_CELL_CHARS = 10_000
MAX_ARTIFACT_OUTPUT_BYTES = 10 * 1024 * 1024


def validate_artifact_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("artifact payload must be an object")
    encoded_size = len(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"))
    if encoded_size > MAX_ARTIFACT_REQUEST_BYTES:
        raise ValueError("artifact request is too large")
    rows = payload.get("rows") or []
    if not isinstance(rows, list) or len(rows) > MAX_ARTIFACT_ROWS:
        raise ValueError("artifact rows exceed the limit")
    columns = payload.get("columns") or (
        list(rows[0].keys()) if rows and isinstance(rows[0], dict) else []
    )
    if not isinstance(columns, list) or len(columns) > MAX_ARTIFACT_COLUMNS:
        raise ValueError("artifact columns exceed the limit")
    if any(not isinstance(column, (str, int, float, bool)) for column in columns):
        raise ValueError("artifact column names are invalid")
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("artifact rows must be objects")
        for value in row.values():
            if len(str(value)) > MAX_ARTIFACT_CELL_CHARS:
                raise ValueError("artifact cell exceeds the limit")
    for key in ("values", "labels"):
        values = payload.get(key)
        if values is not None and (not isinstance(values, list) or len(values) > MAX_ARTIFACT_ROWS):
            raise ValueError("artifact chart values exceed the limit")
    return payload


def validate_artifact_output(data):
    if len(data) > MAX_ARTIFACT_OUTPUT_BYTES:
        raise ValueError("generated artifact exceeds the output limit")
    return data
