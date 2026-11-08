"""A local mock HTTP server and helpers; tests never touch the real network."""

import ipaddress
import shutil
import ssl
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from geoptimiser.crawler import CrawlConfig, LocalBodyStore, SafeFetcher


@dataclass
class Route:
    status: int = 200
    body: bytes = b""
    content_type: str | None = "text/html; charset=utf-8"
    headers: dict[str, str] = field(default_factory=dict)
    chunked: bool = False
    drip_seconds: float | None = None  # send one byte per interval, forever
    endless: bool = False  # stream data forever with no Content-Length
    content_length: int | None = None  # override the (honest) Content-Length
    raw_headers: list[tuple[str, str]] = field(default_factory=list)  # repeatable
    cut_chunked: bool = False  # promise a 1000-byte chunk, send `body`, hang up


class MockSite:
    def __init__(self) -> None:
        self.routes: dict[str, Route] = {}
        self.requests: list[tuple[str, dict[str, str]]] = []
        self.port = 0

    def add(self, path: str, body: str | bytes = b"", **kwargs: object) -> None:
        data = body.encode() if isinstance(body, str) else body
        self.routes[path] = Route(body=data, **kwargs)  # type: ignore[arg-type]

    def html(self, path: str, *links: str, title: str = "t") -> None:
        anchors = "".join(f'<a href="{href}">x</a>' for href in links)
        self.add(path, f"<html><title>{title}</title><body>{anchors}</body></html>")

    def url(self, path: str = "/", host: str = "site.test") -> str:
        return f"http://{host}:{self.port}{path}"

    def paths_requested(self) -> list[str]:
        return [path for path, _ in self.requests]


def _handler(site: MockSite) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: object) -> None:
            pass

        def do_GET(self) -> None:  # noqa: N802
            site.requests.append(
                (self.path, {k.lower(): v for k, v in self.headers.items()})
            )
            route = site.routes.get(self.path.split("?")[0]) or site.routes.get(
                self.path
            )
            if route is None:
                route = Route(status=404, body=b"nope")
            try:
                self._send(route)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

        def _send(self, route: Route) -> None:
            self.send_response(route.status)
            if route.content_type:
                self.send_header("Content-Type", route.content_type)
            for name, value in route.headers.items():
                self.send_header(name, value)
            for name, value in route.raw_headers:
                self.send_header(name, value)
            self.send_header("Connection", "close")
            if route.endless or route.drip_seconds is not None:
                self.end_headers()
                while True:
                    self.wfile.write(b"a" * (1 if route.drip_seconds else 8192))
                    self.wfile.flush()
                    if route.drip_seconds:
                        time.sleep(route.drip_seconds)
            elif route.cut_chunked:
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                self.wfile.write(b"3e8\r\n" + route.body)
            elif route.chunked:
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                for i in range(0, len(route.body), 100):
                    part = route.body[i : i + 100]
                    self.wfile.write(f"{len(part):x}\r\n".encode() + part + b"\r\n")
                self.wfile.write(b"0\r\n\r\n")
            else:
                length = len(route.body)
                if route.content_length is not None:
                    length = route.content_length
                self.send_header("Content-Length", str(length))
                self.end_headers()
                self.wfile.write(route.body)

    return Handler


def _serve(
    mock: MockSite, context: ssl.SSLContext | None = None
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(mock))
    server.daemon_threads = True
    if context is not None:
        server.socket = context.wrap_socket(server.socket, server_side=True)
    mock.port = server.server_address[1]
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    return server, thread


@pytest.fixture
def site() -> Iterator[MockSite]:
    mock = MockSite()
    server, _ = _serve(mock)
    yield mock
    server.shutdown()
    server.server_close()


@dataclass(frozen=True)
class TlsMaterials:
    """A throw-away CA, a ``site.test`` leaf signed by it, and an unrelated CA."""

    ca: Path
    leaf_cert: Path
    leaf_key: Path
    other_ca: Path


def _openssl(cwd: Path, *args: str) -> None:
    subprocess.run(["openssl", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture(scope="session")
def tls_materials(tmp_path_factory: pytest.TempPathFactory) -> TlsMaterials:
    if shutil.which("openssl") is None:
        pytest.skip("the openssl CLI is needed to generate test certificates")
    d = tmp_path_factory.mktemp("tls")
    for name in ("ca", "other"):
        _openssl(
            d, "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", f"{name}.key", "-out", f"{name}.pem", "-days", "2",
            "-subj", f"/CN=test-{name}",
            "-addext", "basicConstraints=critical,CA:TRUE",
            "-addext", "keyUsage=critical,keyCertSign",
        )  # fmt: skip
    _openssl(
        d, "req", "-newkey", "rsa:2048", "-nodes", "-keyout", "leaf.key",
        "-out", "leaf.csr", "-subj", "/CN=site.test",
    )  # fmt: skip
    (d / "ext").write_text("subjectAltName=DNS:site.test\n")
    _openssl(
        d, "x509", "-req", "-in", "leaf.csr", "-CA", "ca.pem", "-CAkey", "ca.key",
        "-CAcreateserial", "-out", "leaf.pem", "-days", "2", "-extfile", "ext",
    )  # fmt: skip
    return TlsMaterials(d / "ca.pem", d / "leaf.pem", d / "leaf.key", d / "other.pem")


@pytest.fixture
def tls_site(tls_materials: TlsMaterials) -> Iterator[MockSite]:
    """The mock site served over HTTPS with the ``site.test`` certificate."""
    mock = MockSite()
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(tls_materials.leaf_cert, tls_materials.leaf_key)
    server, _ = _serve(mock, context)
    yield mock
    server.shutdown()
    server.server_close()


def loopback_only(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Test-only IP policy: the mock server lives on loopback."""
    return ip.is_loopback


@pytest.fixture
def make_config(site: MockSite) -> Callable[..., CrawlConfig]:
    def build(**overrides: object) -> CrawlConfig:
        fields: dict[str, object] = {
            "allowed_ports": frozenset({site.port}),
            "min_request_interval_seconds": 0,
            "request_timeout_seconds": 5,
            "max_fetch_seconds": 10,
        }
        return CrawlConfig(**(fields | overrides))  # type: ignore[arg-type]

    return build


@pytest.fixture
def store(tmp_path: Path) -> LocalBodyStore:
    return LocalBodyStore(tmp_path / "bodies")


@pytest.fixture
def make_fetcher(
    site: MockSite, store: LocalBodyStore, make_config: Callable[..., CrawlConfig]
) -> Callable[..., SafeFetcher]:
    """A fetcher whose fake DNS sends every name to the loopback mock server."""

    def build(config: CrawlConfig | None = None, **kwargs: object) -> SafeFetcher:
        options: dict[str, object] = {
            "resolver": lambda host, port: ["127.0.0.1"],
            "ip_policy": loopback_only,
        }
        return SafeFetcher(
            config or make_config(),
            store,
            "aud_test",
            **(options | kwargs),  # type: ignore[arg-type]
        )

    return build
