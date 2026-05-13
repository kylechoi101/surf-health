# Shorelife (formerly Surf Health)

California marine beach health forecast platform focused on daily enterococcus risk for surfers and beachgoers.

This **public repository** holds the open-source ML pipeline + research methodology.
The consumer-facing web and mobile apps live in private repositories:

| Surface | Source | Status |
|---|---|---|
| Backend API + ML pipeline | This repo (Apache-2.0) | Public, reviewable |
| Web app (Next.js → GitHub Pages) | `kylechoi101/shorelife-web` | Private |
| Mobile app (Expo → iOS + Android) | `kylechoi101/shorelife-mobile` | Private |

Open-core rationale: the science is reviewable so users, journalists, and partners can trust the forecast. The brand, UX, and operational artifacts that constitute the competitive surface live behind the private repos. See [docs/REPO_RESTRUCTURE.md](docs/REPO_RESTRUCTURE.md).

## Project Structure (public repo)

- `backend/`: Python FastAPI service, ingestion pipelines (BeachWatch, CEDEN, Stormwater), feature engineering, model training, and tests.
- `scripts/`: Reproducible research scripts (per-station residual benchmarks, Wikimedia photo curation, hourly weather refresh, etc.).
- `data/curated/`: Schemas and small samples. The production `serving.sqlite` artifact is served from Render at runtime.
- `docs/`: Methodology, model card, outreach kit.

## Local Development

The backend requires Python 3.12.

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,training]"
```

To run the API locally:
```bash
uvicorn app.main:app --reload
```

To run a daily training pass:
```bash
python -m app.ml.training --curated --winner-only \
  --spatial-backtests --spatial-strategy shortlist \
  --training-window-days 365 --forecast-min-recency-days 45 \
  --forecast-date "$(TZ=America/Los_Angeles date +%Y-%m-%d)"
```

## Automated pipeline

`.github/workflows/daily-forecast.yml` runs daily at 6 AM PT and:

1. Pulls California BeachWatch + CEDEN safe-to-swim data
2. Pulls external covariates (CDIP, CeNCOOS, EPA UV, hydrology, stormwater)
3. Trains the production ML model with spatial holdout backtests
4. Refreshes forecast-time weather (Open-Meteo) to give every beach 100% wind/UV coverage
5. Audits forecasts vs official advisories
6. Bakes the API serving snapshot (`serving.sqlite`)
7. Verifies public-release gates (calibration slope, AUCPR vs persistence)
8. Commits and pushes the refreshed `data/curated/`, triggering an automatic Render redeploy

## Methodology

The full methodology, calibration metrics, known failure modes, and citations are in [`data/curated/model_card.md`](data/curated/model_card.md). System health and live metrics are available at [`https://surf-health-api.onrender.com/system/health`](https://surf-health-api.onrender.com/system/health).

## License

Apache License 2.0 — see [LICENSE](LICENSE). Anyone may use, modify, and redistribute this code with attribution.

## Acknowledgement

- This project is inspired by the project my team attempted: https://github.com/SatrunsDream/DataTide
- Special thanks to Allison Sharpe, Stormwater Environmental Specialist at City of San Diego.
