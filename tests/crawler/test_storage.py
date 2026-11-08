import hashlib
import os
import time
from pathlib import Path

import pytest

from geoptimiser.crawler import LocalBodyStore


def test_put_get_round_trip_is_content_addressed(tmp_path: Path) -> None:
    store = LocalBodyStore(tmp_path)
    body = store.put(b"<html>hi</html>")

    digest = hashlib.sha256(b"<html>hi</html>").hexdigest()
    assert body.sha256 == digest
    assert body.ref == f"sha256:{digest}"
    assert body.size_bytes == 15
    assert not body.truncated
    assert store.get(body.ref) == b"<html>hi</html>"
    assert (tmp_path / digest[:2] / digest).is_file()


def test_identical_bodies_are_stored_once(tmp_path: Path) -> None:
    store = LocalBodyStore(tmp_path)
    assert store.put(b"same").ref == store.put(b"same").ref
    assert len(list(tmp_path.glob("??/*"))) == 1


def test_truncated_flag_is_carried(tmp_path: Path) -> None:
    assert LocalBodyStore(tmp_path).put(b"abc", truncated=True).truncated


def test_files_are_private_and_no_temp_files_remain(tmp_path: Path) -> None:
    body = LocalBodyStore(tmp_path).put(b"x")
    path = tmp_path / body.sha256[:2] / body.sha256
    assert path.stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.rglob(".tmp-*"))


@pytest.mark.parametrize(
    "ref",
    ["../../etc/passwd", "sha256:../x", "sha256:" + "A" * 64, "sha256:abc", "", "x"],
)
def test_malformed_refs_are_rejected(tmp_path: Path, ref: str) -> None:
    store = LocalBodyStore(tmp_path)
    with pytest.raises(ValueError, match="invalid body reference"):
        store.get(ref)
    with pytest.raises(ValueError, match="invalid body reference"):
        store.delete(ref)


def test_tampered_content_is_detected(tmp_path: Path) -> None:
    store = LocalBodyStore(tmp_path)
    body = store.put(b"original")
    (tmp_path / body.sha256[:2] / body.sha256).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="does not match"):
        store.get(body.ref)


def test_missing_body_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        LocalBodyStore(tmp_path).get("sha256:" + "0" * 64)


def test_delete(tmp_path: Path) -> None:
    store = LocalBodyStore(tmp_path)
    body = store.put(b"gone")
    assert store.delete(body.ref) is True
    assert store.delete(body.ref) is False


def test_purge_older_than(tmp_path: Path) -> None:
    store = LocalBodyStore(tmp_path)
    old, fresh = store.put(b"old"), store.put(b"fresh")
    long_ago = time.time() - 40 * 86400
    os.utime(tmp_path / old.sha256[:2] / old.sha256, (long_ago, long_ago))

    assert store.purge_older_than(30) == 1
    assert store.get(fresh.ref) == b"fresh"
    with pytest.raises(FileNotFoundError):
        store.get(old.ref)
