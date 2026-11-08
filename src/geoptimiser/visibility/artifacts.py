"""Visibility artifacts: ``visibility.jsonl`` and ``visibility_manifest.json``."""

from pathlib import Path

from geoptimiser.jsonl import JsonlWriter, read_jsonl, write_json_atomic
from geoptimiser.schemas import VisibilityObservation
from geoptimiser.visibility.collect import CollectionManifest, CollectionResult

OBSERVATIONS = "visibility.jsonl"
MANIFEST = "visibility_manifest.json"


def open_observation_sink(out_dir: Path) -> JsonlWriter:
    """Sink for ``collect_visibility``: each record is durable before the next call."""
    return JsonlWriter(Path(out_dir) / OBSERVATIONS)


def write_manifest(manifest: CollectionManifest, out_dir: Path) -> None:
    write_json_atomic(Path(out_dir) / MANIFEST, manifest.model_dump(mode="json"))


def write_collection(result: CollectionResult, out_dir: Path) -> None:
    """Write a finished collection in one go (observations, then the manifest)."""
    with open_observation_sink(out_dir) as sink:
        for observation in result.observations:
            sink.write(observation)
    write_manifest(result.manifest, out_dir)


def read_observations(out_dir: Path) -> list[VisibilityObservation]:
    return read_jsonl(Path(out_dir) / OBSERVATIONS, VisibilityObservation)
