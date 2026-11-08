"""Passage evidence: building it from chunks and proving it is faithful."""

from collections.abc import Iterable, Mapping
from datetime import datetime

from geoptimiser.features.inputs import url_key
from geoptimiser.schemas import Chunk, EvidenceRef


class GroundingError(ValueError):
    """Evidence claims a passage that the stored chunks do not support."""


def passage_evidence(
    chunk: Chunk, retrieved_at: datetime, max_chars: int = 400
) -> EvidenceRef:
    """Evidence quoting the start of ``chunk``, located exactly in the source text.

    The snippet is a prefix of the chunk (at most ``max_chars``), so ``char_end``
    is adjusted to match: the locator always describes the quoted text itself.
    """
    snippet = chunk.text[:max_chars]
    return EvidenceRef(
        evidence_id=f"ev_{chunk.chunk_id}",
        source_url=str(chunk.url),
        snippet=snippet,
        source_type="website",
        retrieved_at=retrieved_at,
        audit_id=chunk.audit_id,
        chunk_id=chunk.chunk_id,
        document_id=chunk.document_id,
        char_start=chunk.char_start,
        char_end=chunk.char_start + len(snippet),
    )


def grounding_problems(
    evidence: Iterable[EvidenceRef], audit_id: str, chunks: Mapping[str, Chunk]
) -> list[str]:
    """Why located evidence is not supported by ``chunks``; empty means faithful.

    Evidence without a locator is not examined here (it observes a measurement).
    """
    problems = []
    for ref in evidence:
        if ref.chunk_id is None:
            continue
        label = ref.evidence_id
        chunk = chunks.get(ref.chunk_id)
        if chunk is None:
            problems.append(f"{label}: chunk {ref.chunk_id!r} does not exist")
            continue
        if ref.audit_id != audit_id or chunk.audit_id != audit_id:
            problems.append(f"{label}: belongs to a different audit")
        if ref.document_id != chunk.document_id:
            problems.append(f"{label}: document differs from the chunk's")
        if url_key(ref.source_url) != url_key(str(chunk.url)):
            problems.append(f"{label}: source_url differs from the chunk's page")
        assert ref.char_start is not None and ref.char_end is not None
        if not chunk.char_start <= ref.char_start < ref.char_end <= chunk.char_end:
            problems.append(f"{label}: range lies outside the chunk")
            continue
        offset = ref.char_start - chunk.char_start
        if chunk.text[offset : offset + len(ref.snippet)] != ref.snippet:
            problems.append(f"{label}: snippet is not the quoted source text")
    return problems


def validate_grounding(
    evidence: Iterable[EvidenceRef], audit_id: str, chunks: Mapping[str, Chunk]
) -> None:
    problems = grounding_problems(evidence, audit_id, chunks)
    if problems:
        raise GroundingError(problems[0])
