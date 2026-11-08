import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from geoptimiser.benchmark import (
    DatasetError,
    JudgmentSet,
    QuerySet,
    load_judgment_set,
    load_query_set,
)

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[2]


def queryset(**overrides: Any) -> QuerySet:
    fields: dict[str, Any] = {
        "name": "qs",
        "version": 1,
        "industry": "b2b_saas",
        "queries": [
            {"query_id": "q1", "text": "what is x", "intent": "informational"},
            {"query_id": "q2", "text": "how to y", "intent": "how_to"},
        ],
    }
    return QuerySet(**(fields | overrides))


def judgments(**overrides: Any) -> JudgmentSet:
    fields: dict[str, Any] = {
        "name": "js",
        "version": 1,
        "query_set_name": "qs",
        "query_set_version": 1,
        "origin": "fixture",
        "judgments": [
            {"query_id": "q1", "target": {"url": "https://a.test/"}, "grade": 2}
        ],
    }
    return JudgmentSet(**(fields | overrides))


def test_query_set_basics_and_lookup() -> None:
    qs = queryset()
    assert qs.get("q2").text == "how to y" and qs.review_status == "draft"
    with pytest.raises(KeyError):
        qs.get("nope")


@pytest.mark.parametrize(
    ("bad", "match"),
    [
        ({"queries": [{"query_id": "q1", "text": "a b", "intent": "how_to"}] * 2}, "unique"),
        ({"queries": [{"query_id": "q1", "text": "Same  Text", "intent": "how_to"},
                      {"query_id": "q2", "text": "same text", "intent": "how_to"}]}, "duplicate query text"),
        ({"queries": [{"query_id": "q1", "text": "  ", "intent": "how_to"}]}, ""),
        ({"queries": [{"query_id": "q1", "text": "x" * 301, "intent": "how_to"}]}, ""),
        ({"queries": [{"query_id": "q1", "text": "ok", "intent": "astrology"}]}, ""),
        ({"queries": [{"query_id": "bad id", "text": "ok", "intent": "how_to"}]}, ""),
        ({"version": 0}, ""),
        ({"review_status": "reviewed"}, "reviewed_by"),
        ({"review_status": "draft", "reviewed_by": "Ada"}, "draft"),
        ({"unknown": 1}, ""),
    ],
)  # fmt: skip
def test_query_set_validation(bad: dict[str, Any], match: str) -> None:
    with pytest.raises(ValidationError, match=match or None):
        queryset(**bad)


def test_reviewed_query_set_names_its_reviewer() -> None:
    qs = queryset(
        review_status="reviewed", reviewed_by="Ada", reviewed_on=date(2026, 1, 2)
    )
    assert qs.reviewed_by == "Ada"


def test_empty_query_set_is_valid_but_empty() -> None:
    assert queryset(queries=[]).queries == ()


def test_judgment_validation() -> None:
    assert (
        judgments().for_query("q1")[0].grade == 2 and judgments().for_query("q2") == ()
    )
    target = {"url": "https://a.test/"}
    dup = [{"query_id": "q1", "target": target, "grade": 1}] * 2
    with pytest.raises(ValidationError, match="only once"):
        judgments(judgments=dup)
    with pytest.raises(ValidationError, match="who judged"):
        judgments(origin="human")
    assert judgments(origin="human", judged_by="Ada").judged_by == "Ada"
    for grade in (-1, 4):
        with pytest.raises(ValidationError):
            judgments(judgments=[{"query_id": "q1", "target": target, "grade": grade}])
    with pytest.raises(ValidationError):
        judgments(judgments=[{"query_id": "q1", "target": {"url": ""}, "grade": 1}])


def test_same_page_different_sections_are_distinct_targets() -> None:
    url = "https://a.test/"
    items = [
        {"query_id": "q1", "target": {"url": url}, "grade": 1},
        {"query_id": "q1", "target": {"url": url, "heading": "Setup"}, "grade": 2},
    ]
    assert len(judgments(judgments=items).judgments) == 2


def test_fixture_files_load() -> None:
    qs = load_query_set(FIXTURES / "queryset.json")
    js = load_judgment_set(FIXTURES / "judgments.json")
    assert (qs.name, qs.version) == (js.query_set_name, js.query_set_version)
    assert len(qs.queries) == 6 and js.origin == "fixture"


def test_shipped_starter_benchmark_is_an_honest_draft() -> None:
    qs = load_query_set(ROOT / "configs" / "query_benchmark.json")
    assert qs.review_status == "draft" and qs.reviewed_by is None
    assert qs.industry == "b2b_saas" and len(qs.queries) == 8
    assert "not been reviewed" in (qs.description or "")


def test_loader_errors_name_the_file(tmp_path: Path) -> None:
    missing = tmp_path / "none.json"
    with pytest.raises(DatasetError, match="none.json: cannot read"):
        load_query_set(missing)
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{not json", encoding="utf-8")
    with pytest.raises(DatasetError, match="invalid JSON at line 1"):
        load_query_set(bad_json)
    invalid = tmp_path / "invalid.json"
    data = json.loads((FIXTURES / "queryset.json").read_text())
    data["queries"][0]["intent"] = "astrology"
    invalid.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(DatasetError, match=r"invalid.json: queries\.0\.intent"):
        load_query_set(invalid)
    binary = tmp_path / "bin.json"
    binary.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(DatasetError, match="cannot read"):
        load_query_set(binary)
