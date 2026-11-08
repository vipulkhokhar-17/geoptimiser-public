"""Persistence: reopening, interruption, concurrency, schema versions."""

import sqlite3
import threading
from datetime import UTC, datetime, timedelta

import pytest

from geoptimiser.app import AuditOptions, AuditStore, AuditSubmission
from geoptimiser.app.models import StageRecord, normalize_target
from geoptimiser.app.service import AuditNotFound, AuditService
from geoptimiser.app.store import (
    SCHEMA_VERSION,
    InvalidTransition,
    NotFound,
    StoreError,
)
from tests.app.conftest import populate

T0 = datetime(2026, 6, 1, tzinfo=UTC)


def create(store, url="http://acme.test/", when=T0, **kw):
    target = normalize_target(url)
    return store.create_audit(
        target_url=target.url, normalized_url=target.normalized_url, domain=target.domain,
        brand_name=kw.get("brand"), options=AuditOptions(), created_at=when,
    )  # fmt: skip


def test_audit_ids_are_deterministic_unique_and_directory_safe(tmp_path):
    a = AuditStore(tmp_path / "a.db")
    b = AuditStore(tmp_path / "b.db")
    first, second = create(a), create(a)
    assert first.audit_id != second.audit_id  # same target and time, next sequence
    assert create(b).audit_id == first.audit_id  # reproducible given the same inputs
    assert first.audit_id.startswith("aud_") and len(first.audit_id) == 24
    assert a.artifact_dir(first.audit_id) == f"audits/{first.audit_id}"


def test_completed_audits_survive_a_restart(make_service, site, tmp_path):
    populate(site)
    first = make_service()
    record = first.submit(
        AuditSubmission(url="http://acme.test/", authorization_confirmed=True)
    )
    assert first.runner.wait_idle(60)
    done = first.get(record.audit_id)
    assert done.status == "completed"
    report_before = first.report(record.audit_id)
    first.close()

    second = make_service()  # a new process over the same data directory
    assert second.recovered == []
    again = second.get(record.audit_id)
    assert again == done
    assert second.report(record.audit_id) == report_before
    assert [a.audit_id for a in second.list_audits()] == [record.audit_id]
    assert second.findings(record.audit_id)["count"] == len(report_before.findings)


def test_audits_running_when_the_process_died_become_interrupted(tmp_path):
    store = AuditStore(tmp_path / "x.db")
    queued, running, finished = (
        create(store),
        create(store, when=T0 + timedelta(1)),
        create(store, when=T0 + timedelta(2)),
    )
    store.start(running.audit_id, T0)
    store.save_stage(
        running.audit_id, StageRecord(name="crawl", status="running", started_at=T0)
    )
    store.start(finished.audit_id, T0)
    store.finish(finished.audit_id, "completed", T0)

    recovered = AuditStore(tmp_path / "x.db").recover_interrupted(T0 + timedelta(3))
    assert set(recovered) == {queued.audit_id, running.audit_id}
    for audit_id in recovered:
        record = store.get_audit(audit_id)
        assert record.status == "interrupted" and record.error_category == "interrupted"
        assert "stopped" in record.error_message
    assert store.get_audit(finished.audit_id).status == "completed"  # untouched
    assert store.stages(running.audit_id)[0].status == "failed"
    assert store.stages(running.audit_id)[0].error_category == "interrupted"


def test_an_interrupted_audit_is_never_reported_as_completed(make_service, tmp_path):
    service = make_service()
    target = normalize_target("http://acme.test/")
    record = service.store.create_audit(
        target_url=target.url, normalized_url=target.normalized_url, domain=target.domain,
        brand_name=None, options=AuditOptions(), created_at=T0,
    )  # fmt: skip
    service.store.start(record.audit_id, T0)
    service.close()
    restarted = make_service()
    assert restarted.recovered == [record.audit_id]
    assert restarted.get(record.audit_id).status == "interrupted"
    with pytest.raises(Exception) as err:
        restarted.report(record.audit_id)
    assert err.value.code == "report_unavailable"  # type: ignore[attr-defined]


def test_terminal_states_are_final(tmp_path):
    store = AuditStore(tmp_path / "x.db")
    record = create(store)
    store.start(record.audit_id, T0)
    store.finish(record.audit_id, "failed", T0, error_category="dns", error_message="x")
    with pytest.raises(InvalidTransition):
        store.finish(record.audit_id, "completed", T0)
    with pytest.raises(InvalidTransition):
        store.start(record.audit_id, T0)
    with pytest.raises(ValueError):
        store.finish(create(store, when=T0 + timedelta(1)).audit_id, "running", T0)
    with pytest.raises(NotFound):
        store.get_audit("aud_" + "f" * 20)
    with pytest.raises(NotFound):
        store.finish("aud_" + "f" * 20, "failed", T0)


def test_schema_version_is_tracked_and_newer_databases_are_refused(tmp_path):
    path = tmp_path / "x.db"
    store = AuditStore(path)
    assert store.schema_version == SCHEMA_VERSION
    AuditStore(path)  # reopening is idempotent
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    conn.close()
    with pytest.raises(StoreError, match="newer"):
        AuditStore(path)


def test_wal_mode_and_foreign_keys(tmp_path):
    store = AuditStore(tmp_path / "x.db")
    conn = store._connect()
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO stages (audit_id, name, status) VALUES ('nope','crawl','ok')"
            )
    finally:
        conn.close()


def test_concurrent_writers_do_not_lose_or_collide(tmp_path):
    store = AuditStore(tmp_path / "x.db")
    ids: list[str] = []
    errors: list[BaseException] = []

    def work(n: int) -> None:
        try:
            record = create(store, url=f"http://acme.test/p{n % 3}")
            store.start(record.audit_id, T0)
            for stage in ("crawl", "extract"):
                store.save_stage(record.audit_id, StageRecord(name=stage, status="ok"))
            store.finish(record.audit_id, "completed", T0)
            ids.append(record.audit_id)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(n,)) for n in range(16)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and len(set(ids)) == 16
    assert len(store.list_audits(limit=100)) == 16
    assert all(len(store.stages(i)) == 2 for i in ids)


def test_a_failed_transaction_rolls_back(tmp_path):
    store = AuditStore(tmp_path / "x.db")
    with pytest.raises(RuntimeError):
        with store._tx() as conn:
            conn.execute(
                "INSERT INTO audits (audit_id,target_url,normalized_url,domain,status,created_at,"
                "pipeline_version,options_json,artifact_dir) VALUES ('aud_x','u','n','d','queued','t','p','{}','d')"
            )
            raise RuntimeError("boom")
    assert store.list_audits() == []


def test_artifact_registry_records_hash_and_size(tmp_path):
    store = AuditStore(tmp_path / "x.db")
    record = create(store)
    (tmp_path / "audits" / record.audit_id).mkdir(parents=True)
    path = tmp_path / "audits" / record.audit_id / "report.json"
    path.write_text('{"a": 1}')
    store.register_artifact(
        record.audit_id,
        "report.json",
        f"audits/{record.audit_id}/report.json",
        tmp_path,
    )
    entry = store.artifacts(record.audit_id)["report.json"]
    assert entry["size_bytes"] == 8 and len(entry["sha256"]) == 64


def test_service_never_reads_outside_the_data_directory(make_service, tmp_path):
    service = make_service()
    record = service.store.create_audit(
        target_url="http://acme.test/", normalized_url="http://acme.test/", domain="acme.test",
        brand_name=None, options=AuditOptions(), created_at=T0,
    )  # fmt: skip
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret")
    service.store.register_artifact(
        record.audit_id, "report.json", "../secret.txt", tmp_path / "data"
    )
    assert service._read(record.audit_id, "report.json") is None
    with pytest.raises(Exception) as err:
        service.report(record.audit_id)
    assert "secret" not in str(err.value) and str(tmp_path) not in str(err.value)


def test_unknown_audit_errors_do_not_leak_paths(make_service):
    service = make_service()
    with pytest.raises(AuditNotFound) as err:
        service.get("aud_" + "a" * 20)
    assert "/" not in str(err.value)
    assert isinstance(service, AuditService)
