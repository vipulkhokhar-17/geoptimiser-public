"""The versioned HTTP API (FastAPI). Requires the ``api`` extra.

Local-first by design: no authentication and no multi-user isolation are provided, so it
is permanently bound to 127.0.0.1 (the CLI exposes no host override or remote-bind option). The
API accepts a URL and bounded options and nothing else: it never fetches an arbitrary
URL for the caller, reads an arbitrary path, or runs submitted code. Crawling happens only
inside the pipeline, through the crawler's SSRF-safe fetcher.
"""

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from geoptimiser.app.config import AppConfig
from geoptimiser.app.models import (
    AuditOptions,
    AuditRecord,
    AuditSubmission,
    StageRecord,
)
from geoptimiser.app.service import AuditService, ServiceError

try:
    from fastapi import FastAPI, Request, Response
    from fastapi.exceptions import RequestValidationError
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import HTMLResponse, JSONResponse
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError("the API needs FastAPI: pip install 'geoptimiser[api]'") from exc

log = logging.getLogger("geoptimiser.app.api")
UI_DIR = Path(__file__).parent / "ui"
MAX_BODY_BYTES = 16 * 1024
API_CSP = "default-src 'none'; frame-ancestors 'none'"
REPORT_CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; "
    "form-action 'none'; frame-ancestors 'none'"
)
UI_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
# The UI reads its API base from this script. The backend serves the same-origin value;
# the static (GitHub Pages) export ships its own file pointing at the deployed backend.
SAME_ORIGIN_CONFIG = 'window.GEOPTIMISER_CONFIG = {"apiBase": ""};\n'
_STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/ui/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/ui/config.js": (None, "text/javascript; charset=utf-8"),
    "/ui/style.css": ("style.css", "text/css; charset=utf-8"),
    "/ui/hanken-grotesk.woff2": ("hanken-grotesk.woff2", "font/woff2"),
    "/ui/jetbrains-mono.woff2": ("jetbrains-mono.woff2", "font/woff2"),
    "/ui/FONTS-LICENSE.txt": ("FONTS-LICENSE.txt", "text/plain; charset=utf-8"),
}


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AuditView(_Out):
    audit_id: str
    status: str
    stage: str | None
    target_url: str
    normalized_url: str
    domain: str
    brand_name: str | None
    error_category: str | None
    error_message: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None
    pipeline_version: str
    options: AuditOptions
    summary: dict[str, Any]
    pipeline: dict[str, Any]
    stages: list[StageRecord] | None = None
    links: dict[str, str]


class AuditList(_Out):
    audits: list[AuditView]


class Health(_Out):
    status: str


class Readiness(_Out):
    status: str
    checks: dict[str, bool]


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    before_audit_id: str = Field(min_length=1, max_length=64)
    after_audit_id: str = Field(min_length=1, max_length=64)


def _view(record: AuditRecord, stages: list[StageRecord] | None = None) -> AuditView:
    base = f"/api/v1/audits/{record.audit_id}"
    return AuditView(
        audit_id=record.audit_id,
        status=record.status,
        stage=record.stage,
        target_url=record.target_url,
        normalized_url=record.normalized_url,
        domain=record.domain,
        brand_name=record.brand_name,
        error_category=record.error_category,
        error_message=record.error_message,
        created_at=record.created_at.isoformat(),
        started_at=record.started_at.isoformat() if record.started_at else None,
        finished_at=record.finished_at.isoformat() if record.finished_at else None,
        pipeline_version=record.pipeline_version,
        options=record.options,
        summary=record.summary,
        pipeline=record.pipeline,
        stages=stages,
        links={
            "self": base,
            "findings": f"{base}/findings",
            "recommendations": f"{base}/recommendations",
            "report": f"{base}/report",
            "report_html": f"{base}/report.html",
            "features": f"{base}/features",
        },
    )


def _host_without_port(host: str) -> str:
    """The Host header's host part: "[::1]:8000" -> "[::1]", "[::1]" -> "[::1]"."""
    if host.startswith("["):
        end = host.find("]")
        return host[: end + 1] if end != -1 else host
    return host.rsplit(":", 1)[0]


def _error(status: int, code: str, message: str, request_id: str) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message, "request_id": request_id}},
        status_code=status,
    )


def create_app(service: AuditService) -> FastAPI:
    config: AppConfig = service.config
    allowed_hosts = {h.lower() for h in config.allowed_hosts}

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        service.close()

    app = FastAPI(
        lifespan=lifespan,
        title="Geoptimiser",
        version="1",
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/v1/openapi.json",
    )

    @app.middleware("http")
    async def guard(request: Request, call_next: Any) -> Response:
        request_id = uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        host = (request.headers.get("host") or "").lower()
        host = _host_without_port(host)
        if host not in allowed_hosts:
            return _error(
                400, "invalid_host", "this Host header is not allowed", request_id
            )
        if request.method == "POST":
            length = request.headers.get("content-length")
            if length is None or not length.isdigit() or int(length) > MAX_BODY_BYTES:
                return _error(
                    413,
                    "body_too_large",
                    "the request body is missing or too large",
                    request_id,
                )
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("Content-Security-Policy", API_CSP)
        response.headers["X-Request-Id"] = request_id
        return response

    if config.cors_origins:
        # Opt-in and narrow: exact origins, read/create methods, one header, no cookies
        # or credentials. Added after the guard so it wraps it (outermost).
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(config.cors_origins),
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
            allow_credentials=False,
            expose_headers=["X-Request-Id", "Location"],
            max_age=600,
        )

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, exc: ServiceError) -> JSONResponse:
        return _error(exc.status, exc.code, str(exc), request.state.request_id)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        problems = [
            {
                "field": ".".join(str(p) for p in e["loc"] if p != "body"),
                "problem": e["msg"],
            }
            for e in exc.errors()[:10]  # never echo the submitted values
        ]
        body = {"error": {"code": "invalid_request", "message": "the request is not valid",
                          "request_id": request.state.request_id, "problems": problems}}  # fmt: skip
        return JSONResponse(body, status_code=422)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.error('{"event":"unhandled","type":"%s"}', type(exc).__name__)
        return _error(
            500, "internal_error", "something went wrong", request.state.request_id
        )

    # --- operational ---------------------------------------------------------------

    @app.get("/api/v1/health", response_model=Health)
    def health() -> Health:
        return Health(status="ok")

    @app.get("/api/v1/ready", response_model=Readiness)
    def ready() -> JSONResponse:
        ok, checks = service.ready()
        return JSONResponse(
            {"status": "ready" if ok else "not_ready", "checks": checks},
            status_code=200 if ok else 503,
        )

    # --- audits --------------------------------------------------------------------

    @app.post("/api/v1/audits", status_code=202, response_model=AuditView)
    def submit(submission: AuditSubmission, response: Response) -> AuditView:
        record = service.submit(submission)
        response.headers["Location"] = f"/api/v1/audits/{record.audit_id}"
        return _view(record)

    @app.get("/api/v1/audits", response_model=AuditList)
    def list_audits(limit: int = 20) -> AuditList:
        return AuditList(audits=[_view(r) for r in service.list_audits(limit)])

    @app.get("/api/v1/audits/{audit_id}", response_model=AuditView)
    def get_audit(audit_id: str) -> AuditView:
        record = service.get(audit_id)
        return _view(record, service.stages(audit_id))

    @app.get("/api/v1/audits/{audit_id}/findings")
    def findings(audit_id: str) -> dict[str, Any]:
        return service.findings(audit_id)

    @app.get("/api/v1/audits/{audit_id}/features")
    def features(audit_id: str) -> dict[str, Any]:
        return service.features(audit_id)

    @app.get("/api/v1/catalog")
    def catalog() -> dict[str, Any]:
        return service.catalog()

    @app.get("/api/v1/audits/{audit_id}/recommendations")
    def recommendations(audit_id: str) -> dict[str, Any]:
        return service.recommendations(audit_id)

    @app.get("/api/v1/audits/{audit_id}/report")
    def report(audit_id: str, download: bool = False) -> Response:
        body = service.report(audit_id).model_dump_json()
        headers = (
            {"Content-Disposition": f'attachment; filename="{audit_id}.json"'}
            if download
            else {}
        )
        return Response(body, media_type="application/json", headers=headers)

    @app.get("/api/v1/audits/{audit_id}/report.html", response_class=HTMLResponse)
    def report_html(audit_id: str, download: bool = False) -> HTMLResponse:
        headers = {"Content-Security-Policy": REPORT_CSP}
        if download:
            headers["Content-Disposition"] = f'attachment; filename="{audit_id}.html"'
        return HTMLResponse(service.report_html(audit_id), headers=headers)

    # --- comparisons ---------------------------------------------------------------

    @app.post("/api/v1/comparisons")
    def compare(request: CompareRequest) -> dict[str, Any]:
        result = service.compare(request.before_audit_id, request.after_audit_id)
        return result.model_dump(mode="json")

    @app.get("/api/v1/comparisons/{comparison_id}")
    def get_comparison(comparison_id: str) -> dict[str, Any]:
        return service.get_comparison(comparison_id).model_dump(mode="json")

    # --- the bundled UI (a fixed list of files; no directory serving) -------------------

    def _static(path: str) -> Response:
        name, media = _STATIC[path]
        body = (
            SAME_ORIGIN_CONFIG.encode()
            if name is None
            else (UI_DIR / name).read_bytes()
        )
        headers = {"Content-Security-Policy": UI_CSP}
        if name and name.endswith(".woff2"):
            # Fonts are immutable package data: let the browser keep them.
            headers["Cache-Control"] = "public, max-age=604800, immutable"
        return Response(body, media_type=media, headers=headers)

    for route in _STATIC:
        app.add_api_route(route, lambda route=route: _static(route), methods=["GET"],
                          include_in_schema=False)  # fmt: skip

    return app
