"""The end-to-end audit pipeline, built only from existing components (ADR-0024).

URL -> crawl -> extraction -> feature checks and scoring -> chunking -> retrieval ->
diagnosis -> recommendations -> optional agent -> final validation -> report.

Each stage is timed, logged and recorded. A failure in a critical stage fails the audit;
a failure in an optional stage leaves it ``incomplete``. Artifacts already written are
kept either way, and a report describing exactly what happened is always attempted.
"""

import json
import logging
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from geoptimiser.agent import (
    AgentContext,
    AgentRequest,
    ModelError,
    OpenRouterModel,
    run_agent,
    write_trace,
)
from geoptimiser.agent.models import AgentModel
from geoptimiser.app.config import AppConfig
from geoptimiser.app.models import (
    CRITICAL_STAGES,
    AuditRecord,
    ErrorCategory,
    StageName,
    StageRecord,
)
from geoptimiser.app.report import PipelineState, build_report, render_html
from geoptimiser.app.store import AuditStore
from geoptimiser.chunking import CHUNKER_VERSION, chunk_documents, read_chunks
from geoptimiser.crawler import (
    ArtifactWriter,
    CrawlConfig,
    Crawler,
    LocalBodyStore,
    SafeFetcher,
    read_fetches,
)
from geoptimiser.crawler.config import DEFAULT_USER_AGENT
from geoptimiser.crawler.urls import host_in_scope
from geoptimiser.diagnosis import (
    DiagnosisConfig,
    diagnose,
    validate_diagnosis,
    write_diagnosis,
)
from geoptimiser.diagnosis.engine import DIAGNOSIS_VERSION
from geoptimiser.extraction import ExtractionWriter, extract_all
from geoptimiser.extraction.pipeline import EXTRACTION_VERSION
from geoptimiser.features import load_inputs
from geoptimiser.features.audit import run_audit, write_artifacts
from geoptimiser.features.scoring import SCORING_VERSION
from geoptimiser.jsonl import write_json_atomic
from geoptimiser.recommendations import (
    TemplateGenerator,
    validate_recommendations,
    write_recommendations,
)
from geoptimiser.recommendations.generator import GENERATOR_VERSION
from geoptimiser.retrieval import (
    EmbeddingError,
    RetrievalSettings,
    Retriever,
    build_retriever,
    describe,
    load_settings,
)
from geoptimiser.schemas import AuditRequest, FetchRecord

log = logging.getLogger("geoptimiser.app")
FetcherFactory = Callable[
    [CrawlConfig, LocalBodyStore, str, Callable[[str], bool]], SafeFetcher
]
DEFAULT_AGENT_GOAL = (
    "Produce validated, evidence-linked recommendations for this audit."
)


def default_fetcher_factory(
    config: CrawlConfig,
    store: LocalBodyStore,
    audit_id: str,
    host_allowed: Callable[[str], bool],
) -> SafeFetcher:
    """The production fetcher: pinned public IPs, verified TLS, manual redirects."""
    return SafeFetcher(config, store, audit_id, host_allowed=host_allowed)


def default_model_factory(config: Any) -> AgentModel:
    return OpenRouterModel(config.model)


@dataclass
class PipelineDeps:
    """Seams for tests and operators. None of them is reachable through the API."""

    fetcher_factory: FetcherFactory = default_fetcher_factory
    model_factory: Callable[[Any], AgentModel] = default_model_factory
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    sleep: Callable[[float], None] = time.sleep


class StageFailure(Exception):
    """A stage could not do its job; carries a category and a safe message."""

    def __init__(self, category: ErrorCategory, message: str) -> None:
        super().__init__(message)
        self.category = category


class _Abort(Exception):
    """A critical stage failed; stop running further stages."""


def _emit(event: str, **fields: Any) -> None:
    """One structured log line: codes, counts and timings only, never page content."""
    log.info(json.dumps({"event": event, **fields}, sort_keys=True, default=str))


_TRANSPORT_CATEGORY: dict[str, ErrorCategory] = {
    "dns": "dns",
    "tls": "tls",
    "timeout": "timeout",
    "connection": "connection",
    "blocked_address": "blocked_target",
    "blocked_port": "blocked_target",
    "blocked_url": "blocked_target",
}
_SAFE_MESSAGES: dict[ErrorCategory, str] = {
    "dns": "the host name could not be resolved",
    "tls": "the TLS handshake or certificate verification failed",
    "timeout": "the site did not respond in time",
    "connection": "a connection to the site could not be established",
    "blocked_target": "the target resolves to a non-public address or uses a port that is not allowed, and was refused",
    "http_error": "the site answered with an HTTP error",
    "crawl_error": "the site could not be crawled",
}


def classify_seed_failure(fetches: list[FetchRecord]) -> StageFailure:
    """Why nothing could be audited, judged from the first page fetch."""
    pages = [f for f in fetches if f.requested_url.path != "/robots.txt"]
    seed = pages[0] if pages else (fetches[0] if fetches else None)
    if seed is None:
        return StageFailure("crawl_error", "no request was made")
    if not pages and seed.outcome in ("success", "http_error"):
        return StageFailure(
            "crawl_error", "robots.txt does not allow this site to be crawled"
        )
    if seed.outcome == "transport_error" and seed.error_type:
        category = _TRANSPORT_CATEGORY.get(seed.error_type, "crawl_error")
        return StageFailure(category, _SAFE_MESSAGES[category])
    if seed.outcome == "http_error":
        return StageFailure(
            "http_error", f"{_SAFE_MESSAGES['http_error']} ({seed.status_code})"
        )
    if seed.outcome == "redirect_not_followed":
        return StageFailure(
            "crawl_error",
            f"a redirect was not followed ({seed.redirect_refusal_reason})",
        )
    return StageFailure(
        "no_content", "the site returned no HTML page that could be audited"
    )


class PipelineRun:
    def __init__(
        self,
        record: AuditRecord,
        store: AuditStore,
        config: AppConfig,
        deps: PipelineDeps,
    ) -> None:
        self.record, self.store, self.config, self.deps = record, store, config, deps
        self.dir = config.data_dir / store.artifact_dir(record.audit_id)
        self.rel = Path(store.artifact_dir(record.audit_id))
        self.state = PipelineState()
        self.stages: dict[str, StageRecord] = {}
        self.request = AuditRequest(
            audit_id=record.audit_id,
            target_domain=record.domain,
            brand_name=record.brand_name or record.domain,
            business_context="web audit",
            target_audience="n/a",
            authorization_confirmed=True,
        )
        self.crawl_config = self._crawl_config()
        self.retriever: Retriever | None = None
        self.documents: list[Any] = []

    # --- configuration -------------------------------------------------------------

    def _crawl_config(self) -> CrawlConfig:
        opts = self.record.options
        fields: dict[str, Any] = {
            "max_pages": min(opts.max_pages, self.config.max_pages_cap),
            "max_depth": min(opts.max_depth, self.config.max_depth_cap),
        }
        return CrawlConfig(**(fields | self.config.crawl_overrides))

    # --- stage plumbing ------------------------------------------------------------

    def stage(self, name: StageName, fn: Callable[[], dict[str, Any] | None]) -> None:
        started = self.deps.clock()
        t0 = time.monotonic()
        self.store.set_stage_pointer(self.record.audit_id, name)
        running = StageRecord(name=name, status="running", started_at=started)
        self.store.save_stage(self.record.audit_id, running)
        status, category, message, detail = "ok", None, None, {}
        try:
            detail = fn() or {}
            if detail.pop("_skipped", False):
                status = "skipped"
        except StageFailure as failure:
            status, category, message = "failed", failure.category, str(failure)
        except Exception as exc:  # a stage bug must not take the service down
            status, category = "failed", "internal_error"
            message = f"unexpected {type(exc).__name__}"
        duration = (time.monotonic() - t0) * 1000
        record = StageRecord(
            name=name, status=status, started_at=started,  # type: ignore[arg-type]
            finished_at=self.deps.clock(), duration_ms=round(duration, 1),
            error_category=category, error_message=message, detail=detail,
        )  # fmt: skip
        self.stages[name] = record
        self.store.save_stage(self.record.audit_id, record)
        _emit("stage", audit_id=self.record.audit_id, stage=name, status=status,
              duration_ms=round(duration, 1), error_category=category)  # fmt: skip
        if status == "failed" and name in CRITICAL_STAGES:
            raise _Abort

    def skip(self, name: StageName, reason: str) -> None:
        self.stage(name, lambda: {"_skipped": True, "reason": reason})

    def register(self, name: str, *parts: str) -> None:
        path = self.rel.joinpath(*parts)
        if (self.config.data_dir / path).exists():
            self.store.register_artifact(
                self.record.audit_id, name, path.as_posix(), self.config.data_dir
            )

    # --- the stages ----------------------------------------------------------------

    def validate(self) -> dict[str, Any]:
        return {
            "max_pages": self.crawl_config.max_pages,
            "max_depth": self.crawl_config.max_depth,
        }

    def crawl(self) -> dict[str, Any]:
        store = LocalBodyStore(self.dir / "bodies")
        domain = self.record.domain
        fetcher = self.deps.fetcher_factory(
            self.crawl_config, store, self.record.audit_id,
            lambda host: host_in_scope(host, domain),
        )  # fmt: skip
        try:
            with ArtifactWriter(self.dir) as sink:
                result = Crawler(
                    self.request, self.crawl_config, fetcher,
                    seed_url=self.record.target_url, sink=sink,
                    sleep=self.deps.sleep,
                ).run()  # fmt: skip
        finally:
            for name in ("fetches.jsonl", "skipped_urls.jsonl", "crawl_summary.json"):
                self.register(name, name)
        fetches = list(result.fetches)
        self.state.fetches = fetches
        self.state.crawl_summary = {
            "stop_reason": result.stop_reason,
            "fetch_count": len(fetches),
            "skipped_count": len(result.skipped),
            "max_pages": self.crawl_config.max_pages,
            "max_depth": self.crawl_config.max_depth,
            "respect_robots": self.crawl_config.respect_robots,
            "user_agent": self.crawl_config.user_agent,
            "robots_skipped": sum(
                1 for s in result.skipped if s.reason == "robots_disallowed"
            ),
            # Bodies cut at the response-size limit: the page was only partly seen.
            "truncated_bodies": sum(
                1 for f in fetches if f.body is not None and f.body.truncated
            ),
        }
        pages = [
            f
            for f in fetches
            if f.outcome == "success" and f.requested_url.path != "/robots.txt"
        ]
        if not pages:
            raise classify_seed_failure(fetches)
        return {"fetches": len(fetches), "pages_ok": len(pages), "stop_reason": result.stop_reason,
                "errors": dict(Counter(f.error_type for f in fetches if f.error_type))}  # fmt: skip

    def extract(self) -> dict[str, Any]:
        store = LocalBodyStore(self.dir / "bodies")
        fetches = read_fetches(self.dir / "fetches.jsonl")
        try:
            with ExtractionWriter(self.dir / "extraction") as sink:
                result = extract_all(fetches, store, sink=sink, clock=self.deps.clock)
        finally:
            self.register("documents.jsonl", "extraction", "documents.jsonl")
        self.documents = list(result.documents)
        self.state.crawl_summary["truncated_documents"] = sum(
            1 for d in self.documents if d.source_truncated or d.truncated_fields
        )
        if not self.documents:
            raise StageFailure("no_content", "no page could be extracted into text")
        return {
            "documents": len(self.documents),
            "failures": len(result.failures),
            "skipped": len(result.skipped),
        }

    def features(self) -> dict[str, Any]:
        run = run_audit(load_inputs(self.dir))
        write_artifacts(run, self.dir / "features")
        for name in (
            "feature_results.jsonl",
            "evidence.jsonl",
            "findings.jsonl",
            "features.json",
        ):
            self.register(f"features/{name}", "features", name)
        self.state.run = run
        overall = run.scores.overall
        return {"results": len(run.results), "findings": len(run.findings),
                "score": overall.score, "reportable": overall.reportable}  # fmt: skip

    def chunk(self) -> dict[str, Any]:
        count = chunk_documents(self.documents, self.dir / "chunks.jsonl")
        self.register("chunks.jsonl", "chunks.jsonl")
        self.state.chunks = read_chunks(self.dir / "chunks.jsonl")
        return {"chunks": count}

    def retrieval(self) -> dict[str, Any]:
        mode = self.record.options.retrieval
        info: dict[str, Any] = {
            "requested": mode,
            "status": "skipped",
            "semantic": False,
        }
        self.state.retrieval = info
        if mode == "off":
            return {"_skipped": True, "reason": "retrieval not requested"}
        if not self.state.chunks:
            return {"_skipped": True, "reason": "no chunks to index"}
        if mode == "lexical":
            self.retriever = Retriever(self.state.chunks)
            info |= {"status": "ok", "mode": "lexical", "embedder": None}
            return {"mode": "lexical"}
        info["status"] = "unavailable"
        try:
            settings = (
                load_settings(self.config.retrieval_settings_path)
                if self.config.retrieval_settings_path
                else RetrievalSettings()
            )
            self.retriever = build_retriever(self.state.chunks, settings)
        except EmbeddingError as exc:
            # Never substitute lexical retrieval for a semantic request.
            raise StageFailure(
                "retrieval_unavailable",
                f"semantic retrieval is unavailable ({type(exc).__name__})",
            ) from None
        descriptor = (
            describe(self.retriever.embedder) if self.retriever.embedder else None
        )
        info |= {"status": "ok", "mode": "hybrid", "semantic": True,
                 "embedder": descriptor.model_dump(mode="json") if descriptor else None}  # fmt: skip
        return {"mode": "hybrid"}

    def diagnose(self) -> dict[str, Any]:
        assert self.state.run is not None
        mode = "hybrid" if self.state.retrieval.get("semantic") else "lexical"
        self.state.diagnosis = diagnose(
            self.state.run, self.state.chunks, retriever=self.retriever,
            config=DiagnosisConfig(retrieval_mode=mode), clock=self.deps.clock,
        )  # fmt: skip
        write_diagnosis(self.dir / "findings.json", self.state.diagnosis)
        self.register("findings.json", "findings.json")
        return {"findings": len(self.state.diagnosis.findings)}

    def recommend(self) -> dict[str, Any]:
        assert self.state.diagnosis is not None
        result = TemplateGenerator().generate(self.state.diagnosis, self.deps.clock)
        self.state.recommendations = result
        write_recommendations(self.dir / "recommendations.json", result)
        self.register("recommendations.json", "recommendations.json")
        return {
            "recommendations": len(result.recommendations),
            "rejected": len(result.rejected),
        }

    def agent(self) -> dict[str, Any]:
        assert self.state.run is not None and self.state.diagnosis is not None
        info: dict[str, Any] = {
            "requested": True,
            "status": "failed",
            "model_id": self.config.agent.model.model_id,
        }
        self.state.agent = info
        if not self.config.agent_enabled:
            info["status"] = "disabled"
            raise StageFailure(
                "agent_unavailable", "the agent is disabled on this server"
            )
        try:
            model = self.deps.model_factory(self.config.agent)
            context = AgentContext.create(
                self.state.run, self.state.chunks, retriever=self.retriever,
                diagnosis=self.state.diagnosis, clock=self.deps.clock,
            )  # fmt: skip
            result = run_agent(
                AgentRequest(audit=self.request, goal=DEFAULT_AGENT_GOAL),
                context, model, self.config.agent, clock=self.deps.clock,
            )  # fmt: skip
        except ModelError:
            info["status"] = "unavailable"
            raise StageFailure(
                "agent_unavailable",
                "the language model is not available (missing key, extra or access)",
            ) from None
        write_trace(self.dir / "agent_trace.json", result)
        self.register("agent_trace.json", "agent_trace.json")
        info |= {"status": result.status, "reason": result.reason,
                 "iterations_used": result.iterations_used, "provider": result.provider,
                 "model_id": result.model_id, "steps": len(result.steps),
                 "evidence_valid": result.evidence_valid, "output_valid": result.output_valid}  # fmt: skip
        if result.status == "failed":
            raise StageFailure(
                "agent_failed", f"the agent run failed ({result.reason[:80]})"
            )
        if result.status == "incomplete":
            raise StageFailure(
                "agent_incomplete",
                f"the agent run was incomplete ({result.reason[:80]})",
            )
        return {"status": result.status, "steps": len(result.steps)}

    def validate_output(self) -> dict[str, Any]:
        s = self.state
        assert (
            s.run is not None
            and s.diagnosis is not None
            and s.recommendations is not None
        )
        problems = [
            *validate_diagnosis(s.diagnosis, s.run, s.chunks),
            *validate_recommendations(s.recommendations, s.diagnosis),
        ]
        s.problems = problems
        if problems:
            raise StageFailure(
                "validation_failed",
                f"{len(problems)} grounding/validation problem(s); first: {problems[0][:120]}",
            )
        return {"problems": 0}

    # --- finish --------------------------------------------------------------------

    def outcome(self) -> tuple[str, str, ErrorCategory | None, str | None]:
        failed = [s for s in self.stages.values() if s.status == "failed"]
        critical = [s for s in failed if s.name in CRITICAL_STAGES]
        if critical:
            s = critical[0]
            return (
                "failed",
                f"stage '{s.name}' failed: {s.error_category}",
                s.error_category,
                s.error_message,
            )
        if failed:
            s = failed[0]
            return (
                "incomplete",
                f"optional stage '{s.name}' failed: {s.error_category}",
                s.error_category,
                s.error_message,
            )
        stop = self.state.crawl_summary.get("stop_reason")
        if stop in ("audit_timeout", "audit_byte_budget", "aborted"):
            return (
                "incomplete",
                f"the crawl stopped early ({stop})",
                "crawl_error",
                f"the crawl stopped early ({stop})",
            )
        return (
            "completed",
            "all requested stages completed and outputs were validated",
            None,
            None,
        )

    def versions(self) -> dict[str, Any]:
        run = self.state.run
        return {
            "extraction_version": EXTRACTION_VERSION,
            "chunker_version": CHUNKER_VERSION,
            "catalog_version": run.catalog_version if run else None,
            "scoring_version": SCORING_VERSION,
            "diagnosis_version": DIAGNOSIS_VERSION,
            "recommendation_generator": f"{TemplateGenerator.name}/{GENERATOR_VERSION}",
            "retrieval": self.state.retrieval
            or {"requested": self.record.options.retrieval},
            "agent": {
                "requested": self.record.options.use_agent,
                "model_id": self.config.agent.model.model_id
                if self.record.options.use_agent
                else None,
            },  # fmt: skip
            "crawl": {
                "max_pages": self.crawl_config.max_pages,
                "max_depth": self.crawl_config.max_depth,
                "respect_robots": self.crawl_config.respect_robots,
                "user_agent": DEFAULT_USER_AGENT,
            },  # fmt: skip
        }

    def summary(self, status: str) -> dict[str, Any]:
        run, diag, recs = (
            self.state.run,
            self.state.diagnosis,
            self.state.recommendations,
        )
        out: dict[str, Any] = {
            "pages_ok": sum(1 for f in self.state.fetches if f.outcome == "success" and f.requested_url.path != "/robots.txt"),
            "stages": {n: s.status for n, s in self.stages.items()},
            "agent": (self.state.agent or {}).get("status", "not_requested"),
            "retrieval": self.state.retrieval.get("status", "not_run"),
        }  # fmt: skip
        if run is not None:
            o = run.scores.overall
            out |= {"overall_score": o.score if o.reportable else None,
                    "score_reportable": o.reportable, "feature_coverage": o.feature_coverage,
                    "unit_coverage": o.unit_coverage}  # fmt: skip
        if diag is not None and not self.state.problems:
            out["findings"] = len(diag.findings)
            out["findings_by_severity"] = dict(
                Counter(f.severity for f in diag.findings)
            )
        if recs is not None and not self.state.problems:
            out["recommendations"] = len(recs.recommendations)
        return out

    def write_report(self, status: str, reason: str) -> None:
        stages = list(self.stages.values())
        self.state.versions = self.versions()
        report = build_report(
            self.record, stages, self.state, status=status, reason=reason,
            generated_at=self.deps.clock(),
        )  # fmt: skip
        document = report.model_dump(mode="json")
        page = render_html(report)  # render first: a failure here writes nothing
        json_path, html_path = self.dir / "report.json", self.dir / "report.html"
        try:
            write_json_atomic(json_path, document)
            tmp = self.dir / ".report.html.tmp"
            tmp.write_text(page, encoding="utf-8")
            tmp.replace(html_path)
        except BaseException:
            # Never leave a report that says "completed" for an audit that failed here.
            for path in (json_path, html_path, self.dir / ".report.html.tmp"):
                path.unlink(missing_ok=True)
            raise
        self.register("report.json", "report.json")
        self.register("report.html", "report.html")


def run_pipeline(
    audit_id: str,
    *,
    store: AuditStore,
    config: AppConfig,
    deps: PipelineDeps | None = None,
) -> None:
    """Run one queued audit to a terminal status. Never raises for audit problems.

    Anything unexpected (for example the database failing mid-run) still ends the audit
    as ``failed`` with a generic category, so no audit is left ``running`` by a crashed
    job. If even that cannot be recorded, the next start marks it ``interrupted``.
    """
    deps = deps or PipelineDeps()
    try:
        _run_pipeline(audit_id, store=store, config=config, deps=deps)
    except Exception as exc:
        _emit("audit_crashed", audit_id=audit_id, error_type=type(exc).__name__)
        try:
            store.finish(
                audit_id, "failed", deps.clock(), error_category="internal_error",
                error_message=f"the audit stopped unexpectedly ({type(exc).__name__})",
            )  # fmt: skip
        except Exception:
            pass  # nothing more can be recorded; recovery handles it on restart


def _run_pipeline(
    audit_id: str,
    *,
    store: AuditStore,
    config: AppConfig,
    deps: PipelineDeps | None = None,
) -> None:
    """Run one queued audit to a terminal status. Never raises for audit problems."""
    deps = deps or PipelineDeps()
    record = store.get_audit(audit_id)
    store.start(audit_id, deps.clock())
    run = PipelineRun(store.get_audit(audit_id), store, config, deps)
    _emit("audit_start", audit_id=audit_id, domain=record.domain)
    opts = record.options
    try:
        run.stage("validate", run.validate)
        run.stage("crawl", run.crawl)
        run.stage("extract", run.extract)
        run.stage("features", run.features)
        run.stage("chunk", run.chunk)
        run.stage("retrieval", run.retrieval)
        run.stage("diagnose", run.diagnose)
        run.stage("recommend", run.recommend)
        if opts.use_agent:
            run.stage("agent", run.agent)
        else:
            run.skip("agent", "the agent was not requested")
        run.stage("validate_output", run.validate_output)
    except _Abort:
        pass
    status, reason, category, message = run.outcome()
    try:
        run.stage("report", lambda: run.write_report(status, reason) or {})
    except _Abort:
        status, reason, category = "failed", "stage 'report' failed", "internal_error"
        message = run.stages["report"].error_message
    store.finish(
        audit_id, status, deps.clock(), error_category=category, error_message=message,
        summary=run.summary(status), pipeline=run.versions(),
    )  # fmt: skip
    _emit("audit_end", audit_id=audit_id, status=status, category=category)
