# Shorelife (formerly Surf Health)

California marine beach health forecast platform focused on daily enterococcus risk for surfers and beachgoers.

## Project Structure

- `backend/`: Python FastAPI service, ingestion pipelines (BeachWatch, CEDEN, Stormwater), feature engineering, model training, and tests.
- `web/`: Next.js (React) website for public and research-facing views.
- `mobile/`: React Native (Expo) mobile application for iOS and Android.

## Local Development

### Backend

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

### Web

The web app uses Next.js.

```bash
cd web
npm install
```

Set `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000` in `web/.env.local`.

To run the web app:
```bash
npm run dev
```

### Mobile

The mobile app is built with Expo.

```bash
cd mobile
npm install
```

To run the mobile app locally:
```bash
npm start
```

## Data + Modeling

The backend ships with fixtures so the API and UI work immediately without needing to run the full pipeline.

### Automated Pipelines

The entire data ingestion, ML training, and static data generation process is fully automated via GitHub Actions (`daily-forecast.yml`). It runs daily to:
1. Fetch the latest California BeachWatch data.
2. Fetch CEDEN Safe-to-Swim data.
3. Fetch external covariates (CDIP, CeNCOOS, EPA UV, Hydrology, Stormwater).
4. Run ML model training and generate forecasts.
5. Bake static data for the web/mobile apps.
6. Commit the updated curated data back to the repository.

### Manual Data Pipeline

If you need to run the pipeline manually locally, refer to the scripts in `backend/app/data/pipeline/` and `backend/app/ml/training.py`.

## Mobile Deployment

Mobile deployment to iOS and Android is handled via Expo Application Services (EAS).

- **iOS:** Run `./build_and_submit.sh` in the `mobile/` directory to build and submit to TestFlight.
- **Android:** Run `./build_and_submit_android.sh` to trigger an EAS cloud build. Note: The first `.aab` upload must be done manually via the Google Play Console.

## Notes

- Operational storage targets Postgres/PostGIS and research snapshots target DuckDB/Parquet/SQLite.
- The current repo is scaffolded for local-first development on Apple Silicon with PyTorch MPS.

## Acknowledgement

- This project is inspired by the project my team attempted to do: https://github.com/SatrunsDream/DataTide
- Special thanks to Allison Sharpe, Stormwater Environmental Specialist at City of San Diego.
