"""Crawl artifacts -> extraction -> audit -> chunks -> retrieval -> diagnosis."""

from pathlib import Path

from geoptimiser.chunking import chunk_documents, read_chunks
from geoptimiser.diagnosis import diagnose, validate_diagnosis, write_diagnosis
from geoptimiser.extraction import read_documents
from geoptimiser.features import load_inputs
from geoptimiser.features.audit import run_audit
from geoptimiser.retrieval import HashingEmbedder, Retriever
from tests.diagnosis.conftest import clock
from tests.features.test_integration import ORIGIN, crawl_dir  # noqa: F401


def test_full_chain_on_extracted_pages(crawl_dir: Path, tmp_path: Path) -> None:  # noqa: F811
    run = run_audit(load_inputs(crawl_dir))
    documents = read_documents(crawl_dir / "extraction" / "documents.jsonl")
    chunk_path = tmp_path / "chunks.jsonl"
    assert chunk_documents(documents, chunk_path) > 0
    chunks = read_chunks(chunk_path)

    retriever = Retriever(chunks, embedder=HashingEmbedder())
    diagnosis = diagnose(run, chunks, retriever=retriever, clock=clock)

    assert validate_diagnosis(diagnosis, run, chunks) == []
    assert {f.finding_id for f in run.findings} <= {
        f.finding_id for f in diagnosis.findings
    }
    assert diagnosis.stats.passages_attached > 0
    located = [e for e in diagnosis.evidence.values() if e.chunk_id]
    assert located and all(e.source_url.startswith(ORIGIN) for e in located)

    write_diagnosis(tmp_path / "findings.json", diagnosis)
    # The same inputs give the same document: reproducible apart from nothing.
    again = diagnose(run, chunks, retriever=retriever, clock=clock)
    assert again.model_dump_json() == diagnosis.model_dump_json()
