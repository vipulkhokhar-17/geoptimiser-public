"""Crash-safe JSONL artifacts for extraction (same durability rules as the crawler)."""

import json
import os
from pathlib import Path
from types import TracebackType
from typing import IO, Any

from pydantic import BaseModel

from geoptimiser.schemas import SCHEMA_VERSION, PageDocument


class ExtractionWriter:
    """Appends ``documents.jsonl``, ``extraction_failures.jsonl`` and
    ``skipped_fetches.jsonl``; each line is flushed and ``fsync``-ed before the
    next page is processed. Files are created exclusively, so an existing
    extraction is never overwritten. ``extraction_summary.json`` is replaced
    atomically at the end.
    """

    def __init__(self, out_dir: Path) -> None:
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._documents = self._open("documents.jsonl")
        self._failures = self._open("extraction_failures.jsonl")
        self._skipped = self._open("skipped_fetches.jsonl")

    def _open(self, name: str) -> IO[str]:
        return open(self.out_dir / name, "x", encoding="utf-8")  # noqa: SIM115

    @staticmethod
    def _append(handle: IO[str], record: BaseModel) -> None:
        handle.write(record.model_dump_json() + "\n")
        handle.flush()
        os.fsync(handle.fileno())

    def write_document(self, record: BaseModel) -> None:
        self._append(self._documents, record)

    def write_failure(self, record: BaseModel) -> None:
        self._append(self._failures, record)

    def write_skipped(self, record: BaseModel) -> None:
        self._append(self._skipped, record)

    def write_summary(self, summary: dict[str, Any]) -> None:
        tmp = self.out_dir / ".extraction_summary.json.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(summary, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.out_dir / "extraction_summary.json")

    def close(self) -> None:
        for handle in (self._documents, self._failures, self._skipped):
            handle.close()

    def __enter__(self) -> "ExtractionWriter":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def read_documents(path: Path) -> list[PageDocument]:
    """Load ``documents.jsonl``, ignoring a torn final line.

    Each record must declare ``schema_version`` explicitly and match this code's
    version (ADR-0006).
    """
    lines = Path(path).read_text(encoding="utf-8").split("\n")[:-1]
    records: list[PageDocument] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        data = json.loads(line)
        if data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(
                f"line {number}: schema_version {data.get('schema_version')!r} "
                f"is not supported (expected {SCHEMA_VERSION})"
            )
        records.append(PageDocument.model_validate(data))
    return records
