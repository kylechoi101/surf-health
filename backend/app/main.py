import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router


async def run_pipeline():
    print("[daily_forecast] Starting daily ML pipeline...")
    cmd = (
        "curl -s -o /tmp/beach-monitoring-stations.csv 'https://raw.githubusercontent.com/CA-Water-Board/Beach-Water-Quality-Postings/master/stations.csv' && "
        "python -m app.data.pipeline.cli --normalize-beachwatch --stations-csv /tmp/beach-monitoring-stations.csv --merge-ceden --with-external-covariates --with-hydrology && "
        "python -m app.ml.training --curated --forecast-date \"$(date +%Y-%m-%d)\""
    )
    process = await asyncio.create_subprocess_shell(cmd)
    await process.communicate()
    print(f"[daily_forecast] Finished daily ML pipeline with exit code {process.returncode}")


async def run_daily_forecast_loop():
    # If the curated dataset doesn't exist (e.g. on fresh Render deployment), run it immediately
    if not Path("/app/data/curated/beaches.parquet").exists():
        print("[daily_forecast] No curated data found. Running initial pipeline bootstrap...")
        await run_pipeline()

    while True:
        now = datetime.now(UTC)
        next_run = now.replace(hour=13, minute=0, second=0, microsecond=0)
        if now >= next_run:
            next_run += timedelta(days=1)
        sleep_seconds = (next_run - now).total_seconds()
        
        print(f"[daily_forecast] Sleeping for {sleep_seconds:.0f} seconds until next run at {next_run.isoformat()} UTC.")
        await asyncio.sleep(sleep_seconds)
        
        await run_pipeline()


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(run_daily_forecast_loop())
    yield
    task.cancel()


app = FastAPI(
    title="Surf Health API",
    summary="California marine beach health forecast service",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
def root():
    return {
        "name": "Surf Health API",
        "docs": "/docs",
        "status": "ok",
    }

