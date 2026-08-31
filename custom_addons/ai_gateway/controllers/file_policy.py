"""Shared, dependency-free upload validation for all ingress paths."""
from __future__ import annotations

import io
import os
import zipfile
from pathlib import PurePosixPath


MAX_UPLOAD_BYTES = int(os.environ.get("AI_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
MAX_UNPACKED_BYTES = int(os.environ.get("AI_MAX_UNPACKED_BYTES", str(100 * 1024 * 1024)))

_ALLOWED_EXTENSIONS = {
    ".txt": "text/plain", ".md": "text/markdown", ".csv": "text/csv", ".json": "application/json",
    ".pdf": "application/pdf", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel", ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
}


def _zip_is_safe(raw, required_names=()):
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = set(info.filename.replace("\\", "/") for info in archive.infolist())
            if any(required not in names for required in required_names):
                return False, "office document content is invalid"
            total = 0
            for info in archive.infolist():
                normalized_name = info.filename.replace("\\", "/")
                name = PurePosixPath(normalized_name)
                if "\x00" in normalized_name or name.is_absolute() or ".." in name.parts:
                    return False, "archive contains an unsafe path"
                # Unix mode 0o120000 denotes a symlink entry.
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    return False, "archive symlinks are not allowed"
                total += max(info.file_size, 0)
                if total > MAX_UNPACKED_BYTES:
                    return False, "archive unpacked size exceeds the safety limit"
    except (zipfile.BadZipFile, OSError):
        return False, "archive content is invalid"
    return True, None


def validate_upload(filename, raw, max_bytes=None):
    """Validate extension, size and basic content signatures.

    This does not claim to be malware scanning. A production deployment should
    connect the quarantine state to an AV/content scanning service before a
    file becomes searchable or downloadable.
    """
    filename = os.path.basename(str(filename or "file"))
    ext = os.path.splitext(filename.lower())[1]
    if ext not in _ALLOWED_EXTENSIONS:
        raise ValueError("unsupported file type")
    if not isinstance(raw, (bytes, bytearray)) or not raw:
        raise ValueError("file is empty")
    if len(raw) > (max_bytes or MAX_UPLOAD_BYTES):
        raise ValueError("file exceeds the upload size limit")
    raw = bytes(raw)
    signatures = {
        ".pdf": raw.startswith(b"%PDF-"),
        ".png": raw.startswith(b"\x89PNG\r\n\x1a\n"),
        ".jpg": raw.startswith(b"\xff\xd8\xff"),
        ".jpeg": raw.startswith(b"\xff\xd8\xff"),
        ".webp": raw[:4] == b"RIFF" and raw[8:12] == b"WEBP",
    }
    if ext in signatures and not signatures[ext]:
        raise ValueError("file content does not match its extension")
    if ext in {".docx", ".xlsx", ".pptx"}:
        if not raw.startswith(b"PK"):
            raise ValueError("office document content is invalid")
        required = {
            ".docx": ("[Content_Types].xml", "word/document.xml"),
            ".xlsx": ("[Content_Types].xml", "xl/workbook.xml"),
            ".pptx": ("[Content_Types].xml", "ppt/presentation.xml"),
        }[ext]
        safe, reason = _zip_is_safe(raw, required_names=required)
        if not safe:
            raise ValueError(reason)
    if ext == ".xls" and raw[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise ValueError("legacy spreadsheet content is invalid")
    if ext in {".txt", ".md", ".csv", ".json"}:
        if b"\x00" in raw[:8192]:
            raise ValueError("text file contains binary content")
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("text file must be UTF-8")
    return {"filename": filename, "extension": ext, "mimetype": _ALLOWED_EXTENSIONS[ext], "size": len(raw)}
