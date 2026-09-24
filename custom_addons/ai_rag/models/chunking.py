import re

# Deliberately NOT the naive fixed-offset char slicer already used in
# company_ai_demo/models/file_reader.py's chunk_text() (which just cuts
# every 800 chars regardless of word/sentence boundaries - fine for a
# one-off "rank 4 excerpts from THIS attachment" use case, not accurate
# enough to be the actual persistent search index for the whole
# document library). This one respects paragraph boundaries first and
# only falls back to a hard cut for a single paragraph that is itself
# bigger than one chunk (e.g. a wall-of-text scanned document with no
# real paragraph breaks).

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
