# Static frontend hosting: backend deployment is blocked

**Current status: not deployed.** The backend runs on the operator's Mac as a local-only demo. The GitHub Pages workflow is disabled unless explicitly enabled with repository variables. This document is not an instruction to expose the Mac backend.

## Two separate systems

| Component | Current state | What it requires |
|---|---|---|
| Static frontend | Exportable static files; not currently published | GitHub Pages configuration and explicit opt-in |
| Python API, crawler, retrieval, agent, SQLite and audit artifacts | Runs locally on the operator's Mac | A separately operated backend host |
| Public API hostname | Not configured | A hosted, authenticated backend behind TLS |

GitHub Pages can publish only the static frontend. It does **not** deploy the Python backend, database, audit artifacts, model weights or job runner. A published frontend will not be functional until it points to a separately hosted API.

## Why the Mac backend must not be tunnelled

The local API has no authentication, authorization or per-user isolation. Anyone who can reach the API can submit audits and access all audits stored by the process. A tunnel, reverse proxy or port-forward would make that API reachable beyond the Mac.

**Do not run ngrok, Cloudflare Tunnel, router port-forwarding or another public tunnel to the current Mac backend.** The CLI has no remote-bind option. A Cloudflare Access policy can be an additional perimeter control, but it does not replace application-level authentication and authorization on every API route. CORS is also not authentication: non-browser clients can call an exposed API without obeying browser CORS rules.

The CLI's safe default is:

```bash
python -m geoptimiser.app serve
```

It listens on `127.0.0.1:8000`. Keep that default.

## Test the exported frontend locally

This workflow keeps both the static server and API bound to loopback on the same Mac:

```bash
# Export static UI pointed at the local API.
python -m geoptimiser.app.static_export \
  --out site --api-base http://127.0.0.1:8000 --domain ""

# In terminal 1, serve only on loopback.
python -m http.server 8080 --directory site --bind 127.0.0.1

# In terminal 2, start the API and allow this local page's exact origin.
# The API accepts loopback CORS origins only.
python -m geoptimiser.app serve \
  --cors-origin http://127.0.0.1:8080
```

Open `http://127.0.0.1:8080`. Both processes remain on the same computer. Do not replace either bind address with `0.0.0.0`.

## GitHub Pages workflow: deliberately opt-in

The workflow `.github/workflows/pages.yml` publishes static assets only. It is restricted to the `main` branch and requires both repository variables:

- `GEOPTIMISER_PAGES_ENABLED=true`
- `GEOPTIMISER_API_BASE=https://<secured-api-host>`

The API variable must be an HTTPS URL. With the enable variable unset, the workflow does not build or deploy Pages. Do not enable it until a secured, separately hosted API exists and has been tested.

Before a first publication:
1. Configure GitHub Pages to use GitHub Actions.
2. Configure and verify the custom domain in GitHub repository settings.
3. Confirm the static site contains no secrets or private data.
4. Set the two repository variables only after the backend release gates below have been completed.
5. Run the workflow from `main` and verify the deployed frontend.

Consult GitHub's current [custom domain documentation](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site) before changing DNS. Do not point a public API hostname at the Mac.

## Requirements before a hosted backend can be connected

The current backend is not ready for public network access. Before connecting a public frontend to it, implement and test:

- authentication and authorization on every API route;
- per-user audit/report ownership checks and tenant isolation;
- TLS termination and trusted reverse-proxy header handling;
- per-user rate limits, queue limits, quotas and abuse controls;
- verified domain ownership or equivalent audit-consent process;
- crawler egress controls and SSRF regression testing;
- managed secret storage and rotation;
- data retention, deletion, backup and restore;
- safe job processing and concurrency;
- monitoring, incident response and deployed-staging security tests.

See [security model](SECURITY.md), [public-release checklist](PUBLIC_RELEASE_CHECKLIST.md), and [deployment requirements](DEPLOYMENT_REQUIREMENTS.md).

**Source-code publication does not require backend deployment.** The repository can eventually be made public while the backend remains private and local-only.
