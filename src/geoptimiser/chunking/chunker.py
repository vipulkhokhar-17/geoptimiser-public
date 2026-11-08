"""Structure-aware, offset-exact chunking of extracted pages (Stage 07, ADR-0018).

A page is split at its heading lines into sections; a section longer than
``max_chars`` is cut at the best available boundary (line, sentence, word, and only
then a hard cut) with a bounded overlap. Every chunk is a verbatim slice of
``PageDocument.text`` and records its exact character range, so ``verify_chunks``
can prove that the chunks reproduce the source. Nothing here calls a model.
"""

import hashlib
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Self

from pydantic import Field, model_validator

from geoptimiser.schemas import Chunk, PageDocument, SchemaModel

CHUNKER_VERSION = 1
_SENTENCE_END = re.compile(r"[.!?][\"')\]]*\s")


class ChunkConfig(SchemaModel):
    max_chars: int = Field(default=1200, ge=100, le=8000)
    overlap_chars: int = Field(default=150, ge=0)
    max_chunks_per_document: int = Field(default=500, ge=1, le=10_000)

    @model_validator(mode="after")
    def _check_overlap(self) -> Self:
        if self.overlap_chars > self.max_chars // 2:
            raise ValueError("overlap_chars must be at most half of max_chars")
        return self


class ChunkingResult(SchemaModel):
    """Chunks plus an explicit statement of whether the whole text was covered."""

    document_id: str
    chunks: tuple[Chunk, ...]
    # True when max_chunks_per_document stopped chunking before the end of the text.
    stopped_at_limit: bool = False
    covered_until: int = 0  # end offset of the last chunk (0 for an empty text)
    text_length: int = 0


@dataclass(frozen=True)
class _Section:
    start: int
    end: int
    path: tuple[str, ...]


def _line_starts(text: str) -> list[int]:
    starts, pos = [0], 0
    for line in text.split("\n")[:-1]:
        pos += len(line) + 1
        starts.append(pos)
    return starts


def _sections(doc: PageDocument) -> list[_Section]:
    """Sections delimited by heading lines found, in order, in ``doc.text``.

    A heading that cannot be found as a whole line is ignored (never guessed at),
    which at worst merges two sections.
    """
    text = doc.text
    lines = text.split("\n")
    starts = _line_starts(text)
    marks: list[tuple[int, int, str]] = []  # (line index, level, text)
    cursor = 0
    for heading in doc.headings:
        wanted = " ".join(heading.text.split())
        if not wanted:
            continue
        for index in range(cursor, len(lines)):
            if lines[index] == wanted:
                marks.append((index, heading.level, wanted))
                cursor = index + 1
                break
    sections: list[_Section] = []
    if not marks or starts[marks[0][0]] > 0:
        end = starts[marks[0][0]] if marks else len(text)
        sections.append(_Section(0, end, ()))
    stack: list[tuple[int, str]] = []
    for position, (index, level, title) in enumerate(marks):
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        end = starts[marks[position + 1][0]] if position + 1 < len(marks) else len(text)
        sections.append(_Section(starts[index], end, tuple(t for _, t in stack)))
    return sections


def _trim(text: str, start: int, end: int) -> tuple[int, int] | None:
    """Narrow [start, end) to exclude surrounding whitespace; None if all blank."""
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return (start, end) if start < end else None


def _break_point(text: str, pos: int, limit: int) -> int:
    """Best cut in (pos, limit]: newline, else sentence end, else space, else limit."""
    window = text[pos:limit]
    cut = window.rfind("\n")
    if cut > 0:
        return pos + cut
    ends = [m.end() for m in _SENTENCE_END.finditer(window)]
    if ends and ends[-1] > 0:
        return pos + ends[-1]
    cut = window.rfind(" ")
    if cut > 0:
        return pos + cut
    return limit


def _split_section(
    text: str, section: _Section, config: ChunkConfig
) -> Iterator[tuple[int, int, int]]:
    """Yield (start, end, overlap) spans covering the section's non-blank text."""
    pos, last_end = section.start, None
    while pos < section.end:
        limit = min(pos + config.max_chars, section.end)
        cut = limit if limit == section.end else _break_point(text, pos, limit)
        span = _trim(text, pos, cut)
        if span is not None and (last_end is None or span[1] > last_end):
            start, end = span
            yield start, end, (max(0, last_end - start) if last_end else 0)
            last_end = end
        if cut >= section.end:
            return
        nxt = cut - config.overlap_chars if config.overlap_chars else cut
        nxt = max(nxt, pos + 1)
        # begin the overlap at a word boundary, never inside a word
        if config.overlap_chars and not text[nxt - 1].isspace():
            while nxt < cut and not text[nxt].isspace():
                nxt += 1
        pos = nxt


def chunk_id(document_id: str, char_start: int, char_end: int, version: int) -> str:
    """Stable id: one document, span and chunker version always give the same id."""
    digest = hashlib.sha256(
        f"{version}|{document_id}|{char_start}|{char_end}".encode()
    ).hexdigest()[:16]
    return f"ch-{digest}"


def chunk_document(
    doc: PageDocument, config: ChunkConfig | None = None
) -> ChunkingResult:
    """Chunk one page. An empty or whitespace-only text yields no chunks."""
    config = config or ChunkConfig()
    text = doc.text
    chunks: list[Chunk] = []
    stopped = False
    for section in _sections(doc):
        for start, end, overlap in _split_section(text, section, config):
            if len(chunks) >= config.max_chunks_per_document:
                stopped = True
                break
            piece = text[start:end]
            chunks.append(
                Chunk(
                    audit_id=doc.audit_id,
                    chunk_id=chunk_id(doc.document_id, start, end, CHUNKER_VERSION),
                    document_id=doc.document_id,
                    fetch_id=doc.fetch_id,
                    url=doc.url,
                    chunker_version=CHUNKER_VERSION,
                    ordinal=len(chunks),
                    heading_path=section.path,
                    text=piece,
                    char_start=start,
                    char_end=end,
                    text_sha256=hashlib.sha256(piece.encode("utf-8")).hexdigest(),
                    overlap_chars=overlap,
                    source_truncated=doc.source_truncated,
                )
            )
        if stopped:
            break
    return ChunkingResult(
        document_id=doc.document_id,
        chunks=tuple(chunks),
        stopped_at_limit=stopped,
        covered_until=chunks[-1].char_end if chunks else 0,
        text_length=len(text),
    )


def verify_chunks(
    doc: PageDocument, chunks: Sequence[Chunk], *, complete: bool = True
) -> list[str]:
    """Problems that stop ``chunks`` from reproducing ``doc.text``; empty means sound.

    Checks identity, exact slices, ordering, unique ids and that every non-blank
    character is covered (up to the last chunk when ``complete`` is False).
    """
    problems: list[str] = []
    text = doc.text
    seen: set[str] = set()
    covered = [False] * len(text)
    previous = -1
    for chunk in chunks:
        label = chunk.chunk_id
        if chunk.chunk_id in seen:
            problems.append(f"{label}: duplicate chunk_id")
        seen.add(chunk.chunk_id)
        if (chunk.audit_id, chunk.document_id, chunk.fetch_id) != (
            doc.audit_id,
            doc.document_id,
            doc.fetch_id,
        ) or str(chunk.url) != str(doc.url):
            problems.append(f"{label}: identity does not match the document")
        if chunk.char_end > len(text):
            problems.append(f"{label}: range ends beyond the source text")
            continue
        if text[chunk.char_start : chunk.char_end] != chunk.text:
            problems.append(f"{label}: text differs from the source slice")
        expected = chunk_id(
            doc.document_id, chunk.char_start, chunk.char_end, chunk.chunker_version
        )
        if chunk.chunk_id != expected:
            problems.append(f"{label}: chunk_id is not the stable id for its span")
        if chunk.ordinal != previous + 1:
            problems.append(f"{label}: ordinal {chunk.ordinal} out of sequence")
        previous = chunk.ordinal
        if chunk.source_truncated != doc.source_truncated:
            problems.append(f"{label}: source_truncated differs from the document")
        for i in range(chunk.char_start, chunk.char_end):
            covered[i] = True
    limit = max((c.char_end for c in chunks), default=0) if not complete else len(text)
    missing = [
        i
        for i in range(min(limit, len(text)))
        if not covered[i] and not text[i].isspace()
    ]
    if missing:
        problems.append(
            f"{len(missing)} non-blank characters not covered (first at {missing[0]})"
        )
    return problems
