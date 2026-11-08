"""SQLite persistence for audit metadata (ADR-0024).

The database stores identity, status, configuration, stage records and *references* to
artifacts; the artifacts themselves stay in the audit's directory on disk. Writes are
short transactions on a connection opened per call, WAL mode lets readers proceed during
a write, and ``PRAGMA user_version`` tracks the schema so an older database is migrated
and a newer one is refused rather than guessed at.
"""

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from geoptimiser.app.models import (
    PIPELINE_VERSION,
    TERMINAL_STATUSES,
    AuditOptions,
    AuditRecord,
    StageRecord,
)

SCHEMA_VERSION = 1
_MIGRATIONS: dict[int, str] = {
    1: """
    CREATE TABLE audits (
        audit_id TEXT PRIMARY KEY,
        target_url TEXT NOT NULL,
        normalized_url TEXT NOT NULL,
        domain TEXT NOT NULL,
        brand_name TEXT,
        status TEXT NOT NULL CHECK (status IN
            ('queued','running','completed','incomplete','failed','interrupted')),
        stage TEXT,
        error_category TEXT,
        error_message TEXT,
        created_at TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT,
        pipeline_version TEXT NOT NULL,
        options_json TEXT NOT NULL,
        pipeline_json TEXT NOT NULL DEFAULT '{}',
        summary_json TEXT NOT NULL DEFAULT '{}',
        artifact_dir TEXT NOT NULL UNIQUE
    );
    CREATE INDEX audits_by_url ON audits (normalized_url, created_at);
    CREATE TABLE stages (
        audit_id TEXT NOT NULL REFERENCES audits (audit_id),
        name TEXT NOT NULL,
        status TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT,
        duration_ms REAL,
        error_category TEXT,
        error_message TEXT,
        detail_json TEXT NOT NULL DEFAULT '{}',
        PRIMARY KEY (audit_id, name)
    );
    CREATE TABLE artifacts (
        audit_id TEXT NOT NULL REFERENCES audits (audit_id),
        name TEXT NOT NULL,
        relpath TEXT NOT NULL,
        sha256 TEXT,
        size_bytes INTEGER,
        registered_at TEXT NOT NULL,
        PRIMARY KEY (audit_id, name)
    );
    CREATE TABLE comparisons (
        comparison_id TEXT PRIMARY KEY,
        before_audit_id TEXT NOT NULL REFERENCES audits (audit_id),
        after_audit_id TEXT NOT NULL REFERENCES audits (audit_id),
        normalized_url TEXT NOT NULL,
        relpath TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (before_audit_id, after_audit_id)
    );
    """,
}


class StoreError(RuntimeError):
    """The database cannot be used (for example, it was written by a newer version)."""


class NotFound(LookupError):
    """No such audit or comparison."""


class InvalidTransition(RuntimeError):
    """An attempt to change the status of an audit that has already finished."""


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def make_audit_id(normalized_url: str, created_at: datetime, sequence: int) -> str:
    """Deterministic for the same (target, time, sequence); unique per submission."""
    digest = hashlib.sha256(
        f"{normalized_url}|{_iso(created_at)}|{sequence}".encode()
    ).hexdigest()[:20]
    return f"aud_{digest}"


class AuditStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            conn = self._connect()
            try:
                self._migrate(conn)
            finally:
                conn.close()
        except sqlite3.DatabaseError:
            # Not a SQLite database / corrupt / locked: report it without the path.
            raise StoreError(
                "the audit database cannot be opened (corrupt or not a SQLite file)"
            ) from None

    # --- connection handling ----------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA busy_timeout = 30000")
        except BaseException:
            conn.close()  # do not leak the handle when the file is not a database
            raise
        return conn

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        """One write transaction: BEGIN IMMEDIATE takes the write lock up front."""
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    def _migrate(self, conn: sqlite3.Connection) -> None:
        conn.execute("BEGIN IMMEDIATE")
        try:
            current = conn.execute("PRAGMA user_version").fetchone()[0]
            if current > SCHEMA_VERSION:
                raise StoreError(
                    f"database schema version {current} is newer than this program "
                    f"supports ({SCHEMA_VERSION})"
                )
            for version in range(current + 1, SCHEMA_VERSION + 1):
                for statement in _MIGRATIONS[version].split(";"):
                    if statement.strip():
                        conn.execute(statement)
                conn.execute(f"PRAGMA user_version = {version}")
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise

    @property
    def schema_version(self) -> int:
        with self._read() as conn:
            return int(conn.execute("PRAGMA user_version").fetchone()[0])

    def check(self) -> None:
        """Raise if the database cannot be read (used by the readiness probe)."""
        with self._read() as conn:
            conn.execute("SELECT 1 FROM audits LIMIT 1").fetchall()

    # --- audits -------------------------------------------------------------------

    def create_audit(
        self,
        *,
        target_url: str,
        normalized_url: str,
        domain: str,
        brand_name: str | None,
        options: AuditOptions,
        created_at: datetime,
        pipeline: dict[str, object] | None = None,
    ) -> AuditRecord:
        """Insert a queued audit; its id and directory name are derived in the same
        transaction from the per-target sequence, so concurrent submissions of the
        same URL cannot collide."""
        with self._tx() as conn:
            sequence = conn.execute(
                "SELECT COUNT(*) FROM audits WHERE normalized_url = ?",
                (normalized_url,),
            ).fetchone()[0]
            audit_id = make_audit_id(normalized_url, created_at, sequence)
            conn.execute(
                "INSERT INTO audits (audit_id, target_url, normalized_url, domain, "
                "brand_name, status, created_at, pipeline_version, options_json, "
                "pipeline_json, artifact_dir) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    audit_id, target_url, normalized_url, domain, brand_name, "queued",
                    _iso(created_at), PIPELINE_VERSION, options.model_dump_json(),
                    json.dumps(pipeline or {}), f"audits/{audit_id}",
                ),
            )  # fmt: skip
        return self.get_audit(audit_id)

    def discard_queued(self, audit_id: str) -> bool:
        """Delete an audit that was never started (no stages, no artifacts).

        Used when the job queue refuses the audit right after it was created, so a
        rejected request leaves no durable state (security audit run 1)."""
        with self._tx() as conn:
            if conn.execute(
                "SELECT 1 FROM stages WHERE audit_id = ? UNION ALL "
                "SELECT 1 FROM artifacts WHERE audit_id = ? LIMIT 1",
                (audit_id, audit_id),
            ).fetchone():
                return False
            cur = conn.execute(
                "DELETE FROM audits WHERE audit_id = ? AND status = 'queued'",
                (audit_id,),
            )
            return cur.rowcount == 1

    def count_agent_audits_since(self, since: datetime) -> int:
        """Audits that requested the LLM agent, created at or after ``since``."""
        with self._tx() as conn:
            rows = conn.execute(
                "SELECT options_json FROM audits WHERE created_at >= ?",
                (_iso(since),),
            ).fetchall()
        return sum(1 for (options,) in rows if json.loads(options).get("use_agent"))

    @staticmethod
    def _audit(row: sqlite3.Row) -> AuditRecord:
        return AuditRecord(
            audit_id=row["audit_id"],
            target_url=row["target_url"],
            normalized_url=row["normalized_url"],
            domain=row["domain"],
            brand_name=row["brand_name"],
            status=row["status"],
            stage=row["stage"],
            error_category=row["error_category"],
            error_message=row["error_message"],
            created_at=_dt(row["created_at"]),
            started_at=_dt(row["started_at"]),
            finished_at=_dt(row["finished_at"]),
            pipeline_version=row["pipeline_version"],
            options=AuditOptions.model_validate_json(row["options_json"]),
            pipeline=json.loads(row["pipeline_json"]),
            summary=json.loads(row["summary_json"]),
        )

    def get_audit(self, audit_id: str) -> AuditRecord:
        with self._read() as conn:
            row = conn.execute(
                "SELECT * FROM audits WHERE audit_id = ?", (audit_id,)
            ).fetchone()
        if row is None:
            raise NotFound(audit_id)
        return self._audit(row)

    def artifact_dir(self, audit_id: str) -> str:
        with self._read() as conn:
            row = conn.execute(
                "SELECT artifact_dir FROM audits WHERE audit_id = ?", (audit_id,)
            ).fetchone()
        if row is None:
            raise NotFound(audit_id)
        return str(row["artifact_dir"])

    def list_audits(
        self, *, limit: int = 50, normalized_url: str | None = None
    ) -> list[AuditRecord]:
        query = "SELECT * FROM audits"
        args: list[Any] = []
        if normalized_url is not None:
            query += " WHERE normalized_url = ?"
            args.append(normalized_url)
        query += " ORDER BY created_at DESC, audit_id DESC LIMIT ?"
        args.append(limit)
        with self._read() as conn:
            return [self._audit(r) for r in conn.execute(query, args).fetchall()]

    def start(self, audit_id: str, started_at: datetime) -> None:
        with self._tx() as conn:
            changed = conn.execute(
                "UPDATE audits SET status='running', started_at=?, stage='validate' "
                "WHERE audit_id=? AND status='queued'",
                (_iso(started_at), audit_id),
            ).rowcount
            if not changed:
                self._missing_or_finished(conn, audit_id)

    def finish(
        self,
        audit_id: str,
        status: str,
        finished_at: datetime,
        *,
        error_category: str | None = None,
        error_message: str | None = None,
        summary: dict[str, object] | None = None,
        pipeline: dict[str, object] | None = None,
    ) -> None:
        """Move an audit into a terminal status (allowed once)."""
        if status not in TERMINAL_STATUSES:
            raise ValueError(f"{status!r} is not a terminal status")
        with self._tx() as conn:
            changed = conn.execute(
                "UPDATE audits SET status=?, finished_at=?, error_category=?, "
                "error_message=?, summary_json=COALESCE(?, summary_json), "
                "pipeline_json=COALESCE(?, pipeline_json) "
                "WHERE audit_id=? AND status IN ('queued','running')",
                (
                    status, _iso(finished_at), error_category,
                    (error_message or "")[:500] or None,
                    json.dumps(summary) if summary is not None else None,
                    json.dumps(pipeline) if pipeline is not None else None,
                    audit_id,
                ),
            ).rowcount  # fmt: skip
            if not changed:
                self._missing_or_finished(conn, audit_id)

    @staticmethod
    def _missing_or_finished(conn: sqlite3.Connection, audit_id: str) -> None:
        row = conn.execute(
            "SELECT status FROM audits WHERE audit_id = ?", (audit_id,)
        ).fetchone()
        if row is None:
            raise NotFound(audit_id)
        raise InvalidTransition(f"audit is already {row['status']}")

    def set_stage_pointer(self, audit_id: str, stage: str) -> None:
        with self._tx() as conn:
            conn.execute(
                "UPDATE audits SET stage=? WHERE audit_id=? AND status='running'",
                (stage, audit_id),
            )

    def recover_interrupted(self, when: datetime) -> list[str]:
        """After a restart: audits left queued/running by a previous process cannot be
        resumed, so mark them ``interrupted`` (their partial artifacts stay)."""
        with self._tx() as conn:
            ids = [
                r["audit_id"]
                for r in conn.execute(
                    "SELECT audit_id FROM audits WHERE status IN ('queued','running')"
                )
            ]
            for audit_id in ids:
                conn.execute(
                    "UPDATE audits SET status='interrupted', finished_at=?, "
                    "error_category='interrupted', error_message=? WHERE audit_id=?",
                    (
                        _iso(when),
                        "the service stopped before this audit finished",
                        audit_id,
                    ),
                )
                conn.execute(
                    "UPDATE stages SET status='failed', error_category='interrupted' "
                    "WHERE audit_id=? AND status='running'",
                    (audit_id,),
                )
        return ids

    # --- stages -------------------------------------------------------------------

    def save_stage(self, audit_id: str, stage: StageRecord) -> None:
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO stages (audit_id, name, status, started_at, finished_at, "
                "duration_ms, error_category, error_message, detail_json) "
                "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT (audit_id, name) DO UPDATE SET "
                "status=excluded.status, started_at=excluded.started_at, "
                "finished_at=excluded.finished_at, duration_ms=excluded.duration_ms, "
                "error_category=excluded.error_category, "
                "error_message=excluded.error_message, detail_json=excluded.detail_json",
                (
                    audit_id, stage.name, stage.status, _iso(stage.started_at),
                    _iso(stage.finished_at), stage.duration_ms, stage.error_category,
                    (stage.error_message or "")[:500] or None,
                    json.dumps(stage.detail, default=str),
                ),
            )  # fmt: skip

    def stages(self, audit_id: str) -> list[StageRecord]:
        with self._read() as conn:
            rows = conn.execute(
                "SELECT * FROM stages WHERE audit_id = ? ORDER BY rowid", (audit_id,)
            ).fetchall()
        return [
            StageRecord(
                name=r["name"],
                status=r["status"],
                started_at=_dt(r["started_at"]),
                finished_at=_dt(r["finished_at"]),
                duration_ms=r["duration_ms"],
                error_category=r["error_category"],
                error_message=r["error_message"],
                detail=json.loads(r["detail_json"]),
            )
            for r in rows
        ]

    # --- artifacts and comparisons -----------------------------------------------------

    def register_artifact(
        self, audit_id: str, name: str, relpath: str, data_dir: Path
    ) -> None:
        """Record a file by name; its hash and size are taken from the file itself."""
        path = Path(data_dir) / relpath
        digest, size = None, None
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            size = path.stat().st_size
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO artifacts (audit_id, name, relpath, sha256, size_bytes, "
                "registered_at) VALUES (?,?,?,?,?,?) ON CONFLICT (audit_id, name) DO "
                "UPDATE SET relpath=excluded.relpath, sha256=excluded.sha256, "
                "size_bytes=excluded.size_bytes, registered_at=excluded.registered_at",
                (audit_id, name, relpath, digest, size, _iso(datetime.now(UTC))),
            )

    def artifacts(self, audit_id: str) -> dict[str, dict[str, Any]]:
        with self._read() as conn:
            rows = conn.execute(
                "SELECT name, relpath, sha256, size_bytes FROM artifacts "
                "WHERE audit_id = ? ORDER BY name",
                (audit_id,),
            ).fetchall()
        return {
            r["name"]: {
                "relpath": r["relpath"],
                "sha256": r["sha256"],
                "size_bytes": r["size_bytes"],
            }
            for r in rows
        }

    def save_comparison(
        self,
        comparison_id: str,
        before: str,
        after: str,
        normalized_url: str,
        relpath: str,
        created_at: datetime,
    ) -> None:
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO comparisons VALUES (?,?,?,?,?,?) ON CONFLICT "
                "(before_audit_id, after_audit_id) DO UPDATE SET relpath=excluded.relpath, "
                "created_at=excluded.created_at",
                (
                    comparison_id,
                    before,
                    after,
                    normalized_url,
                    relpath,
                    _iso(created_at),
                ),
            )

    def get_comparison(self, before: str, after: str) -> dict[str, Any] | None:
        with self._read() as conn:
            row = conn.execute(
                "SELECT * FROM comparisons WHERE before_audit_id=? AND after_audit_id=?",
                (before, after),
            ).fetchone()
        return dict(row) if row else None

    def get_comparison_by_id(self, comparison_id: str) -> dict[str, Any]:
        with self._read() as conn:
            row = conn.execute(
                "SELECT * FROM comparisons WHERE comparison_id = ?", (comparison_id,)
            ).fetchone()
        if row is None:
            raise NotFound(comparison_id)
        return dict(row)
