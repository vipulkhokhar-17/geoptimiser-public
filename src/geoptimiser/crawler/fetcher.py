"""Single-URL safe fetcher: pinned connections, manual redirects, bounded streaming.

Safety model (ADR-0009):

* DNS is resolved once per hop; every address must be public. The connection is
  made to the validated IP (never re-resolving the hostname, so DNS rebinding
  cannot swap the address), the connected peer is checked again, and TLS still
  verifies the certificate against the hostname.
* Redirects are never followed by the HTTP library. Each hop is validated before
  any connection is made.
* Bodies are streamed in chunks and cut off at ``max_bytes`` while reading;
  ``Content-Length`` is never trusted. A watchdog bounds the total fetch time.
"""

import functools
import http.client
import socket
import ssl
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urljoin, urlsplit

from pydantic import HttpUrl, TypeAdapter, ValidationError

from geoptimiser.crawler.config import CrawlConfig
from geoptimiser.crawler.netguard import (
    IPPolicy,
    PolicyViolation,
    Resolver,
    is_public_address,
    parse_ip,
    resolve_allowed,
    system_resolver,
)
from geoptimiser.crawler.storage import BodyStore, StorageError
from geoptimiser.schemas import (
    FetchRecord,
    FetchTimings,
    RedirectHop,
    TransportErrorType,
)

FetchKind = Literal["page", "robots"]
ConnectionFactory = Callable[
    [str, str, int, str, float, IPPolicy], http.client.HTTPConnection
]

_URL = TypeAdapter(HttpUrl)
_CHUNK = 16 * 1024
_MAX_IPS_TRIED = 4
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_DEFAULT_PORTS = {"http": 80, "https": 443}
_ACCEPT = {
    "page": "text/html,application/xhtml+xml;q=0.9",
    "robots": "text/plain",
}
_CONTENT_TYPES = {
    "page": frozenset({"text/html", "application/xhtml+xml"}),
    "robots": frozenset({"text/plain"}),
}
# Only headers relevant to GEO checks are recorded (an allow-list, ADR-0009).
_RECORDED_HEADERS = (
    "content-type",
    "content-length",
    "content-encoding",
    "last-modified",
    "etag",
    "cache-control",
    "x-robots-tag",
    "link",
    "location",
    "retry-after",
    "date",
    "strict-transport-security",  # F110 (RFC 6797); value capped like every header
)
_MAX_HEADER_VALUE = 2000
_MAX_LOCATION = 8192


def _open_pinned(ip: str, port: int, timeout: float, policy: IPPolicy) -> socket.socket:
    """Connect to ``ip`` and re-check the address that was actually connected."""
    sock = socket.create_connection((ip, port), timeout=timeout)
    try:
        peer = parse_ip(str(sock.getpeername()[0]))
        if not policy(peer):
            raise PolicyViolation(
                "blocked_address", f"connected to a non-public address ({peer})"
            )
    except BaseException:
        sock.close()
        raise
    return sock


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(
        self, host: str, port: int, ip: str, timeout: float, policy: IPPolicy
    ) -> None:
        super().__init__(host, port, timeout=timeout)
        self._ip, self._policy = ip, policy

    connect_ms: float | None = None
    tls_ms: float | None = None

    def connect(self) -> None:
        started = time.monotonic()
        self.sock = _open_pinned(self._ip, self.port, self.timeout, self._policy)
        self.connect_ms = (time.monotonic() - started) * 1000


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        host: str,
        port: int,
        ip: str,
        timeout: float,
        policy: IPPolicy,
        context: ssl.SSLContext | None = None,
    ) -> None:
        super().__init__(
            host, port, timeout=timeout, context=context or ssl.create_default_context()
        )
        self._ip, self._policy = ip, policy

    connect_ms: float | None = None
    tls_ms: float | None = None

    def connect(self) -> None:
        started = time.monotonic()
        sock = _open_pinned(self._ip, self.port, self.timeout, self._policy)
        self.connect_ms = (time.monotonic() - started) * 1000
        try:
            # SNI and certificate verification use the hostname, not the IP.
            handshake = time.monotonic()
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
            self.tls_ms = (time.monotonic() - handshake) * 1000
        except BaseException:
            sock.close()
            raise


def default_connection_factory(
    scheme: str,
    host: str,
    port: int,
    ip: str,
    timeout: float,
    policy: IPPolicy,
    ssl_context: ssl.SSLContext | None = None,
) -> http.client.HTTPConnection:
    if scheme == "https":
        return _PinnedHTTPSConnection(host, port, ip, timeout, policy, ssl_context)
    return _PinnedHTTPConnection(host, port, ip, timeout, policy)


def _require_verifying(context: ssl.SSLContext) -> None:
    """Refuse a context that would skip certificate or hostname verification."""
    if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
        raise ValueError("ssl_context must verify certificates and hostnames")


@dataclass(frozen=True)
class FetchResult:
    """A fetch record plus the stored body's bytes (``None`` if not stored)."""

    record: FetchRecord
    body: bytes | None


@dataclass
class _Timing:
    """Mutable timing scratchpad for one fetch; only the final hop's values survive."""

    scheme: str = "https"
    dns_ms: float | None = None
    connect_ms: float | None = None
    tls_ms: float | None = None
    ttfb_ms: float | None = None
    response_ms: float | None = None
    notes: dict[str, str] = field(default_factory=dict)

    def build(self, started: float) -> FetchTimings:
        values = {
            "dns_ms": self.dns_ms,
            "connect_ms": self.connect_ms,
            "tls_ms": self.tls_ms,
            "ttfb_ms": self.ttfb_ms,
            "response_ms": self.response_ms,
        }
        unmeasured = {}
        for name, value in values.items():
            if value is None:
                default = (
                    "plain HTTP: there is no TLS handshake"
                    if name == "tls_ms" and self.scheme == "http"
                    else "not reached before the fetch ended"
                )
                unmeasured[name] = self.notes.get(name, default)
        return FetchTimings(
            **{k: (None if v is None else round(v, 3)) for k, v in values.items()},
            total_ms=round((time.monotonic() - started) * 1000, 3),
            unmeasured=unmeasured,
        )


class _IncompleteResponse(Exception):
    """The server closed the connection before the declared body length."""


@dataclass(frozen=True)
class _Response:
    status: int
    headers: dict[str, str]  # recorded (allow-listed, truncated) headers
    locations: list[str]  # raw Location header values, untruncated
    body: bytes | None
    truncated: bool
    not_stored_reason: str | None


class _Refused(Exception):
    """Internal: a redirect hop that must not be followed."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _Watchdog:
    """Shuts the socket down at a deadline so a stalled fetch cannot hang."""

    def __init__(self, conn: http.client.HTTPConnection, seconds: float) -> None:
        self.fired = False
        self._conn = conn
        self._timer = threading.Timer(max(seconds, 0.001), self._fire)
        self._timer.daemon = True

    def _fire(self) -> None:
        self.fired = True
        sock = self._conn.sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def __enter__(self) -> "_Watchdog":
        self._timer.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._timer.cancel()


def _split_target(url: str, allowed_ports: frozenset[int]) -> tuple[str, str, int]:
    parts = urlsplit(url)
    if parts.scheme not in _DEFAULT_PORTS:
        raise PolicyViolation(
            "unsupported_scheme", f"unsupported scheme {parts.scheme!r}"
        )
    if parts.username is not None or parts.password is not None:
        raise PolicyViolation("credentials_in_url", "URLs with credentials are refused")
    host = parts.hostname
    if not host:
        raise PolicyViolation("invalid_location", "URL has no host")
    port = parts.port or _DEFAULT_PORTS[parts.scheme]
    if port not in allowed_ports:
        raise PolicyViolation("blocked_port", f"port {port} is not allowed")
    return parts.scheme, host, port


def _canonical(url: str) -> str | None:
    try:
        return str(_URL.validate_python(url))
    except ValidationError:
        return None


class SafeFetcher:
    """Fetches one URL (following validated redirects) into a ``FetchRecord``."""

    def __init__(
        self,
        config: CrawlConfig,
        store: BodyStore,
        audit_id: str,
        *,
        host_allowed: Callable[[str], bool] | None = None,
        resolver: Resolver = system_resolver,
        ip_policy: IPPolicy = is_public_address,
        connection_factory: ConnectionFactory = default_connection_factory,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        """``ssl_context`` is optional and must verify certificates and hostnames."""
        if ssl_context is not None:
            if connection_factory is not default_connection_factory:
                raise ValueError("ssl_context cannot be combined with a custom factory")
            _require_verifying(ssl_context)
            connection_factory = functools.partial(
                default_connection_factory, ssl_context=ssl_context
            )
        self.config = config
        self.store = store
        self.audit_id = audit_id
        self.host_allowed = host_allowed
        self.resolver = resolver
        self.ip_policy = ip_policy
        self.connection_factory = connection_factory

    # -- public ---------------------------------------------------------------

    def fetch(
        self,
        url: str,
        *,
        kind: FetchKind = "page",
        max_bytes: int | None = None,
        redirect_allowed: Callable[[str], bool] | None = None,
    ) -> FetchResult:
        """Fetch ``url``; every outcome, including failure, is a ``FetchRecord``.

        ``redirect_allowed`` is asked about each redirect destination before any
        connection to it (the crawler uses it for robots.txt). Raises
        ``ValueError`` only if ``url`` or ``max_bytes`` is invalid.
        """
        if max_bytes is not None and max_bytes < 1:
            raise ValueError("max_bytes must be at least 1")
        requested = _canonical(url)
        if requested is None:
            raise ValueError(f"not a valid http(s) URL: {url!r}")
        limit = self.config.max_response_bytes
        if max_bytes is not None:
            limit = min(max_bytes, limit)
        started = datetime.now(UTC)
        clock_start = time.monotonic()
        timing = _Timing()
        deadline = clock_start + self.config.max_fetch_seconds
        base: dict[str, object] = {
            "audit_id": self.audit_id,
            "fetch_id": f"fetch_{uuid.uuid4().hex}",
            "requested_url": requested,
            "started_at": started,
        }
        hops: list[RedirectHop] = []
        seen = {requested}
        current = requested
        try:
            scheme, host, port = _split_target(current, self.config.allowed_ports)
            # Scope is enforced on the host this fetch will actually connect to, for the
            # first hop as well as for redirects, so no caller-side parser can widen it.
            if self.host_allowed is not None and not self.host_allowed(host):
                raise PolicyViolation(
                    "blocked_url", f"{host} is outside the crawl scope"
                )
            ips = self._resolve(host, port, timing)
            while True:
                timing.scheme = scheme
                resp = self._request(
                    scheme, host, port, ips, current, kind, limit, deadline, timing
                )
                if not 300 <= resp.status < 400:
                    return self._finish(base, hops, current, resp, timing, clock_start)
                step = self._follow(current, resp, hops, seen, redirect_allowed, timing)
                if isinstance(step, _Refused):
                    return self._refused(
                        base, hops, current, step.reason, resp, timing, clock_start
                    )
                current, ips = step
                scheme, host, port = _split_target(current, self.config.allowed_ports)
        except _TooManyRedirects:
            return self._error(
                base,
                hops,
                "too_many_redirects",
                f"more than {self.config.max_redirects} redirects or a redirect loop",
                timing,
                clock_start,
            )
        except PolicyViolation as violation:
            error_type = _BLOCK_TYPES.get(violation.reason, "blocked_url")
            return self._error(
                base, hops, error_type, str(violation), timing, clock_start
            )
        except (_IncompleteResponse, http.client.IncompleteRead) as exc:
            return self._error(
                base,
                hops,
                "incomplete_response",
                f"{type(exc).__name__}: {exc}",
                timing,
                clock_start,
            )
        except TimeoutError:
            return self._error(
                base,
                hops,
                "timeout",
                "fetch exceeded its time limit",
                timing,
                clock_start,
            )
        except socket.gaierror as exc:
            return self._error(
                base, hops, "dns", f"DNS resolution failed: {exc}", timing, clock_start
            )
        except ssl.SSLError as exc:
            return self._error(
                base, hops, "tls", f"TLS error: {exc}", timing, clock_start
            )
        except (OSError, http.client.HTTPException) as exc:
            error_type = "connection" if isinstance(exc, OSError) else "other"
            return self._error(
                base,
                hops,
                error_type,
                f"{type(exc).__name__}: {exc}",
                timing,
                clock_start,
            )

    def _resolve(self, host: str, port: int, timing: _Timing) -> list[str]:
        """Resolve and vet ``host``, timing only the resolver call itself."""
        timing.dns_ms = None
        timing.notes.pop("dns_ms", None)
        calls: list[float] = []

        def timed(name: str, number: int) -> list[str]:
            started = time.monotonic()
            try:
                return self.resolver(name, number)
            finally:
                calls.append((time.monotonic() - started) * 1000)

        try:
            return resolve_allowed(host, port, timed, self.ip_policy)
        finally:
            if calls:
                timing.dns_ms = calls[-1]
            else:
                timing.notes["dns_ms"] = "host is an IP literal: no DNS lookup"

    # -- redirects ------------------------------------------------------------

    def _follow(
        self,
        current: str,
        resp: _Response,
        hops: list[RedirectHop],
        seen: set[str],
        redirect_allowed: Callable[[str], bool] | None,
        timing: _Timing,
    ) -> "tuple[str, list[str]] | _Refused":
        """Validate a redirect; return the next URL and its vetted addresses.

        Everything is checked before any connection to the target is made: scheme,
        credentials, port, https-to-http downgrade, scope, robots (via
        ``redirect_allowed``) and the resolved addresses. The returned addresses are
        the ones the next hop connects to. The raw ``Location`` value is used, not
        the truncated copy kept in the recorded headers.
        """
        if resp.status not in _REDIRECT_STATUSES:
            return _Refused("not_a_redirect")
        if not resp.locations:
            return _Refused("missing_location")
        location = resp.locations[0]
        if (
            len(set(resp.locations)) > 1
            or not location
            or len(location) > _MAX_LOCATION
        ):
            return _Refused("invalid_location")
        target = _canonical(urljoin(current, location))
        if target is None:
            return _Refused("invalid_location")
        try:
            scheme, host, port = _split_target(target, self.config.allowed_ports)
        except PolicyViolation as violation:
            return _Refused(violation.reason)
        if urlsplit(current).scheme == "https" and scheme == "http":
            return _Refused("https_downgrade")
        if self.host_allowed is not None and not self.host_allowed(host):
            return _Refused("cross_domain")
        if redirect_allowed is not None and not redirect_allowed(target):
            return _Refused("robots_disallowed")
        try:
            ips = self._resolve(host, port, timing)
        except PolicyViolation as violation:
            return _Refused(violation.reason)
        hops.append(
            RedirectHop(url=current, status_code=resp.status, location=location)
        )
        if len(hops) > self.config.max_redirects or target in seen:
            raise _TooManyRedirects
        seen.add(target)
        return target, ips

    # -- one HTTP exchange ----------------------------------------------------

    def _request(
        self,
        scheme: str,
        host: str,
        port: int,
        ips: list[str],
        url: str,
        kind: FetchKind,
        limit: int,
        deadline: float,
        timing: _Timing,
    ) -> _Response:
        timeout = self.config.request_timeout_seconds
        timing.connect_ms = timing.tls_ms = timing.ttfb_ms = timing.response_ms = None
        timing.notes = {k: v for k, v in timing.notes.items() if k == "dns_ms"}
        conn: http.client.HTTPConnection | None = None
        last_error: OSError | None = None
        for ip in ips[:_MAX_IPS_TRIED]:
            candidate = self.connection_factory(
                scheme, host, port, ip, timeout, self.ip_policy
            )
            try:
                candidate.connect()
            except OSError as exc:
                candidate.close()
                last_error = exc
                continue
            conn = candidate
            timing.connect_ms = getattr(conn, "connect_ms", None)
            timing.tls_ms = getattr(conn, "tls_ms", None)
            for name, value in (
                ("connect_ms", timing.connect_ms),
                ("tls_ms", timing.tls_ms if scheme == "https" else 0.0),
            ):
                if value is None:
                    timing.notes[name] = "not exposed by this connection factory"
            break
        if conn is None:
            raise last_error or ConnectionError("no address could be reached")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            conn.close()
            raise TimeoutError
        try:
            with _Watchdog(conn, remaining) as watchdog:
                parts = urlsplit(url)
                target = (parts.path or "/") + (
                    f"?{parts.query}" if parts.query else ""
                )
                sent = time.monotonic()
                conn.request(
                    "GET",
                    target,
                    headers={
                        "User-Agent": self.config.user_agent,
                        "Accept": _ACCEPT[kind],
                        "Accept-Encoding": "identity",
                        "Connection": "close",
                    },
                )
                response = conn.getresponse()
                timing.ttfb_ms = (time.monotonic() - sent) * 1000
                status = response.status
                raw_headers = response.getheaders()
                headers = _record_headers(raw_headers)
                locations = [
                    v.strip() for k, v in raw_headers if k.lower() == "location"
                ]
                body, truncated, reason = None, False, None
                if 300 <= status < 400:
                    reason = None
                elif not 200 <= status < 300:
                    reason = "non_success_status"
                else:
                    reason = _body_refusal(headers, kind)
                    if reason is None:
                        body, truncated = self._read(response, limit, deadline)
                if watchdog.fired or time.monotonic() > deadline:
                    raise TimeoutError
                timing.response_ms = (time.monotonic() - sent) * 1000
                return _Response(status, headers, locations, body, truncated, reason)
        finally:
            conn.close()

    @staticmethod
    def _read(
        response: http.client.HTTPResponse, limit: int, deadline: float
    ) -> tuple[bytes, bool]:
        """Stream up to ``limit`` bytes; read one extra byte to detect truncation.

        Cutting the stream at ``limit`` is a deliberate truncation. A server that
        closes before its declared ``Content-Length`` is an incomplete response.
        """
        declared = _declared_length(response)
        buf = bytearray()
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError
            chunk = response.read1(min(_CHUNK, limit + 1 - len(buf)))
            if not chunk:
                if declared is not None and len(buf) < declared:
                    raise _IncompleteResponse(
                        f"received {len(buf)} of {declared} declared bytes"
                    )
                return bytes(buf), False
            buf += chunk
            if len(buf) > limit:
                return bytes(buf[:limit]), True

    # -- record construction --------------------------------------------------

    def _finish(
        self,
        base: dict[str, object],
        hops: list[RedirectHop],
        url: str,
        resp: _Response,
        timing: _Timing,
        clock_start: float,
    ) -> FetchResult:
        status, data, truncated = resp.status, resp.body, resp.truncated
        reason = resp.not_stored_reason
        fields: dict[str, object] = {
            **base,
            "redirects": hops,
            "status_code": status,
            "final_url": url,
            "headers": resp.headers,
            "completed_at": datetime.now(UTC),
            "outcome": "success" if 200 <= status < 300 else "http_error",
            "timings": timing.build(clock_start),
        }
        stored = None
        if data is not None and len(data) == 0 and not truncated:
            reason = "empty_response"
        elif data is not None:
            try:
                stored = self.store.put(data, truncated=truncated)
            except OSError as exc:
                # Not a transport error (and not an OSError the caller of fetch()
                # would mistake for one): a failing disk must stop the crawl.
                raise StorageError(f"could not store body: {exc}") from exc
        fields["body"] = stored
        fields["body_not_stored_reason"] = reason
        return FetchResult(FetchRecord.model_validate(fields), data if stored else None)

    def _refused(
        self,
        base: dict[str, object],
        hops: list[RedirectHop],
        url: str,
        reason: str,
        resp: _Response,
        timing: _Timing,
        clock_start: float,
    ) -> FetchResult:
        """Record the 3xx response from ``url`` that was deliberately not followed."""
        record = FetchRecord.model_validate(
            {
                **base,
                "redirects": hops,
                "outcome": "redirect_not_followed",
                "status_code": resp.status,
                "final_url": url,
                "headers": resp.headers,
                "redirect_refusal_reason": reason,
                "completed_at": datetime.now(UTC),
                "timings": timing.build(clock_start),
            }
        )
        return FetchResult(record, None)

    def _error(
        self,
        base: dict[str, object],
        hops: list[RedirectHop],
        error_type: TransportErrorType,
        message: str,
        timing: _Timing,
        clock_start: float,
    ) -> FetchResult:
        record = FetchRecord.model_validate(
            {
                **base,
                "redirects": hops,
                "outcome": "transport_error",
                "error_type": error_type,
                "error_message": message[:300],
                "completed_at": datetime.now(UTC),
                "timings": timing.build(clock_start),
            }
        )
        return FetchResult(record, None)


class _TooManyRedirects(Exception):
    pass


_BLOCK_TYPES: dict[str, TransportErrorType] = {
    "blocked_address": "blocked_address",
    "blocked_port": "blocked_port",
}


def _record_headers(raw: list[tuple[str, str]]) -> dict[str, str]:
    merged: dict[str, list[str]] = {}
    for name, value in raw:
        key = name.lower()
        if key in _RECORDED_HEADERS:
            merged.setdefault(key, []).append(value.strip())
    return {k: ", ".join(v)[:_MAX_HEADER_VALUE] for k, v in merged.items()}


def _declared_length(response: http.client.HTTPResponse) -> int | None:
    """The declared ``Content-Length``, or ``None`` if absent, invalid or moot."""
    if response.chunked or response.status == 204:
        return None
    try:
        value = int(response.getheader("content-length", ""))
    except ValueError:
        return None
    return value if value >= 0 else None


def _body_refusal(headers: dict[str, str], kind: FetchKind) -> str | None:
    encoding = headers.get("content-encoding", "identity").strip().lower()
    if encoding not in ("", "identity"):
        return "unsupported_content_encoding"
    media_type = headers.get("content-type", "").split(";")[0].strip().lower()
    if media_type not in _CONTENT_TYPES[kind]:
        return "unsupported_content_type"
    return None
