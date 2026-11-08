import json
from pathlib import Path

import pytest

from geoptimiser.crawler import ArtifactWriter, read_fetches
from tests.test_fetch_extraction import make_fetch


def test_lines_are_on_disk_before_close(tmp_path: Path) -> None:
    writer = ArtifactWriter(tmp_path)
    writer.write_fetch(make_fetch())

    # Read through a second handle while the writer is still open.
    assert len((tmp_path / "fetches.jsonl").read_text().splitlines()) == 1
    writer.close()


def test_existing_audit_directory_is_never_overwritten(tmp_path: Path) -> None:
    ArtifactWriter(tmp_path).close()
    with pytest.raises(FileExistsError):
        ArtifactWriter(tmp_path)


def test_summary_is_replaced_atomically(tmp_path: Path) -> None:
    with ArtifactWriter(tmp_path) as writer:
        writer.write_summary({"stop_reason": "completed"})
        writer.write_summary({"stop_reason": "aborted"})
    assert json.loads((tmp_path / "crawl_summary.json").read_text()) == {
        "stop_reason": "aborted"
    }
    assert not (tmp_path / ".crawl_summary.json.tmp").exists()


def test_reader_round_trips_complete_records(tmp_path: Path) -> None:
    with ArtifactWriter(tmp_path) as writer:
        writer.write_fetch(make_fetch())
        writer.write_fetch(make_fetch(fetch_id="fetch_002"))
    records = read_fetches(tmp_path / "fetches.jsonl")
    assert [r.fetch_id for r in records] == ["fetch_001", "fetch_002"]


def test_reader_ignores_a_torn_final_line(tmp_path: Path) -> None:
    path = tmp_path / "fetches.jsonl"
    good = make_fetch().model_dump_json()
    path.write_text(good + "\n" + good[: len(good) // 2], encoding="utf-8")
    assert len(read_fetches(path)) == 1


def test_reader_requires_an_explicit_supported_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "fetches.jsonl"
    data = json.loads(make_fetch().model_dump_json())
    for bad in (
        {**data, "schema_version": 2},
        {k: v for k, v in data.items() if k != "schema_version"},
    ):
        path.write_text(json.dumps(bad) + "\n", encoding="utf-8")
        with pytest.raises(ValueError, match="schema_version"):
            read_fetches(path)


def test_reader_rejects_a_corrupt_complete_line(tmp_path: Path) -> None:
    path = tmp_path / "fetches.jsonl"
    path.write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        read_fetches(path)
