"""The corpus framework: schema, honesty about what the corpus is, and metrics."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from geoptimiser.validation.corpus import (
    Label,
    Manifest,
    Snapshot,
    evaluate_corpus,
    load_manifest,
)

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "benchmarks" / "corpus" / "manifest.json"
RESULTS = ROOT / "docs" / "validation" / "results" / "corpus_initial.json"


@pytest.fixture(scope="module")
def manifest() -> Manifest:
    return load_manifest(MANIFEST)


@pytest.fixture(scope="module")
def evaluation(manifest: Manifest) -> dict:
    return evaluate_corpus(manifest, MANIFEST.parent)


def test_the_shipped_corpus_does_not_pretend_to_be_real_world(
    manifest: Manifest,
) -> None:
    assert manifest.real_world is False
    assert all(not s.real_world for s in manifest.snapshots)
    assert all(
        lab.kind == "oracle" for s in manifest.snapshots for lab in s.labels.values()
    ), "no human label may be claimed that no human assigned"
    assert all(
        lab.second_label is None
        for s in manifest.snapshots
        for lab in s.labels.values()
    )


def test_every_snapshot_file_exists_and_ids_are_unique(manifest: Manifest) -> None:
    ids = [s.snapshot_id for s in manifest.snapshots]
    assert len(set(ids)) == len(ids)
    for s in manifest.snapshots:
        assert (MANIFEST.parent / s.file).is_file(), s.file
        assert s.snapshot_date and s.page_type and s.source


def test_the_evaluation_reports_its_own_limits(evaluation: dict) -> None:
    assert evaluation["real_world"] is False
    assert evaluation["labels_by_kind"] == {"oracle": evaluation["labels"]}
    assert evaluation["labels_with_second_reviewer"] == 0
    text = " ".join(evaluation["caveats"]).lower()
    assert "not a real-world benchmark" in text and "no accuracy claim" in text
    assert "not assessed" in evaluation["targets"]["met"]


def test_extractor_and_independent_oracle_agree_on_the_local_pages(
    evaluation: dict,
) -> None:
    """A regression guard: any disagreement is listed with the model's own words."""
    assert evaluation["disagreements"] == [], evaluation["disagreements"]
    for fid, m in evaluation["per_feature"].items():
        assert m["n"] == m["tp"] + m["fp"] + m["tn"] + m["fn"], fid


def test_checked_in_results_match_a_fresh_evaluation(evaluation: dict) -> None:
    assert json.loads(RESULTS.read_text(encoding="utf-8")) == evaluation, (
        "rerun: python -m geoptimiser.validation.corpus --manifest "
        "benchmarks/corpus/manifest.json --out docs/validation/results/corpus_initial.json"
    )


def test_label_and_snapshot_schemas_are_strict() -> None:
    with pytest.raises(ValidationError):
        Label(defect=True, labeler="x", kind="oracle")  # labeler too short
    with pytest.raises(ValidationError):
        Label(defect=True, labeler="human:a", kind="guess")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Snapshot.model_validate({"snapshot_id": "s", "unknown_field": 1})
