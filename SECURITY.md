# Security Policy

## Reporting a Vulnerability

If you find a security issue in Shorelife — anything affecting the
confidentiality, integrity, or availability of the public API or the data
pipeline — please **email kylechoidsc@gmail.com** with details. Do not
open a public GitHub issue or discussion for security topics.

Reports should include:

- A description of the issue and its impact
- Reproduction steps (PoC code, request payloads, etc.)
- The Shorelife commit SHA, API URL, or app version where you observed it
- Whether the issue is exploitable in production right now

You can expect:

- **Acknowledgement within 48 hours** of receipt
- A first-pass triage and severity assessment within 7 days
- Coordinated disclosure once a fix is deployed

## Scope

In scope for this repository:

- The public FastAPI service (`backend/`) and its serving snapshot
- The data ingestion + ML training pipelines under `backend/app/`
- The GitHub Actions workflows under `.github/workflows/`
- The methodology and model card under `data/curated/` and `docs/`

Out of scope for this repository (separate private repos / report directly):

- The consumer-facing **web app** (Next.js → GitHub Pages)
- The consumer-facing **mobile app** (iOS / Android)
- Third-party data sources (data.ca.gov, CDIP, Open-Meteo, etc.) — report
  upstream to the responsible operator

## Supported Versions

Only the latest `main` is supported. The single deployed Render service
tracks `main`; older tags are research artifacts and won't receive fixes.

## Safe Harbor

Good-faith security research against the public Shorelife API and public
repositories is welcomed. Please:

- Avoid degrading service for real users (no DoS / load testing)
- Avoid accessing or modifying data that isn't yours
- Avoid social engineering of contributors

If you follow these and report responsibly via email, we won't pursue
legal action.
