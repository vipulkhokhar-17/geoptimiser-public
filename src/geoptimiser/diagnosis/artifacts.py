"""``findings.json``: the diagnosis as one atomic, non-overwriting JSON document."""

from pathlib import Path

from geoptimiser.diagnosis.engine import Diagnosis
from geoptimiser.jsonl import write_json_atomic


def write_diagnosis(path: Path, diagnosis: Diagnosis) -> None:
    write_json_atomic(path, diagnosis.model_dump(mode="json"))
