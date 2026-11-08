"""The application service: the one object the API and the CLI talk to.

It owns the store, the job runner and the artifact directory. Callers refer to audits
only by id; files are found through the store's artifact table and always checked to lie
inside the data directory, so no request can name or read an arbitrary path.
"""

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from geoptimiser.app.compare import CompareError, Comparison, compare_reports
from geoptimiser.app.config import AppConfig
from geoptimiser.app.jobs import JobRunner, QueueFull
from geoptimiser.app.models import (
    AuditRecord,
    AuditSubmission,
    StageRecord,
    TargetError,
    normalize_target,
)
from geoptimiser.app.pipeline import PipelineDeps, run_pipeline
from geoptimiser.app.report import AuditReport, render_html
from geoptimiser.app.store import AuditStore, NotFound
from geoptimiser.schemas import FeatureResult

_AUDIT_ID = re.compile(r"^aud_[0-9a-f]{20}$")
# Bounds on the per-feature explorer response (results are per page, evidence per result).
_MAX_RESULTS_PER_FEATURE = 100
_MAX_EVIDENCE = 5
_MAX_SNIPPET = 500


class ServiceError(Exception):
    """An error with a stable machine code and an HTTP-style status."""

    status = 400

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class InvalidAuditId(ServiceError):
    status = 400


class AuditNotFound(ServiceError):
    status = 404


class InvalidRequest(ServiceError):
    status = 422


class Unavailable(ServiceError):
    status = 409


class Busy(ServiceError):
    status = 503


class Incompatible(ServiceError):
    status = 409


class RateLimited(ServiceError):
    status = 429


def check_audit_id(audit_id: str) -> str:
    # fullmatch: with match(), "$" also accepts a trailing newline (security audit run 1).
    if not _AUDIT_ID.fullmatch(audit_id):
        raise InvalidAuditId(
            "invalid_audit_id", "audit ids look like aud_ followed by 20 hex digits"
        )
    return audit_id


class AuditService:
    def __init__(
        self,
        config: AppConfig,
        *,
        deps: PipelineDeps | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.config = config
        self.deps = deps or PipelineDeps()
        self.clock = clock
        self.data_dir = Path(config.data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.store = AuditStore(self.data_dir / "geoptimiser.db")
        # A previous process may have died mid-audit: those audits cannot resume.
        self.recovered = self.store.recover_interrupted(self.clock())
        self.runner = JobRunner(config.workers, config.max_queued)
        self._catalog: dict[str, Any] | None = None

    def close(self) -> None:
        self.runner.shutdown()

    # --- submission ------------------------------------------------------------------

    def submit(self, submission: AuditSubmission) -> AuditRecord:
        if not submission.authorization_confirmed:
            raise InvalidRequest(
                "authorization_required",
                "confirm that you own or are authorized to audit this site",
            )
        try:
            target = normalize_target(submission.url)
        except TargetError as exc:
            raise InvalidRequest("invalid_target", str(exc)) from None
        options = submission.options
        if options.use_agent and not self.config.agent_enabled:
            raise InvalidRequest(
                "agent_disabled", "the agent is disabled on this server"
            )
        if (
            options.max_pages > self.config.max_pages_cap
            or options.max_depth > self.config.max_depth_cap
        ):
            raise InvalidRequest(
                "options_out_of_range",
                f"max_pages is limited to {self.config.max_pages_cap} and max_depth to "
                f"{self.config.max_depth_cap} on this server",
            )
        if options.use_agent:
            since = self.clock() - timedelta(hours=1)
            if (
                self.store.count_agent_audits_since(since)
                >= self.config.max_agent_audits_per_hour
            ):
                raise RateLimited(
                    "agent_rate_limited",
                    f"at most {self.config.max_agent_audits_per_hour} audits per hour may "
                    "use the agent on this server; try again later or submit without it",
                )
        if not self.runner.has_room:
            # Refuse before anything durable is written.
            raise Busy("queue_full", "too many audits are queued; try again later")
        record = self.store.create_audit(
            target_url=target.url,
            normalized_url=target.normalized_url,
            domain=target.domain,
            brand_name=submission.brand_name,
            options=options,
            created_at=self.clock(),
        )
        try:
            self.runner.submit(self._job(record.audit_id))
        except QueueFull as exc:
            # A concurrent submission took the last slot: remove the never-started row
            # (falling back to marking it failed if it cannot be removed).
            if not self.store.discard_queued(record.audit_id):
                self.store.finish(
                    record.audit_id, "failed", self.clock(),
                    error_category="internal_error", error_message="rejected: queue full",
                )  # fmt: skip
            raise Busy("queue_full", str(exc)) from None
        return record

    def _job(self, audit_id: str) -> Callable[[], None]:
        def job() -> None:
            run_pipeline(audit_id, store=self.store, config=self.config, deps=self.deps)

        return job

    # --- reads -----------------------------------------------------------------------

    def get(self, audit_id: str) -> AuditRecord:
        check_audit_id(audit_id)
        try:
            return self.store.get_audit(audit_id)
        except NotFound:
            raise AuditNotFound("audit_not_found", "no audit with this id") from None

    def list_audits(self, limit: int = 50) -> list[AuditRecord]:
        return self.store.list_audits(limit=max(1, min(limit, 100)))

    def stages(self, audit_id: str) -> list[StageRecord]:
        self.get(audit_id)
        return self.store.stages(audit_id)

    def _read(self, audit_id: str, name: str) -> bytes | None:
        entry = self.store.artifacts(audit_id).get(name)
        if entry is None:
            return None
        root = self.data_dir.resolve()
        path = (root / entry["relpath"]).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            return None  # never reveal why
        return path.read_bytes()

    def report(self, audit_id: str) -> AuditReport:
        record = self.get(audit_id)
        raw = self._read(audit_id, "report.json")
        if raw is None:
            raise Unavailable(
                "report_unavailable",
                f"no report exists for this audit (status: {record.status})",
            )
        try:
            return AuditReport.model_validate_json(raw)
        except ValidationError:
            raise Unavailable(
                "report_unreadable", "the stored report could not be read"
            ) from None

    def report_html(self, audit_id: str) -> str:
        return render_html(self.report(audit_id))

    def findings(self, audit_id: str) -> dict[str, Any]:
        report = self.report(audit_id)
        if not report.findings_available:
            raise Unavailable(
                "findings_unavailable",
                f"findings are not available for an audit that is {report.status}",
            )
        return {
            "audit_id": audit_id,
            "status": report.status,
            "count": len(report.findings),
            "findings": [f.model_dump(mode="json") for f in report.findings],
        }

    def features(self, audit_id: str) -> dict[str, Any]:
        """Per-feature results of one audit, grouped by feature (read-only).

        Read from the stored ``feature_results.jsonl`` artifact and joined with the
        report's per-feature score entries, so the explorer shows what the backend
        measured and how it was scored. Nothing here is recomputed.
        """
        report = self.report(audit_id)
        if report.scores is None:
            raise Unavailable(
                "features_unavailable",
                f"feature checks did not run for an audit that is {report.status}",
            )
        raw = self._read(audit_id, "features/feature_results.jsonl")
        if raw is None:
            raise Unavailable(
                "features_unavailable", "the feature results of this audit are missing"
            )
        try:
            results = [
                FeatureResult.model_validate_json(line)
                for line in raw.decode("utf-8").split("\n")[:-1]
                if line.strip()
            ]
        except (UnicodeDecodeError, ValidationError):
            raise Unavailable(
                "features_unreadable", "the stored feature results could not be read"
            ) from None
        grouped: dict[str, list[FeatureResult]] = {}
        for result in results:
            grouped.setdefault(result.feature_id, []).append(result)
        features = []
        for entry in report.features:
            own = grouped.get(entry["feature_id"], [])
            features.append(
                {
                    **entry,
                    "result_count": len(own),
                    "results": [
                        {
                            "status": r.status,
                            "scope": r.scope,
                            "url": r.subject_url,
                            "observed_value": r.observed_value,
                            "expected_value": r.expected_value,
                            "severity": r.severity,
                            "explanation": r.explanation,
                            "error_message": r.error_message,
                            "measurement_method": r.measurement_method,
                            "limitations": list(r.limitations[:5]),
                            "is_heuristic": r.is_heuristic,
                            "evidence": [
                                {
                                    "source_url": e.source_url,
                                    "source_type": e.source_type,
                                    "snippet": e.snippet[:_MAX_SNIPPET],
                                }
                                for e in r.evidence[:_MAX_EVIDENCE]
                            ],
                        }
                        for r in own[:_MAX_RESULTS_PER_FEATURE]
                    ],
                }
            )
        return {
            "audit_id": audit_id,
            "status": report.status,
            "catalog_version": report.scores.get("catalog_version"),
            "scoring_version": report.scores.get("scoring_version"),
            "features": features,
        }

    def recommendations(self, audit_id: str) -> dict[str, Any]:
        report = self.report(audit_id)
        if report.recommendations is None or not report.recommendations_validated:
            raise Unavailable(
                "recommendations_unavailable",
                f"no validated recommendations exist for an audit that is {report.status}",
            )
        data = report.recommendations.model_dump(mode="json")
        return {
            "audit_id": audit_id,
            "status": report.status,
            "count": len(report.recommendations.recommendations),
            "recommendations": data["recommendations"],
            "rejected": data["rejected"],
            "notes": data["notes"],
        }

    # --- comparison ----------------------------------------------------------------------

    def compare(self, before_id: str, after_id: str) -> Comparison:
        before, after = self.get(before_id), self.get(after_id)
        reports: list[AuditReport | None] = []
        for record in (before, after):
            try:
                reports.append(self.report(record.audit_id))
            except Unavailable:
                reports.append(None)
        comparison_id = (
            "cmp_" + hashlib.sha256(f"{before_id}|{after_id}".encode()).hexdigest()[:16]
        )
        try:
            if reports[0] is None or reports[1] is None:
                from geoptimiser.app.compare import check_compatible

                check_compatible(before, after, reports[0], reports[1])
            result = compare_reports(
                comparison_id, before, after, reports[0], reports[1]
            )  # type: ignore[arg-type]
        except CompareError as exc:
            raise Incompatible(exc.code, str(exc)) from None
        relpath = f"comparisons/{comparison_id}.json"
        write_json_atomic_overwrite(
            self.data_dir / relpath, result.model_dump(mode="json")
        )
        self.store.save_comparison(
            comparison_id,
            before_id,
            after_id,
            before.normalized_url,
            relpath,
            self.clock(),
        )
        return result

    def get_comparison(self, comparison_id: str) -> Comparison:
        if not re.fullmatch(r"cmp_[0-9a-f]{16}", comparison_id):
            raise InvalidAuditId("invalid_comparison_id", "invalid comparison id")
        try:
            row = self.store.get_comparison_by_id(comparison_id)
        except NotFound:
            raise AuditNotFound(
                "comparison_not_found", "no comparison with this id"
            ) from None
        path = (self.data_dir / row["relpath"]).resolve()
        if not path.is_relative_to(self.data_dir.resolve()) or not path.is_file():
            raise Unavailable(
                "comparison_unavailable", "the stored comparison is missing"
            )
        return Comparison.model_validate_json(path.read_bytes())

    # --- catalog ---------------------------------------------------------------------

    def catalog(self) -> dict[str, Any]:
        """The shipped feature catalog with the default value of each threshold.

        This describes what each feature *is* (definition, implementation status,
        scoring role). It says nothing about any audit's result.
        """
        if self._catalog is None:
            import json

            from geoptimiser.features.config import FeatureConfig
            from geoptimiser.features.registry import default_registry
            from geoptimiser.validation.levels import validation_levels

            catalog = default_registry().catalog
            config = FeatureConfig().model_dump(mode="json")
            levels = validation_levels()
            data = json.loads(catalog.to_json())
            for feature in data["features"]:
                feature["config_defaults"] = {
                    k: config[k] for k in feature.get("config_keys", ()) if k in config
                }
                feature["validation"] = levels.get(feature["feature_id"])
            self._catalog = data
        return self._catalog

    # --- readiness -----------------------------------------------------------------------

    def ready(self) -> tuple[bool, dict[str, bool]]:
        checks = {"database": False, "data_dir": False, "workers": self.runner.alive}
        try:
            self.store.check()
            checks["database"] = True
            probe = self.data_dir / ".write-probe"
            probe.write_bytes(b"")
            probe.unlink()
            checks["data_dir"] = True
        except Exception:
            pass
        return all(checks.values()), checks


def write_json_atomic_overwrite(path: Path, document: Any) -> None:
    """Replace a derived JSON file (comparisons are recomputable, unlike audits)."""
    # A unique temporary file and one atomic rename: the old exists()/unlink()/write
    # sequence let two concurrent writers of the same comparison collide on a shared
    # temporary name or fail with FileExistsError (security audit run 1, hardening).
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
