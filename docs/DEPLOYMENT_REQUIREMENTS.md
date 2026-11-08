# Requirements for an eventual deployment

The hosting decision is **open**. This document lists what any deployment target would need,
without choosing a provider. The application today is a local, single-user tool.

## Must be added before any non-local exposure

1. **Authentication and authorization** (the API has none) and a decision on tenancy:
   per-user audit ownership, per-user data directories or rows, and access checks on every
   read, comparison and report.
2. **TLS termination** and a trusted reverse proxy; correct `Host`/forwarded-header
   handling (the `Host` allow-list and `--allow-remote` are local-development guards).
3. **Rate limiting and quotas** per user (audits per day, pages per audit, queue depth), and
   abuse handling for the crawler (it will fetch whatever domain a user submits).
4. **Verified domain ownership or an equivalent consent mechanism** instead of the current
   authorization checkbox.
5. **Egress controls** at the network layer in addition to the crawler's address checks:
   deny access to cloud metadata endpoints and internal networks from the worker's
   environment.
6. **Secrets management** for `OPENROUTER_API_KEY` (injected environment variable or a
   secret store; never in the image or repo) and a decision whether the LLM agent is offered
   at all.

## Operational requirements

* **Persistent storage** for the SQLite file and the artifact tree (or a migration to a
  server database and object storage); backups; retention and deletion policy for crawled
  page content (copyright and privacy).
* **A job mechanism** that survives restarts: today audits are not resumed and a second
  process invalidates the first's running audits. A multi-worker or multi-instance setup
  needs a real queue and per-audit leases.
* **Observability:** ship the JSON logs somewhere central, add metrics (queue depth, stage
  durations, failure categories), alerting and a health/readiness check wired to the
  platform (`/api/v1/health`, `/api/v1/ready` exist).
* **Resource sizing:** CPU and memory for PyTorch if semantic retrieval is enabled
  (`~90 MB` of weights, downloaded on first use), disk for crawled bodies, and request
  timeouts that exceed a full audit.
* **Supply chain:** pinned and scanned dependencies, a reproducible image, CI that runs the
  `agent`/`api` extras (a job exists) and, ideally, a scheduled run of the optional live and
  semantic checks.
* **Configuration:** the server settings in `AppConfig` and `configs/*.json` need an
  environment-driven loader and per-environment values.

## Product work still open

A reviewed benchmark and real-site retrieval evaluation, a real AI-search visibility
provider (Stages 05–06 have only mocks), a user-facing explanation of scores and coverage,
accessibility review of the UI, and the deferred LoRA/fine-tuning experiment.

## Provider-neutral shortlist criteria

When choosing a host: supports a long-running Python process or container with persistent
disk, outbound egress filtering, secret injection, TLS, and enough memory for the optional
embedding model. No assumption is made about any specific provider.
