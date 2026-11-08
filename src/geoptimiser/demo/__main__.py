"""``python -m geoptimiser.demo --out demo_output``: a reproducible end-to-end demo.

It audits a bundled mock site ("before"), "fixes" part of it, audits again ("after"),
compares the two, and writes JSON and HTML reports plus a short summary. No API key, no
external network and no model download are needed. All results are **demo data**.
"""

import argparse
import http.client
import json
import re
import shutil
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path

from geoptimiser.agent import AgentConfig, ChatMessage
from geoptimiser.app import (
    AppConfig,
    AuditOptions,
    AuditService,
    AuditSubmission,
    PipelineDeps,
)
from geoptimiser.crawler import SafeFetcher

URL = "http://demo.acme.test/"
BRAND = "Acme Widgets (DEMO DATA)"
PUBLIC_IP = (
    "93.184.216.34"  # a public-looking address; the TCP connection is redirected
)
_ROUTES = {
    "/": "index.html",
    "/about": "about.html",
    "/pricing": "pricing.html",
    "/faq": "faq.html",
    "/blog-how-we-price": "blog-how-we-price.html",
    "/robots.txt": "robots.txt",
}
_ORDER = (
    "list_findings",
    "get_finding",
    "validate_evidence",
    "generate_recommendations",
    "validate_output",
)


def _load(phase: str) -> dict[str, bytes]:
    root = resources.files("geoptimiser.demo") / "site"
    pages = {name: (root / "before" / name).read_bytes() for name in _ROUTES.values()}
    if phase == "after":  # overlay: the fixed pages
        for item in (root / "after").iterdir():
            pages[item.name] = item.read_bytes()
    return pages


class DemoSite:
    """The mock website, served from memory (no request ever touches the filesystem)."""

    def __init__(self) -> None:
        self.pages = _load("before")
        site = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: object) -> None:
                pass

            def do_GET(self) -> None:  # noqa: N802
                name = _ROUTES.get(self.path.split("?")[0])
                body = site.pages.get(name or "", b"not found")
                self.send_response(200 if name else 404)
                kind = (
                    "text/plain" if name == "robots.txt" else "text/html; charset=utf-8"
                )
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def phase(self, phase: str) -> None:
        self.pages = _load(phase)

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def fetcher_factory(site: DemoSite) -> Callable[..., SafeFetcher]:
    """The real ``SafeFetcher`` (public-IP policy enabled) with DNS and the TCP
    connection pointed at the local demo site. Only the demo does this."""

    def connect(scheme, host, port, ip, timeout, policy):  # noqa: ANN001
        return http.client.HTTPConnection("127.0.0.1", site.port, timeout=timeout)

    def build(config, store, audit_id, allowed):  # noqa: ANN001
        return SafeFetcher(config, store, audit_id, host_allowed=allowed,
                           resolver=lambda h, p: [PUBLIC_IP], connection_factory=connect)  # fmt: skip

    return build


class DemoModel:
    """A rule-based FAKE model: it picks the next unused tool by reading the prompt.

    It stands in for the OpenRouter model so the demo needs no key or network. It makes
    no judgement of its own; the agent's tools and validation do the real work.
    """

    provider = "demo-fake-model"
    model_id = "demo/rule-based-fake"

    def complete(self, messages: list[ChatMessage]) -> str:
        text = messages[-1].content
        done = set(re.findall(r"^\d+\. (\w+) -> ok", text, re.M))
        for tool in _ORDER:
            if tool in done:
                continue
            args: dict[str, str] = {}
            if tool == "get_finding":
                found = re.search(r'"finding_id": "(fnd_[A-Za-z0-9_]+)"', text)
                if not found:
                    break
                args["finding_id"] = found.group(1)
            return json.dumps(
                {"thought": f"demo: next step is {tool}", "action": tool, "args": args}
            )
        return json.dumps(
            {"action": "finish", "args": {}, "summary": "demo fake model finished"}
        )


@dataclass
class DemoResult:
    out: Path
    before: str
    after: str
    comparison_id: str
    agent_used: bool


def _agent_available() -> bool:
    try:
        import langgraph  # noqa: F401
    except ImportError:
        return False
    return True


def run_demo(
    out: Path, *, use_agent: bool | None = None, force: bool = False
) -> DemoResult:
    if out.exists() and any(out.iterdir()):
        if not force:
            raise SystemExit(
                f"{out} is not empty; choose another --out or pass --force"
            )
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    agent = _agent_available() if use_agent is None else use_agent
    site = DemoSite()
    service = AuditService(
        AppConfig(
            data_dir=out / "data",
            crawl_overrides={"min_request_interval_seconds": 0},
            agent=AgentConfig(retry_delay_seconds=0),
        ),
        deps=PipelineDeps(fetcher_factory=fetcher_factory(site), model_factory=lambda cfg: DemoModel(), sleep=lambda s: None),
    )  # fmt: skip
    try:
        ids = []
        for phase in ("before", "after"):
            site.phase(phase)
            record = service.submit(
                AuditSubmission(
                    url=URL,
                    brand_name=BRAND,
                    authorization_confirmed=True,
                    options=AuditOptions(
                        max_pages=10, retrieval="lexical", use_agent=agent
                    ),
                )  # fmt: skip
            )
            service.runner.wait_idle(120)
            done = service.get(record.audit_id)
            ids.append(done.audit_id)
            print(f"[{phase}] audit {done.audit_id}: {done.status}", file=sys.stderr)
            report = out / f"report_{phase}"
            (report.with_suffix(".json")).write_text(
                service.report(done.audit_id).model_dump_json(indent=2),
                encoding="utf-8",
            )
            report.with_suffix(".html").write_text(
                service.report_html(done.audit_id), encoding="utf-8"
            )
        comparison = service.compare(ids[0], ids[1])
        (out / "comparison.json").write_text(
            comparison.model_dump_json(indent=2), encoding="utf-8"
        )
        _write_summary(out, service, ids, comparison.model_dump(mode="json"), agent)
        return DemoResult(out, ids[0], ids[1], comparison.comparison_id, agent)
    finally:
        service.close()
        site.close()


def _write_summary(
    out: Path, service: AuditService, ids: list[str], comparison: dict, agent: bool
) -> None:
    before = service.report(ids[0])
    chosen = None
    by_id = {rf.finding.finding_id: rf for rf in before.findings}
    for fid in (
        "fnd_F021",
        "fnd_F024",
        "fnd_F022",
        "fnd_F035",
    ):  # clearest teaching cases
        if fid in by_id and by_id[fid].measurements:
            chosen = by_id[fid]
            break
    chosen = chosen or (before.findings[0] if before.findings else None)
    lines = [
        "# Demo summary (DEMO DATA)",
        "",
        "Everything below comes from a bundled mock website (`demo.acme.test`), audited by the",
        "real pipeline. The site, its defects and the fake model are demo fixtures, not real",
        "observations of any real website or AI provider. The site is served over plain HTTP on",
        "loopback, so HTTPS-related findings are expected demo artifacts.",
        "",
        f"- Before audit: `{ids[0]}` ({before.status}); after audit: `{ids[1]}`",
        f"- Agent step: {'run with a rule-based FAKE model (no network)' if agent else 'not run (install .[agent] to include it)'}",
        f"- Overall score before: {before.scores['overall']['score'] if before.scores and before.scores['overall']['reportable'] else 'not reportable (coverage below threshold)'}",
        f"- Findings before: {len(before.findings)}; recommendations: {len(before.recommendations.recommendations) if before.recommendations else 0}",
        "",
    ]
    if chosen:
        f = chosen.finding
        lines += [f"## Traceable finding: {f.title}", "", f"- Finding `{f.finding_id}`, severity **{f.severity}**, basis **{f.basis}**",
                  f"- Method: {f.measurement_method}", ""]  # fmt: skip
        for m in chosen.measurements[:3]:
            lines.append(
                f"- Measured: `{m['url']}` status `{m['status']}`, observed `{m['observed_value']}`, expected `{m['expected_value']}`"
            )
        lines += ["", "### Evidence chain", ""]
        for e in chosen.evidence[:3]:
            where = (
                f"chunk `{e.chunk_id}`, characters {e.char_start}-{e.char_end} of document `{e.document_id}`"
                if e.chunk_id
                else "measurement evidence (no text span)"
            )
            lines += [
                f"- `{e.evidence_id}` from {e.source_url} ({where})",
                f"  > {e.snippet[:160]!r}",
            ]
        recs = [
            r
            for r in (
                before.recommendations.recommendations if before.recommendations else ()
            )
            if f.finding_id in r.finding_ids
        ]
        if recs:
            r = recs[0]
            lines += ["", f"### Recommendation `{r.recommendation_id}` ({r.priority}, effort {r.estimated_effort}, impact {r.expected_impact_direction})", "",
                      f"- Change: {r.proposed_change}", "- Verify:"] + [f"  - {v}" for v in r.verification_plan]  # fmt: skip
            status = next(
                (
                    c
                    for c in comparison["recommendations"]
                    if c["recommendation_id"] == r.recommendation_id
                ),
                None,
            )
            if status:
                lines += [
                    "",
                    f"After the demo site was edited, the later audit measured: **{status['status']}** - {status['detail']}",
                ]
    lines += ["", "## Before/after comparison", "", f"- Reliability: {comparison['reliability']}; caveats: {comparison['caveats'] or 'none'}",
              f"- Findings resolved: {[f['finding_id'] for f in comparison['findings_resolved']]}",
              f"- Findings persistent: {[f['finding_id'] for f in comparison['findings_persistent']]}",
              f"- Findings new: {[f['finding_id'] for f in comparison['findings_new']]}", "", comparison["statement"], "",
              "Open `report_before.html` and `report_after.html` in a browser, or browse the stored audits:", "",
              f"    python -m geoptimiser.app --data-dir {out / 'data'} serve", ""]  # fmt: skip
    (out / "SUMMARY.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m geoptimiser.demo", description=__doc__
    )
    parser.add_argument("--out", type=Path, default=Path("demo_output"))
    parser.add_argument(
        "--no-agent", action="store_true", help="skip the (fake-model) agent step"
    )
    parser.add_argument(
        "--force", action="store_true", help="replace an existing output directory"
    )
    args = parser.parse_args(argv)
    run_demo(args.out, use_agent=False if args.no_agent else None, force=args.force)
    print((args.out / "SUMMARY.md").read_text(encoding="utf-8"))
    print(
        f"Reports: {args.out / 'report_before.html'}  {args.out / 'report_after.html'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
