import json
from pathlib import Path

import pytest

from geoptimiser.benchmark import load_judgment_set, load_query_set
from geoptimiser.chunking import ChunkConfig, chunk_document
from geoptimiser.schemas import Chunk, Heading, PageDocument

FIXTURES = Path(__file__).parent / "fixtures"


def make_doc(text: str, document_id: str = "d1", url: str = "https://x.test/p", **kw):
    return PageDocument(
        audit_id="a1",
        document_id=document_id,
        fetch_id="f-" + document_id,
        url=url,
        extraction_version="x1",
        text=text,
        **kw,
    )


def chunks_of(texts: dict[str, str]) -> list[Chunk]:
    out: list[Chunk] = []
    for doc_id, text in texts.items():
        out += chunk_document(make_doc(text, doc_id), ChunkConfig()).chunks
    return out


def chunks_from_pages(path: Path) -> list[Chunk]:
    """Chunk a fixture corpus file ({"pages": [{url, headings, text}]})."""
    pages = json.loads(path.read_text())["pages"]
    chunks: list[Chunk] = []
    for index, page in enumerate(pages):
        doc = make_doc(
            page["text"],
            f"doc{index}",
            page["url"],
            headings=tuple(Heading(level=lv, text=t) for lv, t in page["headings"]),
        )
        chunks += chunk_document(doc, ChunkConfig()).chunks
    return chunks


@pytest.fixture(scope="session")
def corpus() -> list[Chunk]:
    return chunks_from_pages(FIXTURES / "corpus.json")


@pytest.fixture(scope="session")
def queries():
    return load_query_set(FIXTURES / "queryset.json")


@pytest.fixture(scope="session")
def judgments():
    return load_judgment_set(FIXTURES / "judgments.json")
