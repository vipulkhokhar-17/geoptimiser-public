from pathlib import Path

import pytest

from geoptimiser.benchmark import (
    DatasetMismatch,
    JudgmentSet,
    Target,
    evaluate_rankings,
    load_judgment_set,
    load_query_set,
)

FIXTURES = Path(__file__).parent / "fixtures"
CORPUS = {
    "https://x.test/what-is": ["c1", "c2"],
    "https://x.test/guide": ["c3"],
    "https://x.test/approvals": ["c4"],
    "https://x.test/pricing": ["c5"],
}  # the page for q3 ("missing-page") is deliberately absent


def resolve(target: Target) -> dict[str, int]:
    if target.heading:  # section-level label: only the first chunk of the page
        return {CORPUS.get(target.url, [""])[0]: 1} if target.url in CORPUS else {}
    return {chunk: 1 for chunk in CORPUS.get(target.url, [])}


def run(rankings, **kw):  # type: ignore[no-untyped-def]
    qs = load_query_set(FIXTURES / "queryset.json")
    js = load_judgment_set(FIXTURES / "judgments.json")
    return evaluate_rankings(qs, js, rankings, ks=(1, 3), resolve=resolve, **kw)


def test_scores_and_exclusions_are_reported_consistently() -> None:
    report = run(
        {
            "q1": ["c9", "c1"],
            "q2": ["c4"],
            "q3": ["c1"],
            "q4": ["c5", "c1"],
            "q5": ["c1"],
        }
    )

    assert report.n_queries == 6 and report.n_evaluated == 3
    by_id = {q.query_id: q for q in report.per_query}
    # q1: relevant = c1,c2 (grade 3) and c3 (grade 1); ranking c9,c1 -> RR 1/2
    assert by_id["q1"].scores["mrr"] == 0.5
    assert by_id["q1"].scores["recall@3"] == pytest.approx(1 / 3)  # c1 of {c1,c2,c3}
    assert by_id["q2"].scores["mrr"] == 1.0 and by_id["q4"].scores["recall@1"] == 1.0
    reasons = {e.query_id: e.reason for e in report.excluded}
    assert reasons == {
        "q3": "unresolvable_targets",  # its only relevant label points at a missing page
        "q5": "no_relevant_labels",  # only grade-0 labels: undefined, not zero
        "q6": "no_judgments",  # unlabelled: unknown, not zero
    }
    assert report.means is not None
    assert report.means["mrr"] == pytest.approx((0.5 + 1.0 + 1.0) / 3)


def test_issues_list_label_problems() -> None:
    report = run({"q1": ["c1"], "ghost": ["c1"]})
    issues = " | ".join(report.issues)
    assert "unknown query 'q9'" in issues  # a judgment for a query that does not exist
    assert (
        "unknown query 'ghost'" in issues
    )  # a ranking for a query that does not exist
    assert "missing-page" in issues  # a label whose target is not in the corpus


def test_missing_run_is_excluded_not_scored_zero() -> None:
    report = run({"q1": ["c1"]})
    reasons = {e.query_id: e.reason for e in report.excluded}
    assert reasons["q2"] == "no_ranking" and reasons["q4"] == "no_ranking"
    assert {q.query_id for q in report.per_query} == {"q1"}


def test_an_empty_ranking_is_a_real_zero() -> None:
    report = run({"q1": [], "q2": [], "q4": []})
    assert report.means is not None and report.means["mrr"] == 0.0
    assert all(q.retrieved == 0 for q in report.per_query)


def test_no_evaluable_queries_gives_no_means() -> None:
    report = run({})
    assert report.n_evaluated == 0 and report.means is None


def test_fixture_data_never_claims_real_world_quality() -> None:
    report = run({"q1": ["c1"]})
    assert report.judgment_origin == "fixture" and report.real_world_claim is False
    assert report.query_set_review_status == "draft"


def test_real_world_claim_needs_human_labels_and_a_reviewed_query_set() -> None:
    qs = load_query_set(FIXTURES / "queryset.json")
    js = load_judgment_set(FIXTURES / "judgments.json")
    human = JudgmentSet.model_validate(
        js.model_dump() | {"origin": "human", "judged_by": "Ada"}
    )
    assert evaluate_rankings(qs, human, {}).real_world_claim is False  # draft queries
    reviewed = type(qs).model_validate(
        qs.model_dump()
        | {
            "review_status": "reviewed",
            "reviewed_by": "Ada",
            "reviewed_on": "2026-01-01",
        }
    )
    assert evaluate_rankings(reviewed, human, {}).real_world_claim is True


def test_judgments_for_another_dataset_version_are_refused() -> None:
    qs = load_query_set(FIXTURES / "queryset.json")
    js = load_judgment_set(FIXTURES / "judgments.json")
    for change in ({"query_set_version": 2}, {"query_set_name": "other"}):
        stale = JudgmentSet.model_validate(js.model_dump() | change)
        with pytest.raises(DatasetMismatch):
            evaluate_rankings(qs, stale, {})


def test_default_resolver_treats_the_url_as_the_item() -> None:
    qs = load_query_set(FIXTURES / "queryset.json")
    js = load_judgment_set(FIXTURES / "judgments.json")
    report = evaluate_rankings(qs, js, {"q2": ["https://x.test/approvals"]}, ks=(1,))
    assert report.per_query[0].scores["recall@1"] == 1.0


def test_invalid_k_values_are_rejected_up_front() -> None:
    qs = load_query_set(FIXTURES / "queryset.json")
    js = load_judgment_set(FIXTURES / "judgments.json")
    with pytest.raises(ValueError, match="positive integer"):
        evaluate_rankings(qs, js, {}, ks=(0,))


def test_report_is_machine_readable_with_versions() -> None:
    report = run({"q1": ["c1"]})
    data = report.model_dump(mode="json")
    assert data["schema_version"] == 1 and data["evaluation_version"] == 1
    assert (data["query_set_name"], data["query_set_version"]) == ("fixture_queries", 1)
    assert (data["judgment_set_name"], data["judgment_set_version"]) == (
        "fixture_judgments",
        1,
    )
    assert type(report).model_validate_json(report.model_dump_json()) == report
