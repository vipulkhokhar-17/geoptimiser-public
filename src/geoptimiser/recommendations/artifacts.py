"""``findings.json`` and ``recommendations.json`` written together."""

from pathlib import Path

from geoptimiser.diagnosis import Diagnosis, write_diagnosis
from geoptimiser.jsonl import write_json_atomic
from geoptimiser.recommendations.generator import RecommendationSet


def write_recommendations(path: Path, result: RecommendationSet) -> None:
    write_json_atomic(path, result.model_dump(mode="json"))


def write_outputs(
    out_dir: Path, diagnosis: Diagnosis, recommendations: RecommendationSet
) -> None:
    """Write both artifacts; neither is overwritten if it exists."""
    out_dir.mkdir(parents=True, exist_ok=True)
    write_diagnosis(out_dir / "findings.json", diagnosis)
    write_recommendations(out_dir / "recommendations.json", recommendations)
