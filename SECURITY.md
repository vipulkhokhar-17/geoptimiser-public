# Security policy

## Project status

Geoptimiser is currently a private, single-user, local-only demo. It is not a hosted service. The local API has no authentication, authorization, or multi-user isolation and must not be exposed beyond loopback.

The repository's current controls and limitations are documented in [docs/SECURITY.md](docs/SECURITY.md). Public source-code availability does not mean that the backend is safe to deploy publicly.

## Reporting a vulnerability

Please do not publish credentials, exploit details, private URLs, personal data, or other sensitive proof-of-concept material in a public issue.

If GitHub's private vulnerability reporting feature is enabled for this repository, use it. Otherwise, contact the repository maintainer privately through their GitHub profile before disclosing details publicly.

For an actionable report, include the affected commit or version, the affected component, prerequisites, reproduction steps, observed impact, and any safe mitigation you have identified. Redact secrets and customer data from evidence.

## Scope

The intended current deployment is a local development/demo process bound to loopback. The unauthenticated API is not considered safe for remote use. Reports involving a deliberately exposed instance should state how it was exposed and which network controls were in place.
