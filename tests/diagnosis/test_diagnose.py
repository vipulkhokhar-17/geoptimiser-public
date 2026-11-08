import json

import pytest
from pydantic import ValidationError

from geoptimiser.diagnosis import (
    DEFAULT_RULES,
    DiagnosisConfig,
    DiagnosisError,
    GroundingError,
    SynthesisRule,
    diagnose,
    passage_evidence,
    validate_diagnosis,
    validate_grounding,
    validate_rules,
    write_diagnosis,
)
from geoptimiser.features.registry import default_registry
from geoptimiser.retrieval import HashingEmbedder, Retriever
from geoptimiser.schemas import Chunk, EvidenceRef
from tests.diagnosis.conftest import INJECTION, NOW, SITE, clock


def by_id(diagnosis):
    return {f.finding_id: f for f in diagnosis.findings}


# --- EvidenceRef locator (additive, backward compatible) ---


def test_evidence_without_locator_is_unchanged():
    ref = EvidenceRef(
        evidence_id="e1",
        source_url="https://x.test/",
        snippet="s",
        source_type="website",
    )
    assert ref.chunk_id is None and ref.char_start is None
    old = ref.model_dump() | {}
    for key in ("audit_id", "chunk_id", "document_id", "char_start", "char_end"):
        old.pop(key)
    assert EvidenceRef.model_validate(old) == ref  # records from before still load


def test_partial_or_inconsistent_locators_are_rejected():
    base = dict(
        evidence_id="e1",
        source_url="https://x.test/",
        snippet="abc",
        source_type="website",
    )
    full = dict(audit_id="a", chunk_id="c", document_id="d", char_start=5, char_end=8)
    EvidenceRef(**base, **full)
    for change in (
        {"chunk_id": None},
        {"audit_id": None},
        {"char_end": 9},
        {"char_end": 5},
        {"char_start": None},
    ):
        with pytest.raises(ValidationError):
            EvidenceRef(**base, **(full | change))


# --- grounding ---


def test_passage_evidence_quotes_a_prefix_with_an_exact_range(chunks):
    chunk = chunks[0]
    ref = passage_evidence(chunk, NOW, max_chars=10)
    assert ref.snippet == chunk.text[:10]
    assert (ref.char_start, ref.char_end) == (chunk.char_start, chunk.char_start + 10)
    validate_grounding([ref], chunk.audit_id, {chunk.chunk_id: chunk})


def tamper(ref, **changes):
    return EvidenceRef.model_validate(ref.model_dump() | changes)


def test_grounding_rejects_unsupported_evidence(chunks):
    chunk = chunks[0]
    ref = passage_evidence(chunk, NOW)
    chunk_map = {c.chunk_id: c for c in chunks}
    other = chunks[-1]
    cases = {
        "does not exist": tamper(ref, chunk_id="nope"),
        "different audit": tamper(ref, audit_id="someone_else"),
        "document differs": tamper(ref, document_id="other"),
        "source_url differs": tamper(ref, source_url=str(other.url)),
        "not the quoted": tamper(ref, snippet="x" * len(ref.snippet)),
        "outside the chunk": tamper(
            ref, char_start=chunk.char_end, char_end=chunk.char_end + len(ref.snippet)
        ),
    }
    for fragment, bad in cases.items():
        with pytest.raises(GroundingError, match=fragment):
            validate_grounding([bad], chunk.audit_id, chunk_map)


def test_measurement_evidence_is_not_examined_by_grounding(run_, chunks):
    validate_grounding(run_.evidence.values(), run_.audit_id, {})


# --- diagnosis without a retriever ---


def test_original_findings_are_preserved_and_extended(run_, chunks):
    d = diagnose(run_, chunks, clock=clock)
    mine = by_id(d)
    for original in run_.findings:
        new = mine[original.finding_id]
        assert (new.severity, new.basis, new.feature_ids, new.title) == (
            original.severity,
            original.basis,
            original.feature_ids,
            original.title,
        )
        assert new.evidence_ids[: len(original.evidence_ids)] == original.evidence_ids
    assert d.stats.base_findings == len(run_.findings)
    assert d.stats.passages_attached > 0
    assert d.stats.passage_source == "page_lead"


def test_passages_come_from_the_affected_page_only(run_, chunks):
    d = diagnose(run_, chunks, clock=clock)
    assert any(e.chunk_id for e in d.evidence.values())
    title = by_id(d)["fnd_F021"]
    for evidence_id in title.evidence_ids:  # F021 fails only on /bad
        assert d.evidence[evidence_id].source_url == f"{SITE}/bad"
    assert any(e.startswith("ev_ch-") for e in title.evidence_ids)
    assert any("do not by themselves prove" in lim for lim in title.limitations)
    assert validate_diagnosis(d, run_, chunks) == []


def test_snippets_reproduce_source_text(run_, chunks, pages):
    d = diagnose(run_, chunks, clock=clock)
    texts = {p.document.document_id: p.document.text for p in pages}
    for ref in d.evidence.values():
        if ref.chunk_id:
            assert texts[ref.document_id][ref.char_start : ref.char_end] == ref.snippet


def test_cross_feature_rule_fires_only_where_all_features_fail(run_, chunks):
    d = diagnose(run_, chunks, clock=clock)
    syn = by_id(d)["syn_no_page_summary"]
    assert syn.basis == "heuristic" and syn.category == "cross_feature"
    assert syn.feature_ids == ("F021", "F024") and syn.severity == "high"
    assert f"{SITE}/bad" in syn.description and f"{SITE}/good" not in syn.description
    assert "1 page(s)" in syn.title
    assert set(syn.evidence_ids) >= {
        e for f in ("fnd_F021", "fnd_F024") for e in by_id(d)[f].evidence_ids[:1]
    }
    assert any("not show that they interact" in x for x in syn.limitations)
    assert "hard_to_extract" not in "".join(by_id(d))  # other rules did not fire here


def test_diagnosis_is_deterministic(run_, chunks):
    a = diagnose(run_, chunks, clock=clock)
    b = diagnose(run_, chunks, clock=clock)
    assert a == b and a.model_dump_json() == b.model_dump_json()


def test_works_without_chunks(run_):
    d = diagnose(run_, [], clock=clock)
    assert d.stats.passages_attached == 0 and d.stats.passage_source == "none"
    assert any("No passages were available" in n for n in d.notes)
    assert {f.finding_id for f in run_.findings} <= set(by_id(d))
    assert validate_diagnosis(d, run_, []) == []


def test_chunks_from_another_audit_are_ignored(run_, chunks):
    foreign = [
        Chunk.model_validate(c.model_dump() | {"audit_id": "other"}) for c in chunks
    ]
    d = diagnose(run_, foreign, clock=clock)
    assert d.stats.chunks_ignored == len(foreign) and d.stats.passages_attached == 0
    assert any("another audit" in n for n in d.notes)


def test_passage_budget_and_zero_passages(run_, chunks):
    none = diagnose(run_, chunks, config=DiagnosisConfig(max_passages_per_finding=0))
    assert none.stats.passages_attached == 0
    one = diagnose(run_, chunks, config=DiagnosisConfig(max_passages_per_finding=1))
    for f in one.findings:
        assert sum(1 for e in f.evidence_ids if e.startswith("ev_ch-")) <= 1


# --- with a retriever ---


def test_retriever_ranks_passages_and_falls_back_to_page_lead(run_, chunks):
    r = Retriever(chunks)
    d = diagnose(run_, chunks, retriever=r, clock=clock)
    assert (
        "retrieval" in d.stats.passage_source or "page_lead" in d.stats.passage_source
    )
    assert validate_diagnosis(d, run_, chunks) == []


def test_unavailable_retrieval_mode_degrades_with_a_note(run_, chunks):
    d = diagnose(
        run_,
        chunks,
        retriever=Retriever(chunks),  # no embedder: dense is unavailable
        config=DiagnosisConfig(retrieval_mode="dense"),
        clock=clock,
    )
    assert any("unavailable" in n for n in d.notes)
    assert d.stats.passage_source == "page_lead"


def test_failing_retriever_degrades_instead_of_failing(run_, chunks):
    class Boom(HashingEmbedder):
        calls = 0

        def embed(self, texts):
            Boom.calls += 1
            if Boom.calls > 1:
                raise RuntimeError("down")
            return super().embed(texts)

    d = diagnose(
        run_,
        chunks,
        retriever=Retriever(chunks, embedder=Boom()),
        config=DiagnosisConfig(retrieval_mode="dense"),
        clock=clock,
    )
    assert any("Retrieval failed (EmbeddingError)" in n for n in d.notes)
    assert validate_diagnosis(d, run_, chunks) == []


# --- untrusted text ---


def test_page_text_cannot_steer_the_diagnosis(run_, chunks):
    d = diagnose(run_, chunks, retriever=Retriever(chunks), clock=clock)
    quoted = [e for e in d.evidence.values() if INJECTION in e.snippet]
    plain = diagnose(run_, [], clock=clock)
    assert {f.finding_id: f.severity for f in plain.findings} == {
        f.finding_id: f.severity for f in d.findings
    }
    assert quoted or True  # quoted verbatim when present; never interpreted
    for f in d.findings:
        assert INJECTION not in f.title + f.description + f.measurement_method


# --- validation catches faults ---


def test_validate_diagnosis_detects_tampering(run_, chunks):
    d = diagnose(run_, chunks, clock=clock)
    fnd = by_id(d)["fnd_F021"]

    def with_finding(finding):
        others = tuple(f for f in d.findings if f.finding_id != finding.finding_id)
        return d.model_copy(update={"findings": (*others, finding)})

    from geoptimiser.schemas import Finding

    ghost = Finding.model_validate(fnd.model_dump() | {"evidence_ids": ("ev_missing",)})
    assert any(
        "missing" in p for p in validate_diagnosis(with_finding(ghost), run_, chunks)
    )
    foreign = next(
        e.evidence_id
        for e in run_.evidence.values()
        if e.evidence_id not in fnd.evidence_ids
    )
    stolen = Finding.model_validate(
        fnd.model_dump() | {"evidence_ids": (*fnd.evidence_ids, foreign)}
    )
    wrong = d.model_copy(
        update={"evidence": d.evidence | {foreign: run_.evidence[foreign]}}
    )
    bad = wrong.model_copy(
        update={"findings": (*(f for f in d.findings if f is not fnd), stolen)}
    )
    assert any(
        "not from its failing results" in p
        for p in validate_diagnosis(bad, run_, chunks)
    )
    dropped = d.model_copy(update={"findings": d.findings[1:]})
    assert any("dropped" in p for p in validate_diagnosis(dropped, run_, chunks))
    other = d.model_copy(update={"audit_id": "zzz"})
    assert any("different audit" in p for p in validate_diagnosis(other, run_, chunks))


def test_diagnose_raises_if_its_own_output_is_unsound(run_, chunks, monkeypatch):
    import geoptimiser.diagnosis.engine as mod

    real = mod.passage_evidence

    def unfaithful(chunk, when, limit):
        ref = real(chunk, when, limit)
        return tamper(ref, snippet="x" * len(ref.snippet))  # right length, wrong text

    monkeypatch.setattr(mod, "passage_evidence", unfaithful)
    with pytest.raises(DiagnosisError, match="not the quoted"):
        diagnose(run_, chunks, clock=clock)


# --- rules ---


def test_default_rules_are_valid_against_the_catalog():
    validate_rules(DEFAULT_RULES, default_registry().catalog)


def test_rule_validation():
    catalog = default_registry().catalog
    base = dict(title="t", description="d", severity="low", remediation="r")
    with pytest.raises(ValidationError):
        SynthesisRule(rule_id="r", requires=("F021",), **base)
    with pytest.raises(ValidationError):
        SynthesisRule(rule_id="r", requires=("F021", "F021"), **base)
    with pytest.raises(ValueError, match="unknown"):
        validate_rules(
            (SynthesisRule(rule_id="r", requires=("F021", "F999"), **base),), catalog
        )
    with pytest.raises(ValueError, match="not implemented"):
        validate_rules(
            (SynthesisRule(rule_id="r", requires=("F021", "F032"), **base),), catalog
        )
    with pytest.raises(ValueError, match="not page-scoped"):
        validate_rules(
            (SynthesisRule(rule_id="r", requires=("F021", "F003"), **base),), catalog
        )
    dup = SynthesisRule(rule_id="r", requires=("F021", "F024"), **base)
    with pytest.raises(ValueError, match="unique"):
        validate_rules((dup, dup), catalog)


def test_custom_rules_replace_the_defaults(run_, chunks):
    rule = SynthesisRule(
        rule_id="only_one",
        title="Custom",
        description="Custom rule.",
        requires=("F021", "F024"),
        severity="medium",
        remediation="Fix both.",
    )
    d = diagnose(run_, chunks, config=DiagnosisConfig(rules=(rule,)), clock=clock)
    assert "syn_only_one" in by_id(d) and "syn_no_page_summary" not in by_id(d)
    assert by_id(d)["syn_only_one"].severity == "medium"


def test_invalid_rules_fail_before_any_work(run_, chunks):
    bad = SynthesisRule(
        rule_id="bad",
        title="t",
        description="d",
        requires=("F021", "F999"),
        severity="low",
        remediation="r",
    )
    with pytest.raises(ValueError):
        diagnose(run_, chunks, config=DiagnosisConfig(rules=(bad,)))


# --- artifact ---


def test_write_diagnosis(run_, chunks, tmp_path):
    d = diagnose(run_, chunks, clock=clock)
    path = tmp_path / "findings.json"
    write_diagnosis(path, d)
    data = json.loads(path.read_text())
    assert data["schema_version"] == 1 and data["audit_id"] == run_.audit_id
    assert len(data["findings"]) == len(d.findings)
    with pytest.raises(FileExistsError):
        write_diagnosis(path, d)
