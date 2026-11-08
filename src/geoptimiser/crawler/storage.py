"""Response-body storage behind a small interface (ADR-0007)."""

import hashlib
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Protocol

from geoptimiser.schemas import StoredBody

_REF = re.compile(r"^sha256:([0-9a-f]{64})$")


class StorageError(RuntimeError):
    """A body could not be stored. This is not a network failure: the crawl aborts."""


class BodyStore(Protocol):
    """Where fetched bodies live. Records hold only the returned reference."""

    def put(self, data: bytes, *, truncated: bool = False) -> StoredBody: ...

    def get(self, ref: str) -> bytes: ...

    def delete(self, ref: str) -> bool: ...


def parse_ref(ref: str) -> str:
    """Return the SHA-256 digest in ``ref`` or raise ``ValueError``."""
    match = _REF.match(ref)
    if match is None:
        raise ValueError(f"invalid body reference: {ref!r}")
    return match.group(1)


class LocalBodyStore:
    """Content-addressed files: ``<root>/<aa>/<sha256>``, ref ``sha256:<hex>``.

    Identical bodies are stored once. References are validated against a strict
    pattern, so a crafted ref cannot escape the root. ``get`` re-hashes the file
    and refuses content that no longer matches its address.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path(self, digest: str) -> Path:
        return self.root / digest[:2] / digest

    def put(self, data: bytes, *, truncated: bool = False) -> StoredBody:
        digest = hashlib.sha256(data).hexdigest()
        path = self._path(digest)
        if path.exists():
            os.utime(path)  # a repeated body counts as freshly stored for retention
        else:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                os.chmod(tmp, 0o600)
                os.replace(tmp, path)  # atomic: readers never see partial files
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
        return StoredBody(
            ref=f"sha256:{digest}",
            sha256=digest,
            size_bytes=len(data),
            truncated=truncated,
        )

    def get(self, ref: str) -> bytes:
        digest = parse_ref(ref)
        data = self._path(digest).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError(f"stored body does not match its address: {ref}")
        return data

    def delete(self, ref: str) -> bool:
        path = self._path(parse_ref(ref))
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        return True

    def purge_older_than(self, days: float, *, now: float | None = None) -> int:
        """Delete bodies last stored more than ``days`` ago; return the count."""
        cutoff = (time.time() if now is None else now) - days * 86400
        removed = 0
        for path in self.root.glob("??/" + "[0-9a-f]" * 64):
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        return removed
