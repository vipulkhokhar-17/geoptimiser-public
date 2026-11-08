"""A labelled page corpus and the diagnostic metrics computed against it.

The corpus is a manifest of page snapshots, each with per-feature binary labels
(``defect: true`` means the property the feature checks is absent or invalid). Every
label records who or what assigned it, so a reader can tell a human judgment from an
automated cross-check, and every snapshot says whether it is a real-world page.

**What exists today.** The shipped manifest (``benchmarks/corpus/manifest.json``) is an
*initial, repository-local* corpus: pages already in this repository (demo site and
extraction fixtures), labelled by an independent HTML parser (an "oracle"), not by
people. It tests agreement between two implementations on objective properties. It is
NOT a real-world benchmark and is far too small to support any accuracy claim; the
results say so. The framework below is what a real corpus (target 200-300 snapshots,
critical labels from two human reviewers with recorded disagreements) would use.
"""

import argparse
import json
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from geoptimiser.validation.metrics import BinaryCounts
from geoptimiser.validation.runner import run_fixture
from geoptimiser.validation.spec import FixtureSpec

CORPUS_VERSION = 1
LabelerKind = Literal["human", "oracle"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Label(_Model):
    defect: bool
    labeler: str = Field(min_length=3)  # e.g. "human:reviewer-a" or "oracle:lxml 6.1.3"
    kind: LabelerKind
    # Free text for doubtful cases; a second reviewer's label goes in `second_label`.
    uncertainty: str = ""
    second_label: "Label | None" = None


class Snapshot(_Model):
    snapshot_id: str
    file: str  # relative to the manifest
    url: str  # URL the page is presented under for the audit
    source: str  # where the HTML came from
    snapshot_date: str
    page_type: str
    real_world: bool
    response: dict[str, str | int | bool] = Field(default_factory=dict)
    labels: dict[str, Label]
    notes: str = ""


class Manifest(_Model):
    corpus_version: int = CORPUS_VERSION
    name: str
    description: str
    real_world: bool
    snapshots: tuple[Snapshot, ...]


def load_manifest(path: Path) -> Manifest:
    return Manifest.model_validate(json.loads(path.read_text(encoding="utf-8")))


@dataclass(frozen=True)
class Prediction:
    snapshot_id: str
    feature_id: str
    label_defect: bool
    status: str
    explanation: str


def _spec_for(snapshot: Snapshot, html: str) -> FixtureSpec:
    from geoptimiser.validation.spec import Expectations, Route

    return FixtureSpec(
        id=f"corpus_{snapshot.snapshot_id}",
        title=snapshot.snapshot_id,
        description=snapshot.source,
        site={
            "/robots.txt": Route(
                text="User-agent: *\nAllow: /\n", content_type="text/plain"
            ),
            "/": Route(text=html),
        },
        expect=Expectations(),
    )


def evaluate_corpus(manifest: Manifest, base: Path) -> dict[str, object]:
    """Run every snapshot through the real pipeline and compare with its labels."""
    predictions: list[Prediction] = []
    with tempfile.TemporaryDirectory() as tmp:
        for snap in manifest.snapshots:
            html = (base / snap.file).read_text(encoding="utf-8")
            run = run_fixture(_spec_for(snap, html), Path(tmp))
            by_feature = {
                r.feature_id: r
                for r in run.run.results
                if r.subject_url and r.subject_url.rstrip("/").endswith("fixture.test")
            }
            for fid, label in snap.labels.items():
                result = by_feature.get(fid)
                predictions.append(
                    Prediction(
                        snap.snapshot_id,
                        fid,
                        label.defect,
                        result.status if result else "(no result)",
                        (result.explanation or "") if result else "",
                    )
                )
    counts: dict[str, BinaryCounts] = {}
    abstained: dict[str, Counter[str]] = {}
    disagreements = []
    for p in predictions:
        c = counts.get(p.feature_id, BinaryCounts())
        if p.status in ("pass", "fail", "warning"):
            predicted = p.status == "fail"
            if p.label_defect:
                c += BinaryCounts(tp=int(predicted), fn=int(not predicted))
            else:
                c += BinaryCounts(fp=int(predicted), tn=int(not predicted))
            if predicted != p.label_defect:
                disagreements.append(p)
        else:
            abstained.setdefault(p.feature_id, Counter())[
                "label_defect" if p.label_defect else "label_ok"
            ] += 1
        counts[p.feature_id] = c
    two_reviewers = sum(
        1
        for s in manifest.snapshots
        for lab in s.labels.values()
        if lab.second_label is not None
    )
    return {
        "corpus": manifest.name,
        "corpus_version": manifest.corpus_version,
        "real_world": manifest.real_world,
        "snapshots": len(manifest.snapshots),
        "labels": sum(len(s.labels) for s in manifest.snapshots),
        "labels_by_kind": dict(
            Counter(lab.kind for s in manifest.snapshots for lab in s.labels.values())
        ),
        "labels_with_second_reviewer": two_reviewers,
        "per_feature": {
            fid: {**c.as_dict(), "abstained": dict(abstained.get(fid, {}))}
            for fid, c in sorted(counts.items())
        },
        "disagreements": [
            {
                "snapshot": p.snapshot_id,
                "feature": p.feature_id,
                "label": "defect" if p.label_defect else "ok",
                "model": p.status,
                "explanation": p.explanation,
            }
            for p in disagreements
        ],
        "predictions": [
            {
                "snapshot": p.snapshot_id,
                "feature": p.feature_id,
                "label": "defect" if p.label_defect else "ok",
                "model": p.status,
            }
            for p in predictions
        ],
        "caveats": [
            "Not a real-world benchmark."
            if not manifest.real_world
            else "Real-world corpus.",
            "Sample sizes are tiny; every interval above is wide and no accuracy "
            "claim follows from them.",
            "Oracle labels check agreement between two implementations on objective "
            "properties; they are not human judgments of usefulness.",
            "A mean of undefined metrics is never computed; undefined means no "
            "positive prediction or no true positive existed.",
        ],
        "targets": {
            "presence_and_validity_checks": "precision and recall >= 0.95 on a "
            "sufficiently representative labelled benchmark (project acceptance "
            "target, not a universal standard)",
            "heuristic_checks": "precision < 0.80 -> candidate for informational-only",
            "met": "not assessed: no feature has a representative labelled benchmark",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate features against a corpus.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    manifest = load_manifest(args.manifest)
    result = evaluate_corpus(manifest, args.manifest.parent)
    text = json.dumps(result, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(
        f"{result['snapshots']} snapshots, {result['labels']} labels, "
        f"{len(result['disagreements'])} disagreements"  # type: ignore[arg-type]
    )
    for fid, m in result["per_feature"].items():  # type: ignore[union-attr]
        print(
            f"  {fid}: n={m['n']} precision={m['precision']} recall={m['recall']} "
            f"(tp={m['tp']} fp={m['fp']} tn={m['tn']} fn={m['fn']}) "
            f"{m['abstained'] or ''}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
