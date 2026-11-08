"""Crash-safe JSONL artifacts: each record is durable before the crawl continues."""

import json
import os
from pathlib import Path
from types import TracebackType
from typing import IO, Any

from pydantic import BaseModel

from geoptimiser.schemas import SCHEMA_VERSION, FetchRecord


class ArtifactWriter:
    """Appends records to ``fetches.jsonl`` / ``skipped_urls.jsonl`` as they occur.

    Every line is written, flushed and ``fsync``-ed before the next request, so an
    interrupted or failed crawl keeps everything it had observed. Files are created
    exclusively: a directory that already holds an audit is never overwritten. After
    a hard crash the final line may be torn; ``read_fetches`` ignores it.
    ``crawl_summary.json`` is replaced atomically at the end (or on abort).
    """

    def __init__(self, out_dir: Path) -> None:
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._fetches = self._open("fetches.jsonl")
        self._skipped = self._open("skipped_urls.jsonl")

    def _open(self, name: str) -> IO[str]:
        return open(self.out_dir / name, "x", encoding="utf-8")  # noqa: SIM115

    @staticmethod
    def _append(handle: IO[str], record: BaseModel) -> None:
        handle.write(record.model_dump_json() + "\n")
        handle.flush()
        os.fsync(handle.fileno())

    def write_fetch(self, record: BaseModel) -> None:
        self._append(self._fetches, record)

    def write_skipped(self, record: BaseModel) -> None:
        self._append(self._skipped, record)

    def write_summary(self, summary: dict[str, Any]) -> None:
        tmp = self.out_dir / ".crawl_summary.json.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(summary, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.out_dir / "crawl_summary.json")

    def close(self) -> None:
        self._fetches.close()
        self._skipped.close()

    def __enter__(self) -> "ArtifactWriter":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def read_fetches(path: Path) -> list[FetchRecord]:
    """Load ``fetches.jsonl``, ignoring a torn (unterminated) final line.

    Each record must declare ``schema_version`` explicitly and match this code's
    version (ADR-0006): the model default is for producers, not for readers.
    """
    text = Path(path).read_text(encoding="utf-8")
    lines = text.split("\n")
    complete = lines[:-1]  # the last element is "" or an unterminated fragment
    records: list[FetchRecord] = []
    for number, line in enumerate(complete, start=1):
        if not line.strip():
            continue
        data = json.loads(line)
        if data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(
                f"line {number}: schema_version {data.get('schema_version')!r} "
                f"is not supported (expected {SCHEMA_VERSION})"
            )
        records.append(FetchRecord.model_validate(data))
    return records
