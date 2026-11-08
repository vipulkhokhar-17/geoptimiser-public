"""A real Geoptimiser backend whose crawler is pointed at local synthetic sites.

Used by tests/e2e/browser_e2e.py. The audit pipeline, store, API and UI are the
production code; only DNS and the TCP connection of the (still SSRF-checked) fetcher are
redirected to an in-process server that serves one validation fixture at a time.

    python tests/e2e/e2e_server.py --data-dir /tmp/e2e --port 8811 --control-port 8812

``GET http://127.0.0.1:<control-port>/use/<fixture_id>`` switches the served fixture.
This control port is part of the test harness only; it is never part of the product.
"""

import argparse
import http.client
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import uvicorn

from geoptimiser.app import AppConfig, AuditService, PipelineDeps
from geoptimiser.app.api import create_app
from geoptimiser.crawler import SafeFetcher
from geoptimiser.validation.runner import _PUBLIC_IP, ServedSite
from geoptimiser.validation.spec import load_fixtures

FIXTURES = Path(__file__).resolve().parents[1] / "validation" / "fixtures"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8811)
    parser.add_argument("--control-port", type=int, default=8812)
    parser.add_argument("--fixture", default="combined_realistic_mix")
    args = parser.parse_args()
    specs = {s.id: s for s in load_fixtures(FIXTURES)}
    current = {"site": ServedSite(specs[args.fixture])}
    lock = threading.Lock()

    def connect(scheme, host, port, ip, timeout, policy):  # noqa: ANN001
        with lock:
            port_ = current["site"].port
        return http.client.HTTPConnection("127.0.0.1", port_, timeout=timeout)

    def factory(config, store, audit_id, allowed):  # noqa: ANN001
        return SafeFetcher(config, store, audit_id, host_allowed=allowed,
                           resolver=lambda h, p: [_PUBLIC_IP], connection_factory=connect)  # fmt: skip

    class Control(BaseHTTPRequestHandler):
        def log_message(self, *a: object) -> None:
            pass

        def do_GET(self) -> None:  # noqa: N802
            name = self.path.rsplit("/", 1)[-1]
            if not self.path.startswith("/use/") or name not in specs:
                self.send_response(404)
                self.end_headers()
                return
            with lock:
                old, current["site"] = current["site"], ServedSite(specs[name])
            old.close()
            self.send_response(204)
            self.end_headers()

    control = ThreadingHTTPServer(("127.0.0.1", args.control_port), Control)
    threading.Thread(target=control.serve_forever, daemon=True).start()
    config = AppConfig(
        data_dir=args.data_dir,
        agent_enabled=False,
        crawl_overrides={"min_request_interval_seconds": 0, "request_timeout_seconds": 2,
                         "max_fetch_seconds": 4},
    )  # fmt: skip
    service = AuditService(config, deps=PipelineDeps(fetcher_factory=factory))
    uvicorn.run(
        create_app(service), host="127.0.0.1", port=args.port, log_level="warning"
    )


if __name__ == "__main__":
    main()
