"""``chunks.jsonl``: durable, exclusive, one validated chunk per line."""

from collections.abc import Iterable
from pathlib import Path

from geoptimiser.chunking.chunker import ChunkConfig, chunk_document, verify_chunks
from geoptimiser.jsonl import JsonlWriter, read_jsonl
from geoptimiser.schemas import Chunk, PageDocument


class ChunkVerificationError(ValueError):
    """The chunks produced for a document do not reproduce its text."""


def chunk_documents(
    documents: Iterable[PageDocument],
    path: Path,
    config: ChunkConfig | None = None,
) -> int:
    """Chunk every document into ``path`` (created exclusively); return the count.

    Each document's chunks are verified against its text before being written, so
    a chunker bug fails loudly instead of producing unfaithful evidence.
    """
    total = 0
    with JsonlWriter(path) as out:
        for doc in documents:
            result = chunk_document(doc, config)
            problems = verify_chunks(
                doc, result.chunks, complete=not result.stopped_at_limit
            )
            if problems:
                raise ChunkVerificationError(f"{doc.document_id}: {problems[0]}")
            for chunk in result.chunks:
                out.write(chunk)
            total += len(result.chunks)
    return total


def read_chunks(path: Path) -> list[Chunk]:
    return read_jsonl(path, Chunk)
