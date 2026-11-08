"""Chunking real extractor output (HTML fixtures through the Stage 02 pipeline)."""

import pytest

from geoptimiser.chunking import ChunkConfig, chunk_document, verify_chunks
from geoptimiser.extraction import extract_fetch
from geoptimiser.schemas import PageDocument
from tests.extraction.conftest import fixture_html, store  # noqa: F401
from tests.extraction.test_pipeline import make_fetch


@pytest.mark.parametrize("name", ["full_page", "rich_page", "malformed", "empty"])
def test_extracted_fixtures_chunk_and_verify(store, fixture_html, name):  # noqa: F811
    document = extract_fetch(make_fetch(store, fixture_html(name)), store)
    assert isinstance(document, PageDocument)
    for config in (ChunkConfig(), ChunkConfig(max_chars=100, overlap_chars=30)):
        result = chunk_document(document, config)
        assert verify_chunks(document, result.chunks) == []
        assert all(c.document_id == document.document_id for c in result.chunks)


def test_truncated_source_marks_every_chunk(store, fixture_html):  # noqa: F811
    fetch = make_fetch(store, fixture_html("full_page"), truncated=True)
    document = extract_fetch(fetch, store)
    assert isinstance(document, PageDocument) and document.source_truncated
    chunks = chunk_document(document).chunks
    assert chunks and all(c.source_truncated for c in chunks)


def test_headings_from_a_real_page_form_paths(store, fixture_html):  # noqa: F811
    document = extract_fetch(make_fetch(store, fixture_html("full_page")), store)
    assert isinstance(document, PageDocument)
    paths = {c.heading_path for c in chunk_document(document).chunks}
    assert any(p and p[0] == "Pricing plans" for p in paths)
