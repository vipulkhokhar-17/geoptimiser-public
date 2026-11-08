import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from geoptimiser.jsonl import JsonlWriter, read_jsonl, write_json_atomic
from geoptimiser.schemas import VersionedRecord


class Rec(VersionedRecord):
    n: int


class Plain(BaseModel):
    n: int


def test_lines_are_durable_and_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "a.jsonl"
    with JsonlWriter(path) as writer:
        writer.write(Rec(n=1))
        assert len(path.read_text().splitlines()) == 1  # visible before close
        writer.write(Rec(n=2))
    assert [r.n for r in read_jsonl(path, Rec)] == [1, 2]


def test_existing_files_are_never_overwritten(tmp_path: Path) -> None:
    JsonlWriter(tmp_path / "a.jsonl").close()
    with pytest.raises(FileExistsError):
        JsonlWriter(tmp_path / "a.jsonl")
    write_json_atomic(tmp_path / "a.json", {"x": 1})
    with pytest.raises(FileExistsError):
        write_json_atomic(tmp_path / "a.json", {"x": 2})


def test_reader_ignores_a_torn_line_and_requires_a_version(tmp_path: Path) -> None:
    path = tmp_path / "a.jsonl"
    good = Rec(n=1).model_dump_json()
    path.write_text(good + "\n" + good[:10], encoding="utf-8")
    assert len(read_jsonl(path, Rec)) == 1
    path.write_text(json.dumps({"n": 1}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="schema_version"):
        read_jsonl(path, Rec)
    assert read_jsonl(path, Plain, versioned=False)[0].n == 1


def test_atomic_json_leaves_no_temporary_file(tmp_path: Path) -> None:
    write_json_atomic(tmp_path / "sub" / "r.json", {"a": [1, 2]})
    assert json.loads((tmp_path / "sub" / "r.json").read_text()) == {"a": [1, 2]}
    assert [p.name for p in (tmp_path / "sub").iterdir()] == ["r.json"]
