import re
import unicodedata


_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def normalize_search_text(text):
    """Normalize searchable text without changing the cited original.

    Persian/Arabic documents commonly mix ي/ی, ك/ک, Arabic and Persian
    digits, zero-width non-joiners and compatibility forms.  Embeddings keep
    the original text; this representation is only for deterministic lexical
    search and trigram matching.
    """
    value = unicodedata.normalize("NFKC", str(text or ""))
    value = value.translate(str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه"}))
    value = value.translate(_PERSIAN_DIGITS).translate(_ARABIC_DIGITS)
    value = value.replace("\u200c", " ").replace("\u200d", " ")
    return re.sub(r"\s+", " ", value).strip()

# This shared chunker respects paragraph boundaries first and only falls
# back to a hard cut for a single paragraph that is itself bigger than one
# chunk (e.g. a wall-of-text scanned document with no real paragraph breaks).
# The ad-hoc attachment reader delegates here when ai_rag is installed so
# persistent indexing and one-off relevance selection use the same boundaries.

_DEFAULT_CHUNK_SIZE = 1000
_DEFAULT_OVERLAP = 150


def _split_paragraphs(text):
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def _split_long_paragraph(paragraph, chunk_size, overlap):
    """A paragraph bigger than chunk_size on its own: split on sentence
    boundaries where possible (Persian and Latin punctuation both), and
    only hard-cut mid-sentence as a last resort for a single run-on
    sentence longer than chunk_size."""
    sentences = re.split(r"(?<=[.!?؟۔])\s+", paragraph)
    pieces, current = [], ""
    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= chunk_size:
            current = f"{current} {sentence}".strip()
        else:
            if current:
                pieces.append(current)
            if len(sentence) > chunk_size:
                # single sentence still too long - hard cut with overlap
                start = 0
                while start < len(sentence):
                    end = start + chunk_size
                    pieces.append(sentence[start:end])
                    start = end - overlap
                current = ""
            else:
                current = sentence
    if current:
        pieces.append(current)
    return pieces


def chunk_text(text, chunk_size=_DEFAULT_CHUNK_SIZE, overlap=_DEFAULT_OVERLAP):
    """Paragraph-first chunker: greedily pack whole paragraphs into a
    chunk up to chunk_size, carry `overlap` chars of the previous
    chunk's tail into the next one (so a fact split across a chunk
    boundary is still findable from either side), and only break a
    single oversized paragraph internally (sentence-aware, see
    _split_long_paragraph)."""
    try:
        chunk_size = max(128, int(chunk_size))
        overlap = max(0, min(int(overlap), chunk_size // 2))
    except (TypeError, ValueError):
        chunk_size, overlap = _DEFAULT_CHUNK_SIZE, _DEFAULT_OVERLAP
    paragraphs = _split_paragraphs(text)
    if not paragraphs:
        return []

    chunks = []
    current = ""
    for para in paragraphs:
        candidate = f"{current}\n\n{para}".strip() if current else para
        if len(candidate) <= chunk_size:
            current = candidate
            continue

        if current:
            chunks.append(current)
        if len(para) > chunk_size:
            sub_pieces = _split_long_paragraph(para, chunk_size, overlap)
            chunks.extend(sub_pieces[:-1])
            current = sub_pieces[-1] if sub_pieces else ""
        else:
            current = para

    if current:
        chunks.append(current)

    # carry a small overlap tail from each chunk into the next
    overlapped = []
    tail = ""
    for chunk in chunks:
        piece = f"{tail}\n\n{chunk}".strip() if tail else chunk
        overlapped.append(piece)
        tail = chunk[-overlap:] if len(chunk) > overlap else chunk

    return [c for c in overlapped if c.strip()]


def chunk_blocks(blocks, chunk_size=_DEFAULT_CHUNK_SIZE, overlap=_DEFAULT_OVERLAP):
    """Chunk canonical extractor blocks while retaining source provenance.

    Blocks are packed only when their page/section/type metadata is the same;
    this keeps a citation attached to the right page or table instead of
    flattening the entire document before indexing.  The existing plain-text
    ``chunk_text`` contract remains unchanged for callers that have no
    structured extractor output.
    """
    try:
        chunk_size = max(128, int(chunk_size))
        overlap = max(0, min(int(overlap), chunk_size // 2))
    except (TypeError, ValueError):
        chunk_size, overlap = _DEFAULT_CHUNK_SIZE, _DEFAULT_OVERLAP

    result = []
    current_text = ""
    current_meta = None

    def flush():
        nonlocal current_text, current_meta
        if current_text.strip():
            result.append({"text": current_text.strip(), **(current_meta or {})})
        current_text = ""
        current_meta = None

    for block in blocks or []:
        text = str((block or {}).get("text") or "").strip()
        if not text:
            continue
        meta = {
            key: (block or {}).get(key)
            for key in (
                "page", "section", "content_type", "coordinates",
                "table", "sheet", "slide",
            )
            if (block or {}).get(key) not in (None, "")
        }
        same_source = current_meta == meta or current_meta is None
        candidate = f"{current_text}\n\n{text}".strip() if current_text else text
        if current_text and (not same_source or len(candidate) > chunk_size):
            flush()
            candidate = text
        if len(candidate) <= chunk_size:
            current_text = candidate
            current_meta = meta
            continue
        # A single source block is larger than the limit. Reuse the tested
        # sentence-aware splitter and attach the same provenance to each part.
        for piece in _split_long_paragraph(text, chunk_size, overlap):
            if current_text:
                flush()
            result.append({"text": piece.strip(), **meta})

    flush()
    return [item for item in result if item["text"]]
