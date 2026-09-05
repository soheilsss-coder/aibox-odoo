"""Shared, dependency-free upload validation for every file ingress path.

The policy validates the bytes before Odoo stores an attachment.  It is not an
antivirus scanner and it intentionally does not unpack arbitrary archives.
Heavy parsers are selected later by the bounded document extractor.
"""
from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import PurePosixPath


def _env_int(name, default):
    try:
        return max(1, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


MAX_UPLOAD_BYTES = _env_int("AI_MAX_UPLOAD_BYTES", 25 * 1024 * 1024)
MAX_CHAT_UPLOAD_BYTES = _env_int("AI_MAX_CHAT_UPLOAD_BYTES", 50 * 1024 * 1024)
MAX_UNPACKED_BYTES = _env_int("AI_MAX_UNPACKED_BYTES", 100 * 1024 * 1024)

# Tier A: formats with a deterministic local extraction path.  Legacy Office,
# archives, macro-enabled Office, audio/video and executables stay out until a
# separate worker and a real customer corpus certify them.
ALLOWED_EXTENSIONS = frozenset({
    ".txt", ".md", ".csv", ".json", ".html", ".htm",
    ".pdf", ".docx", ".xlsx", ".pptx",
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff",
})

_ALLOWED_MIME_TYPES = {
    ".txt": "text/plain", ".md": "text/markdown", ".csv": "text/csv",
    ".json": "application/json", ".html": "text/html", ".htm": "text/html",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".bmp": "image/bmp", ".tif": "image/tiff", ".tiff": "image/tiff",
}


def _zip_is_safe(raw, required_names=()):
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = {info.filename.replace("\\", "/") for info in archive.infolist()}
            if any(required not in names for required in required_names):
                return False, "office document content is invalid"
            total = 0
            for info in archive.infolist():
                normalized_name = info.filename.replace("\\", "/")
                name = PurePosixPath(normalized_name)
                if "\x00" in normalized_name or name.is_absolute() or ".." in name.parts:
                    return False, "archive contains an unsafe path"
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    return False, "archive symlinks are not allowed"
                total += max(info.file_size, 0)
                if total > MAX_UNPACKED_BYTES:
                    return False, "archive unpacked size exceeds the safety limit"
    except (zipfile.BadZipFile, OSError):
        return False, "archive content is invalid"
    return True, None


def _validate_text(raw, extension):
    if b"\x00" in raw[:8192]:
        raise ValueError("text file contains binary content")
    try:
        decoded = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("text file must be UTF-8") from exc
    if extension == ".json":
        try:
            json.loads(decoded)
        except json.JSONDecodeError as exc:
            raise ValueError("JSON document is invalid") from exc
    return decoded


def validate_upload(filename, raw, max_bytes=None):
    """Validate extension, size, signatures and lightweight document shape.

    This function is deliberately shared by API upload, attachment ingress and
    protected download.  It does not parse or malware-scan the complete file.
    """
    filename = os.path.basename(str(filename or "file"))
    if "\x00" in filename or any(ord(char) < 32 for char in filename):
        raise ValueError("filename contains unsafe control characters")
    ext = os.path.splitext(filename.lower())[1]
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError("unsupported file type")
    if not isinstance(raw, (bytes, bytearray)) or not raw:
        raise ValueError("file is empty")
    limit = MAX_UPLOAD_BYTES if max_bytes is None else max(1, int(max_bytes))
    if len(raw) > limit:
        raise ValueError("file exceeds the upload size limit")
    raw = bytes(raw)
    signatures = {
        ".pdf": raw.startswith(b"%PDF-"),
        ".png": raw.startswith(b"\x89PNG\r\n\x1a\n"),
        ".jpg": raw.startswith(b"\xff\xd8\xff"),
        ".jpeg": raw.startswith(b"\xff\xd8\xff"),
        ".webp": raw[:4] == b"RIFF" and raw[8:12] == b"WEBP",
        ".bmp": raw.startswith(b"BM"),
        ".tif": raw[:4] in {b"II*\x00", b"MM\x00*"},
        ".tiff": raw[:4] in {b"II*\x00", b"MM\x00*"},
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
    if ext in {".txt", ".md", ".csv", ".json", ".html", ".htm"}:
        _validate_text(raw, ext)
    return {
        "filename": filename,
        "extension": ext,
        "mimetype": _ALLOWED_MIME_TYPES[ext],
        "size": len(raw),
    }
