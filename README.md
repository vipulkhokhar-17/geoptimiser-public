# Geoptimiser

An evidence-grounded **Generative Engine Optimization (GEO) audit and experimentation platform**. Geoptimiser crawls an authorized website, extracts page structure, measures a catalog of GEO-related signals, retrieves supporting passages, and produces evidence-linked findings and recommendations.

> **Current status:** private, single-user, local demo. The backend runs on the operator's machine at `127.0.0.1:8000`. It is not a hosted service. The API has no authentication or multi-user isolation; do not expose it to a network or through a tunnel.

## What it does

The audit pipeline is:

`validate → crawl → extract → feature checks → chunk → retrieve → diagnose → recommend → optional agent → validate → report`

- **Crawler:** bounded, robots-aware crawling with DNS/IP checks, pinned connections, redirect validation, TLS verification, and response/time/byte limits.
- **Extraction and feature engine:** normalizes HTML and evaluates a 120-feature catalog. Results distinguish pass, fail, not applicable, not measured, and error.
- **Retrieval and evidence:** chunks extracted content, retrieves passages, and requires findings and recommendations to reference evidence.
- **Optional agent:** a bounded LangGraph workflow that can inspect findings and invoke a small allowlist of existing pipeline tools. It does not have shell, Python, arbitrary network, or arbitrary file tools.
- **Local application:** FastAPI, SQLite persistence, a browser UI, HTML/JSON reports, and before/after comparisons.

The agent and semantic retrieval are optional. Deterministic checks and the report pipeline do not require a hosted LLM.

## Measurement and validation limits

The catalog contains 120 features. The generated register currently reports:

| Implementation status | Count |
|---|---:|
| Implemented | 41 |
| Partial | 41 |
| Planned | 36 |
| Unavailable | 2 |
| **Total** | **120** |

Validation is separate from implementation:

| Validation level | Count |
|---|---:|
| Pipeline-validated against synthetic fixtures (V2) | 35 |
| Unit-tested only (V1) | 47 |
| Not tested (V0) | 38 |
| Labelled real-page validation | 0 |
| AI-search outcome validation | 0 |

The fixture results test whether the implementation follows its declared measurement policy on constructed cases. They do **not** establish accuracy across real websites or demonstrate that changing a measured feature improves inclusion, ranking, or citations in AI answers. The project has no validated causal or outcome claim.

The counts above are generated in `src/geoptimiser/validation/feature_levels.json` and checked by the validation tooling. See [the feature audit](docs/validation/GEOPTIMISER_FEATURE_AUDIT.md) and [the validation policy](docs/validation/VALIDATION_POLICY.md) for methodology and limitations.

## Run locally

Requirements: Python 3.11+ and Git.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
python -m pytest
ruff check .
ruff format --check .
```

To run the local application:

```bash
python -m pip install -e '.[api]'
python -m geoptimiser.app serve
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The server is hard-bound to `127.0.0.1`: the CLI has no host override or remote-bind option. Changing `--port` changes only the port, not the interface. Configured CORS origins are restricted to localhost/loopback. **Do not tunnel or proxy the backend.** The API has no authentication and anyone who can reach it can read all stored audits.

Run a one-off audit from the terminal:

```bash
python -m geoptimiser.app audit https://example.com --confirm-authorized
```

Only audit websites that you own or are authorized to test. The confirmation flag records an attestation; it does not verify ownership.

For the optional agent:

```bash
python -m pip install -e '.[agent]'
export OPENROUTER_API_KEY='your-key'
```

Keep real credentials in an untracked environment file or shell environment. Never commit keys, cookies, local databases, crawl output, or customer content. See [.env.example](.env.example).

## Data sent to the optional agent

When an audit is configured to use the agent, Geoptimiser sends model requests to the configured OpenRouter API over HTTPS. Requests include the audit task, finding metadata, and bounded observations from the agent's allowlisted tools. Depending on which tools run, observations can contain audited-site URLs and excerpts of website content/evidence. The default observation limit is 3,000 characters per observation; prompts retain only a bounded history window.

The crawler and deterministic pipeline run locally, but **agent-enabled audits are not fully local**. Do not send confidential, personal, customer, or otherwise restricted site content to the external model unless you have authority to do so and have reviewed the provider's current privacy, retention, and data-use terms. The OpenRouter API key is read from `OPENROUTER_API_KEY`.

## Offline demo

The bundled demo runs the pipeline against a mock site and does not require an API key or a live model:

```bash
python -m pip install -e '.[agent]'
python -m geoptimiser.demo --out demo_output
```

See [docs/DEMO.md](docs/DEMO.md).

## Development checks

```bash
python -m pytest
ruff check .
ruff format --check .
python -m geoptimiser.validation.matrix --check
python -m geoptimiser.validation --fixtures tests/validation/fixtures
```

The optional semantic retrieval extra uses a pinned Sentence Transformers model revision in `configs/retrieval.json`. It downloads model weights from Hugging Face on first use and runs inference locally.

## Architecture and project documentation

| Document | Contents |
|---|---|
| [Architecture](docs/project/ARCHITECTURE.md) | Components, data flow, APIs, trust boundaries, technology |
| [Roadmap](docs/ROADMAP.md) | Current implementation status and remaining gaps |
| [Execution flow](docs/project/EXECUTION_FLOW.md) | URL submission through report generation |
| [Development guide](docs/project/DEVELOPMENT_GUIDE.md) | Setup, commands, quality gates, extension points |
| [Feature catalog](docs/FEATURE_CATALOG.md) | All 120 measurements and their current implementation status |
| [Feature validation guide](docs/project/FEATURE_VALIDATION_GUIDE.md) | Validation levels, dispositions, fixtures |
| [Evaluation](docs/EVALUATION.md) | Retrieval and measurement evaluation |
| [Application](docs/APP.md) | Local API, persistence, UI, and operational constraints |
| [Agent](docs/AGENT.md) | Agent graph, tools, budgets, and untrusted-content handling |
| [Security model](docs/SECURITY.md) | Current controls, local binding, risks, operator checks |
| [Public-release checklist](docs/PUBLIC_RELEASE_CHECKLIST.md) | Repository and service release gates |
| [Deployment requirements](docs/DEPLOYMENT_REQUIREMENTS.md) | Work required before exposing a backend publicly |
| [Frontend hosting](docs/DEPLOY_FRONTEND.md) | Safe local UI testing and the disabled, opt-in Pages workflow |
| [Decision records](docs/DECISIONS.md) | Architectural decisions and trade-offs |

## Release status

This repository is a clean-history source snapshot of Geoptimiser, prepared from release-prep commit 413af9d3d40d. The development repository and its prior branches, pull requests, and commit history are not included. The backend remains local-only and is not production-ready. **No licence is granted; all rights are reserved.** Public availability permits viewing this source on GitHub only; it does not grant permission to copy, modify, redistribute, or use the code. See [SECURITY.md](SECURITY.md) and the [public-release checklist](docs/PUBLIC_RELEASE_CHECKLIST.md).
