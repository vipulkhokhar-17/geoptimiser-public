"""Crawl artifacts -> audit -> chunks -> retrieval -> diagnosis -> recommendations,
joined by the agent. Needs LangGraph (skipped otherwise); uses a scripted model."""

import json
from pathlib import Path

import pytest

pytest.importorskip("langgraph")

from geoptimiser.agent import (  # noqa: E402
    AgentConfig,
    AgentContext,
    AgentRequest,
    run_agent,
)
from geoptimiser.chunking import chunk_documents, read_chunks  # noqa: E402
from geoptimiser.extraction import read_documents  # noqa: E402
from geoptimiser.features import load_inputs  # noqa: E402
from geoptimiser.features.audit import run_audit  # noqa: E402
from geoptimiser.recommendations import validate_recommendations  # noqa: E402
from geoptimiser.retrieval import HashingEmbedder, Retriever  # noqa: E402
from geoptimiser.schemas import AuditRequest  # noqa: E402
from tests.agent.conftest import FINISH, ScriptedModel, call  # noqa: E402
from tests.diagnosis.conftest import clock  # noqa: E402
from tests.features.test_integration import ORIGIN, crawl_dir  # noqa: E402, F401


def test_agent_over_the_real_pipeline(crawl_dir: Path, tmp_path: Path) -> None:  # noqa: F811
    run = run_audit(load_inputs(crawl_dir))
    documents = read_documents(crawl_dir / "extraction" / "documents.jsonl")
    chunk_documents(documents, tmp_path / "chunks.jsonl")
    chunks = read_chunks(tmp_path / "chunks.jsonl")
    retriever = Retriever(
        chunks, embedder=HashingEmbedder()
    )  # test double: plumbing only
    context = AgentContext.create(run, chunks, retriever=retriever, clock=clock)
    finding = next(f for f in context.diagnosis.findings if f.finding_id == "fnd_F022")

    script = [
        call("list_findings", severity=finding.severity),
        call("get_finding", finding_id="fnd_F022"),
        call(
            "retrieve_passages", finding_id="fnd_F022", query="pricing plans", top_k=2
        ),
        call("validate_evidence"),
        call("generate_recommendations"),
        call("validate_output"),
        FINISH,
    ]
    model = ScriptedModel(script)
    request = AgentRequest(
        audit=AuditRequest(
            audit_id=run.audit_id,
            target_domain="acme.test",
            brand_name="Acme",
            business_context="Pricing site.",
            target_audience="Buyers",
            authorization_confirmed=True,
        )  # fmt: skip
    )
    result = run_agent(
        request,
        context,
        model,
        AgentConfig(retry_delay_seconds=0),
        sleep=lambda s: None,
        clock=clock,
    )

    assert result.status == "completed", (result.reason, result.errors)
    assert result.findings_total == len(context.diagnosis.findings) > 5
    assert (result.evidence_valid, result.output_valid) == (True, True)
    assert validate_recommendations(result.recommendations, context.diagnosis) == []
    assert all(s.status == "ok" for s in result.steps), [
        s for s in result.steps if s.status != "ok"
    ]

    # Retrieval ran and its passages are grounded supplementary evidence on real pages.
    assert result.supplementary_evidence
    for ref in result.supplementary_evidence:
        assert (
            ref.source_url.startswith(ORIGIN)
            and ref.chunk_id
            and ref.char_end > ref.char_start
        )
    # The deterministic pipeline is untouched: the agent's context still validates alone.
    assert context.problems() == []
    assert json.loads(result.model_dump_json())["status"] == "completed"
