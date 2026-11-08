# Public-release checklist

This checklist separates **publishing the source repository** from **deploying the backend as a public service**. Completing one does not imply the other is safe.

## A. Repository publication gates

- [x] Prepared this release snapshot from the reviewed source tree; the one-time publisher creates a fresh root commit and imports no branches, tags, pull requests, or prior Git metadata.
- [ ] Verify the created GitHub repository is Private and contains only the approved snapshot. Keep it private until explicit publication approval.
- [x] Full-history Gitleaks workflow passed on the originating release-prep branch (56 commits; one fingerprint-specific exception for a known fake test fixture). The clean release repository will run its own secret scan after the initial push.
- [x] Reviewed the fingerprint-specific `.gitleaksignore` entry: it suppresses only the known fake OpenRouter test fixture in the referenced historical commit; the current fixture uses a non-token placeholder.
- [ ] Optionally repeat locally from a full clone: `gitleaks git -v --log-opts="--all" --redact`.
- [ ] Re-run Gitleaks after any further history or release-prep changes. A clean scan is only evidence for the refs and rules scanned; it is not a proof that no secret exists.
- [x] The new release repository will contain only this selected source snapshot; no prior development branches, tags, or pull-request refs will be imported. The tracked tree was inspected for databases, environment secrets, private keys, logs, and crawl-output directories.
- [x] Reviewed the README and security documentation for external data transfers. Agent-enabled audits disclose bounded audit metadata and website evidence excerpts sent to OpenRouter; the operator must still decide which data types are appropriate to send.
- [x] Old commit author/committer metadata, commit messages, and collaboration/session URLs will not be included because no old Git commits are imported.
- [x] The original development repository retains its full history and remains private. The release candidate uses one fresh root commit only.
- [x] No licence is intentionally provided. README states that no licence is granted and all rights are reserved; do not add a `LICENSE` file.
- [ ] Enable branch protection for `main`: require pull requests, require passing CI, block force pushes and deletions.
- [ ] Enable Dependabot alerts and security updates where available. Review repository secret-scanning settings.
- [x] Confirmed CI, agent/API tests, dependency audit, and the full-history Gitleaks workflow passed on the current release-prep head.
- [x] Checked README implementation and validation counts against `src/geoptimiser/validation/feature_levels.json`; the counts match.

## B. Local demo safety

- [x] Backend is hard-bound to `127.0.0.1`; the CLI has no host or remote-bind override.
- [x] Configured CORS origins are restricted to loopback addresses.
- [ ] Confirm the running process on the operator's Mac is actually bound to loopback using `lsof -nP -iTCP:8000 -sTCP:LISTEN`.
- [ ] Do not use port forwarding, ngrok, Cloudflare Tunnel, or a reverse proxy while the API has no authentication.
- [x] Keep API keys outside Git; Gitleaks full-history workflow passed on the current release-prep head. The operator should still verify their local working copy and environment.

- [ ] Keep GitHub Pages disabled; do not tunnel the local Mac backend. See [frontend hosting guidance](DEPLOY_FRONTEND.md).

## C. Before public backend deployment

- [ ] Authentication and authorization on all API routes.
- [ ] Per-user audit/report ownership and tenant isolation.
- [ ] TLS, reverse-proxy configuration, and trusted forwarded-header rules.
- [ ] Per-user rate limits, quotas, queue limits and abuse protection.
- [ ] Verified domain ownership or equivalent audit consent.
- [ ] Network-level crawler egress restrictions.
- [ ] Managed secrets, rotation, logs/metrics, backups, retention and deletion.
- [ ] Durable job queue and safe multi-worker concurrency.
- [ ] Deployed staging tests, threat review, and an independent security assessment.
- [ ] Only then consider enabling the GitHub Pages workflow with:
  - repository variable `GEOPTIMISER_PAGES_ENABLED=true`;
  - repository variable `GEOPTIMISER_API_BASE=https://<secured-api-host>`.

The Pages workflow publishes only static frontend assets. It does not deploy the Python backend.
