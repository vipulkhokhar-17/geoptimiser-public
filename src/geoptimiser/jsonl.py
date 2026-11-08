"""Small durable-write helpers shared by the RAG stages (04–10).

Same conventions as the crawler and extraction writers: files are created exclusively
(an existing run is never overwritten), every JSONL line is flushed and ``fsync``-ed
as it is written, JSON documents are replaced atomically, and readers ignore a torn
final line and require an explicit ``schema_version`` where the model has one.
"""

import json
import os
from pathlib import Path
from types import TracebackType
from typing import Any, TypeVar

from pydantic import BaseModel

from geoptimiser.schemas import SCHEMA_VERSION

M = TypeVar("M", bound=BaseModel)


class JsonlWriter:
    """Append records to one JSONL file, durably."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = open(self.path, "x", encoding="utf-8")  # noqa: SIM115

    def write(self, record: BaseModel) -> None:
        self._handle.write(record.model_dump_json() + "\n")
        self._handle.flush()
        os.fsync(self._handle.fileno())

    def close(self) -> None:
        self._handle.close()

    def __enter__(self) -> "JsonlWriter":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def read_jsonl(path: Path, model: type[M], *, versioned: bool = True) -> list[M]:
    """Load a JSONL file of ``model`` records, ignoring a torn final line.

    With ``versioned`` the JSON must carry ``schema_version`` explicitly and equal
    the supported version (ADR-0006): the model default is for producers only.
    """
    lines = Path(path).read_text(encoding="utf-8").split("\n")[:-1]
    records: list[M] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        data = json.loads(line)
        if versioned and data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(
                f"line {number}: schema_version {data.get('schema_version')!r} "
                f"is not supported (expected {SCHEMA_VERSION})"
            )
        records.append(model.model_validate(data))
    return records


def write_json_atomic(path: Path, document: Any) -> None:
    """Write ``document`` as JSON via a temporary file and an atomic rename.

    Refuses to overwrite an existing file, like the JSONL writers.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(path)
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
