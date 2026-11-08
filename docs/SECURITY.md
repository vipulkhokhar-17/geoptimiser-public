# Security model and operator guidance

Geoptimiser is currently a **single-user, local-only demo**. The backend is run on the operator's Mac and is not a hosted service. It has no authentication, no authorization, and no per-user data isolation.

This document describes the current code-level controls. It is not a penetration-test report, independent certification, or guarantee that all vulnerabilities have been found.

## 1. Local server binding: IP address vs port

The local API starts with:

```bash
python -m geoptimiser.app serve
```

The CLI is hard-bound to `127.0.0.1:8000`. It has no `--host`, `--allow-remote`, or
`--allowed-host` option. The `--port` option changes only the TCP port, not the interface.

- `127.0.0.1` is the loopback address. Connections to it stay on the same computer.
- `8000` is the TCP port. It identifies the application on that computer.
- `0.0.0.0` means listen on all IPv4 network interfaces. Other devices on a reachable network may then connect using the Mac's Wi-Fi/Ethernet address, subject to firewall rules.
- `--port 9000` changes the port; it does not change who can reach the service.
- The supported CLI has no option to bind a different interface; `--port` only changes the port.

For this local-only project, start the server with the command above. The application has
no supported way to bind to another interface. Do not expose the port through router
port-forwarding, ngrok, Cloudflare Tunnel, a reverse proxy, or another device. When the
local UI is served on a separate port, configured CORS origins must also be loopback URLs; a
public website origin is rejected by application configuration.

To see what is listening on port 8000 on macOS:

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
```

Expected listener: `127.0.0.1:8000`. Treat `*:8000`, `0.0.0.0:8000`, `[::]:8000`, or a
LAN address as a warning that another process or configuration is exposing a service
beyond the Mac. Stop it with Ctrl+C and restart Geoptimiser with the command above.

A local-only listener is not an authentication boundary against malware or another untrusted process already running on the same Mac. The API should still be treated as sensitive because it can read stored audit data and create new audits.

## 2. Current security controls

| Area | Existing protection |
|---|---|
| SSRF and DNS rebinding | The crawler resolves each host, rejects non-public addresses, connects to the validated IP, verifies the connected peer, and re-validates each redirect hop. |
| Transport security | TLS certificate and hostname verification are required. Redirects are handled manually; only permitted schemes and ports are accepted. |
| Crawl exhaustion | Streaming response caps, per-audit byte limits, page/depth limits, request spacing, and fetch watchdogs bound network work. |
| API input | Strict request models, a small JSON body limit, server-side option caps, and an explicit authorization attestation. |
| Host and browser requests | Host allow-list, no CORS by default, security response headers, and JSON-only POST requests. |
| Filesystem | Artifact access is by audit identifier and database metadata, with path-containment checks. Local body files use restrictive permissions and content hashes. |
| Database | Parameterized SQL, SQLite foreign keys/WAL, and short transactions. |
| UI and reports | Fixed static files, escaped HTML, text-node insertion in the UI, and restrictive Content Security Policies. |
| Agent | Bounded iterations, validated arguments, a tool allowlist, timeouts, and deterministic final validation. Website text and model output are untrusted; the agent has no shell or arbitrary file/network tool. |
| Secrets | The OpenRouter key is read from the environment when the agent is requested and is not intended to be logged or stored in reports. Local `.env` files are ignored by Git. |

The regression tests and earlier review are documented in [the security review record](project/SECURITY_REVIEW.md).

## 3. Data sent to the external model provider

The crawler, extraction, feature checks, retrieval index and ordinary report generation run locally. When an audit is configured to use the optional agent, the agent calls the configured OpenRouter API over HTTPS.

The model receives the task prompt, audit identifier, finding summaries/metadata, and bounded tool observations. Depending on the tools used, these observations can include target-site URLs, short evidence excerpts, and retrieved passages from the audited pages. The default agent configuration caps each observation at 3,000 characters and retains a bounded history window; this is truncation, not anonymization.

Treat agent-enabled audits as an external data transfer. Do not send confidential, personal, customer, or otherwise restricted content to the model provider unless you have appropriate authority and have reviewed the provider's current privacy, retention, and data-use terms. The API key is read from `OPENROUTER_API_KEY` and is not stored in audit artifacts.

## 4. Important current limitations

1. **No API authentication or authorization.** Anyone who can reach the local API can read all saved audits, reports and comparisons, and can submit new audits. This is why the app must remain on loopback.
2. **No multi-user isolation.** The data model is for one local operator, not multiple customers.
3. **No verified domain ownership.** The submission checkbox is an attestation only.
4. **No aggregate data-directory quota or automatic retention.** Individual crawls are bounded, but accumulated audit data may grow. Body deletion needs reference tracking because content-addressed bodies can be shared by several audits.
5. **No full stage deadline for feature checks and retrieval.** Individual code paths have limits, but the earlier review identified broader stage-level budgets as remaining work.
6. **Public-suffix handling is incomplete.** The application rejects many malformed and local targets; public-suffix validation remains a future hardening item.
7. **External model and dependency trust.** Semantic retrieval downloads model files from Hugging Face when first used. The configured default model revision is now pinned and the loader refuses non-safetensors weights, but the optional semantic stack still needs independent dependency and runtime verification.
8. **Real-network checks were not performed by the earlier sandbox audit.** DNS and TLS behavior on live sites must be re-verified in the operator's environment.
9. **Historical secret scan passed on the current prep head.** Gitleaks scanned 56 commits reachable from the fetched branch and tag refs and returned no findings after one fingerprint-specific exception for a known fake test credential in an old test file. Re-run after further history changes; this does not replace review of branches, tags, metadata, or your local working tree.

## 5. Checks before making the repository public

The dedicated GitHub Actions workflow, `.github/workflows/secrets.yml`, downloads a
pinned Gitleaks release, verifies its SHA-256 digest, fetches complete Git history, and
scans all commits reachable from fetched refs. The current prep head has a successful scan
(56 commits). `.gitleaksignore` contains one exact fingerprint exception for a deliberately
fake OpenRouter test fixture in an old commit; the fixture value has been replaced in the
current tree with an unmistakable non-token placeholder. This is not a general rule ignore.
You can repeat the scan locally from a full clone after fetching branches and tags:

```bash
brew install gitleaks
gitleaks git -v --log-opts="--all" --redact
```

If a credential is found, revoke or rotate it first; deleting the file in a new commit does
not make a historical credential safe. A clean scan is evidence only for the rules and refs
actually scanned, not proof that no secret exists.

Also inspect:
- all Git branches and tags, not only the default branch;
- commit author metadata (email addresses become visible when history is public);
- generated data, database files, crawl output, logs, screenshots, and uploaded content;
- repository settings for branch protection, Dependabot alerts, secret scanning, and Pages.

## 6. Requirements before any public backend exposure

The backend must not be exposed as-is. Before public access, implement and test:

- authentication and authorization on every route;
- ownership checks for every audit, report, feature record, comparison and artifact;
- per-user storage isolation or a correctly enforced tenant model;
- TLS termination and a trusted reverse proxy with hardened forwarded-header handling;
- per-user rate limits, quotas, queue limits, abuse controls and cost limits;
- verified domain ownership or an equivalent consent workflow;
- network-level egress controls for crawler workers;
- managed secret injection and rotation;
- data retention, deletion, backup and restore processes;
- durable job processing, concurrency controls and monitoring;
- security testing against a deployed staging environment.

See [deployment requirements](DEPLOYMENT_REQUIREMENTS.md). Public source-code release and public backend deployment are two separate decisions: the repository can be public while the backend remains private and local-only.
