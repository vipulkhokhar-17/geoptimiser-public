"""The whole offline chain: crawl artifacts to recommendations."""

import json
from pathlib import Path

from geoptimiser.chunking import chunk_documents, read_chunks
from geoptimiser.diagnosis import diagnose
from geoptimiser.extraction import read_documents
from geoptimiser.features import load_inputs
from geoptimiser.features.audit import run_audit
from geoptimiser.recommendations import (
    TemplateGenerator,
    validate_recommendations,
    write_outputs,
)
from geoptimiser.retrieval import HashingEmbedder, Retriever
from tests.diagnosis.conftest import clock
from tests.features.test_integration import crawl_dir  # noqa: F401


def test_end_to_end_chain(crawl_dir: Path, tmp_path: Path) -> None:  # noqa: F811
    run = run_audit(load_inputs(crawl_dir))
    documents = read_documents(crawl_dir / "extraction" / "documents.jsonl")
    chunk_documents(documents, tmp_path / "chunks.jsonl")
    chunks = read_chunks(tmp_path / "chunks.jsonl")
    retriever = Retriever(chunks, embedder=HashingEmbedder())

    diagnosis = diagnose(run, chunks, retriever=retriever, clock=clock)
    result = TemplateGenerator().generate(diagnosis, clock)

    assert result.recommendations
    assert validate_recommendations(result, diagnosis) == []
    assert {r.expected_impact_direction for r in result.recommendations} == {
        "uncertain"
    }
    known = {f.finding_id for f in run.findings}
    assert any(set(r.finding_ids) & known for r in result.recommendations)

    write_outputs(tmp_path / "out", diagnosis, result)
    written = json.loads((tmp_path / "out" / "recommendations.json").read_text())
    assert [r["recommendation_id"] for r in written["recommendations"]] == [
        r.recommendation_id for r in result.recommendations
    ]
    again = TemplateGenerator().generate(
        diagnose(run, chunks, retriever=retriever, clock=clock), clock
    )
    assert again.model_dump_json() == result.model_dump_json()
