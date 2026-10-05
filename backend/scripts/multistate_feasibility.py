"""Hawaii / Florida expansion feasibility study (research only; touches no production path).

Stages (each resumable from on-disk caches):

    fetch    WQP enterococcus results + station metadata, one state x one quarter per
             request, cached under data/raw/wqp/. Also records E. coli / fecal coliform
             result counts per year (HEAD-style count queries, no download).
    rain     Open-Meteo historical archive, one request per 0.1 deg coord covering the
             whole date range, cached under data/raw/openmeteo_multistate/.
    analyze  Coverage tables (Part 1) and the walk-forward model replication (Part 3);
             writes data/experiments/multistate/feasibility_results.json.

    python scripts/multistate_feasibility.py fetch --state HI
    python scripts/multistate_feasibility.py rain --state HI
    python scripts/multistate_feasibility.py analyze --state HI

Run from backend/ with the project venv. Network calls: connect 30 s, read 120 s,
at most 3 attempts with backoff.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from io import StringIO
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))  # so `app.*` pure functions import when run as a script
RAW_WQP = REPO / "data" / "raw" / "wqp"
RAW_RAIN = REPO / "data" / "raw" / "openmeteo_multistate"
OUT = REPO / "data" / "experiments" / "multistate"

TODAY = pd.Timestamp("2026-10-04")
START = pd.Timestamp("2022-01-01")

STATES = {
    "HI": {"fips": "US:15", "tz": "Pacific/Honolulu", "name": "Hawaii"},
    "FL": {"fips": "US:12", "tz": "America/New_York", "name": "Florida"},
}

WQP_RESULT_URL = "https://www.waterqualitydata.us/data/Result/search"
WQP_STATION_URL = "https://www.waterqualitydata.us/data/Station/search"
OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"

TIMEOUT = httpx.Timeout(connect=30.0, read=120.0, write=30.0, pool=30.0)
MAX_ATTEMPTS = 3


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _get(client: httpx.Client, url: str, params: dict, method: str = "GET") -> httpx.Response:
    last: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = client.request(method, url, params=params)
            if resp.status_code in (429, 500, 502, 503, 504):
                raise httpx.HTTPStatusError(f"HTTP {resp.status_code}", request=resp.request, response=resp)
            resp.raise_for_status()
            return resp
        except (httpx.HTTPError, httpx.TimeoutException) as exc:  # noqa: PERF203
            last = exc
            wait = 5 * 2 ** (attempt - 1)
            log(f"  attempt {attempt}/{MAX_ATTEMPTS} failed: {type(exc).__name__}: {str(exc)[:120]}; sleep {wait}s")
            if attempt < MAX_ATTEMPTS:
                time.sleep(wait)
    raise RuntimeError(f"giving up on {url} {params}: {last}")


# --------------------------------------------------------------------------- fetch

def _quarters(start: pd.Timestamp, end: pd.Timestamp):
    q = pd.period_range(start, end, freq="Q")
    for p in q:
        lo = max(p.start_time.normalize(), start)
        hi = min(p.end_time.normalize(), end)
        yield f"{p.year}Q{p.quarter}", lo, hi


def fetch_state(state: str) -> None:
    cfg = STATES[state]
    RAW_WQP.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
        # Station metadata (site type, coordinates, county) for every enterococcus site.
        st_path = RAW_WQP / f"{state}_stations_enterococcus.csv"
        if not st_path.exists():
            log(f"{state}: stations")
            resp = _get(client, WQP_STATION_URL, {
                "statecode": cfg["fips"], "characteristicName": "Enterococcus",
                "startDateLo": START.strftime("%m-%d-%Y"), "mimeType": "csv", "providers": "STORET",
            })
            st_path.write_text(resp.text)
        for label, lo, hi in _quarters(START, TODAY):
            path = RAW_WQP / f"{state}_enterococcus_{label}.csv"
            if path.exists():
                continue
            t0 = time.time()
            resp = _get(client, WQP_RESULT_URL, {
                "statecode": cfg["fips"], "characteristicName": "Enterococcus",
                "startDateLo": lo.strftime("%m-%d-%Y"), "startDateHi": hi.strftime("%m-%d-%Y"),
                "mimeType": "csv", "dataProfile": "resultPhysChem", "providers": "STORET",
            })
            tmp = path.with_suffix(".tmp")
            tmp.write_text(resp.text)
            tmp.replace(path)
            log(f"{state} {label}: {resp.headers.get('Total-Result-Count')} results, "
                f"{len(resp.content)/1e6:.1f} MB, {time.time()-t0:.0f}s")
        # Other fecal indicators: counts only (no download).
        cnt_path = RAW_WQP / f"{state}_other_indicator_counts.json"
        counts = json.loads(cnt_path.read_text()) if cnt_path.exists() else {}
        for char in ("Escherichia coli", "Fecal Coliform", "Enterococcus"):
            for year in range(START.year, TODAY.year + 1):
                key = f"{char}|{year}"
                if key in counts:
                    continue
                hi = min(pd.Timestamp(f"{year}-12-31"), TODAY)
                resp = _get(client, WQP_RESULT_URL, {
                    "statecode": cfg["fips"], "characteristicName": char,
                    "startDateLo": f"01-01-{year}", "startDateHi": hi.strftime("%m-%d-%Y"),
                    "mimeType": "csv", "dataProfile": "resultPhysChem", "providers": "STORET",
                }, method="HEAD")
                counts[key] = {
                    "results": int(resp.headers.get("Total-Result-Count", 0) or 0),
                    "sites": int(resp.headers.get("Total-Site-Count", 0) or 0),
                }
                cnt_path.write_text(json.dumps(counts, indent=1))
                log(f"{state} {char} {year}: {counts[key]}")
    log(f"{state}: fetch complete")


# --------------------------------------------------------------------------- load + filter

def load_raw(state: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    files = sorted(RAW_WQP.glob(f"{state}_enterococcus_*.csv"))
    if not files:
        raise SystemExit(f"no raw files for {state}; run fetch first")
    frames = [pd.read_csv(f, dtype=str, low_memory=False) for f in files]
    raw = pd.concat([f for f in frames if len(f)], ignore_index=True)
    stations = pd.read_csv(RAW_WQP / f"{state}_stations_enterococcus.csv", dtype=str, low_memory=False)
    return raw, stations


def classify_sites(stations: pd.DataFrame, raw: pd.DataFrame) -> pd.DataFrame:
    """One row per site: type, org, name, coords, and a keep/drop decision with a reason.

    Keep rule (in order):
      1. WQX type "BEACH Program Site-*"  -> keep (the state's BEACH Act program sites)
      2. WQX type "Ocean"                 -> keep (open-coast sites)
      3. Estuary / Bay type whose site name says it is a swimming beach
         ("beach", "bch", "swim", "bathing") -> keep
      4. everything else (rivers, canals, lakes, ambient estuary stations) -> drop
    Ambient estuary stations are dropped on purpose: they are water-quality monitoring
    points (often mid-channel or at outfalls), not places people swim, and their
    exceedance rates are not beach exceedance rates.
    """
    st = stations.rename(columns={"LatitudeMeasure": "lat", "LongitudeMeasure": "lon"}).copy()
    st["type"] = st["MonitoringLocationTypeName"].fillna("").str.strip()
    t = st["type"].str.lower()
    st["name"] = st["MonitoringLocationName"].fillna("")
    n = st["name"].str.lower()
    proj = (raw.groupby("MonitoringLocationIdentifier")["ProjectName"]
            .agg(lambda s: " | ".join(sorted(set(s.dropna().astype(str))))[:200]))
    st["projects"] = st["MonitoringLocationIdentifier"].map(proj).fillna("")
    r1 = t.str.startswith("beach program site")
    r2 = t.eq("ocean")
    r3 = t.str.contains("estuar|bay", regex=True) & n.str.contains(r"beach|\bbch\b|swim|bathing", regex=True)
    st["keep"] = r1 | r2 | r3
    st["reason"] = np.select([r1, r2, r3], ["BEACH program site type", "Ocean site type",
                                            "estuary/bay site named as a beach"], default="non-beach site type")
    st["lat"] = pd.to_numeric(st["lat"], errors="coerce")
    st["lon"] = pd.to_numeric(st["lon"], errors="coerce")
    return st[["MonitoringLocationIdentifier", "OrganizationIdentifier", "type", "name", "projects",
               "lat", "lon", "CountyCode", "keep", "reason"]]


def normalize(raw: pd.DataFrame) -> pd.DataFrame:
    """Result rows -> one row per result, with non-detects KEPT (as censored, value = DL or 0).

    The production ``normalize_wqp_results`` drops rows with no numeric value, which on
    WQP drops every non-detect (they carry ResultDetectionConditionText and an empty
    value) and inflates exceedance rates. Here a non-detect is kept as a clean result.
    """
    df = raw.copy()
    df["value_raw"] = df["ResultMeasureValue"]
    df["value"] = pd.to_numeric(df["ResultMeasureValue"].str.replace("<", "", regex=False)
                                .str.replace(">", "", regex=False), errors="coerce")
    cond = df["ResultDetectionConditionText"].fillna("").str.lower()
    qual = df["MeasureQualifierCode"].fillna("").str.upper()
    vraw = df["ResultMeasureValue"].fillna("")
    df["nondetect"] = cond.str.contains("not detected|below|non-detect|<", regex=True) | vraw.str.startswith("<") \
        | vraw.str.lower().str.contains("non-detect|not detected|^nd$", regex=True) \
        | qual.str.contains(r"\bU\b|<|ND", regex=True)
    df["above_range"] = cond.str.contains("above|present above|greater", regex=True) | vraw.str.startswith(">") \
        | qual.str.contains(">|TNTC", regex=True)
    dl = pd.to_numeric(df["DetectionQuantitationLimitMeasure/MeasureValue"], errors="coerce")
    df.loc[df["nondetect"] & df["value"].isna(), "value"] = dl.where(dl.notna(), 0.0)
    df["dl"] = dl
    df["censored"] = df["nondetect"] | df["above_range"]
    df["units"] = df["ResultMeasure/MeasureUnitCode"].fillna("unknown").str.strip()
    df["method"] = (df["ResultAnalyticalMethod/MethodIdentifier"].fillna("") + " / "
                    + df["ResultAnalyticalMethod/MethodName"].fillna("")).str.strip(" /")
    df["method"] = df["method"].replace("", "unknown")
    m = (df["method"] + " " + df["units"]).str.lower()
    df["assay"] = np.select(
        [m.str.contains("pcr|copies|cce|1609|1611|1696"),
         m.str.contains("mpn|enterolert|idexx|9230d|quanti"),
         m.str.contains("cfu|1600|membrane|mei|mel")],
        ["qPCR", "MPN (Enterolert)", "CFU (membrane filtration)"], default="other/unknown")
    df["station_id"] = df["MonitoringLocationIdentifier"].astype(str)
    df["org"] = df["OrganizationIdentifier"].astype(str)
    df["sample_date"] = pd.to_datetime(df["ActivityStartDate"], errors="coerce")
    df["activity_type"] = df["ActivityTypeCode"].fillna("")
    df["status"] = df["ResultStatusIdentifier"].fillna("")
    df = df.loc[df["sample_date"].notna()]
    return df[["station_id", "org", "sample_date", "ActivityStartTime/Time", "activity_type", "status",
               "value_raw", "value", "dl", "nondetect", "above_range", "censored", "units", "method", "assay",
               "ProjectName", "MonitoringLocationName", "ActivityLocation/LatitudeMeasure",
               "ActivityLocation/LongitudeMeasure", "LastUpdated"]].reset_index(drop=True)


# --------------------------------------------------------------------------- state limits

# The single-sample limit each state uses to issue advisories (sources in REPORT.md):
#   Hawaii DOH CWB: Beach Action Value 130 enterococci/100 mL (health.hawaii.gov/cwb/beach-monitoring-program/)
#   Florida DOH Healthy Beaches: 70 CFU/100 mL, advisory after a confirming resample also > 70
#     (floridahealth.gov .../beach-water-quality/)
STATE_LIMIT = {"HI": 130.0, "FL": 70.0}
CA_STV = 104.0
PCR_LIMIT = 1413.0  # applied to any qPCR rows, same rule as California (an assumption outside CA)

# QC activity types that are not routine beach samples.
QC_ACTIVITY = ("quality control", "blank", "replicate", "duplicate", "spike")


def limit_for(assay: pd.Series, culture_limit: float) -> np.ndarray:
    return np.where(assay.eq("qPCR"), PCR_LIMIT, culture_limit)


def build_sample_days(res: pd.DataFrame, culture_limit: float) -> pd.DataFrame:
    """Results -> one row per (station, date): the worst result of the day is the label."""
    r = res.copy()
    r["limit"] = limit_for(r["assay"], culture_limit)
    r["ratio"] = r["value"] / r["limit"]
    r["exceeds"] = (r["value"] > r["limit"]) & ~r["nondetect"]
    r["exceeds104"] = (r["value"] > np.where(r["assay"].eq("qPCR"), PCR_LIMIT, CA_STV)) & ~r["nondetect"]
    r["is_qpcr"] = r["assay"].eq("qPCR")
    r = r.sort_values(["station_id", "sample_date", "exceeds", "ratio"], na_position="first")
    agg = r.groupby(["station_id", "sample_date"], as_index=False).agg(
        org=("org", "last"), exceeds=("exceeds", "max"), exceeds104=("exceeds104", "max"),
        ratio=("ratio", "max"), value=("value", "max"), is_qpcr=("is_qpcr", "max"),
        n_results=("value", "size"), censored=("censored", "max"))
    return agg


def _pct(x, q):
    return float(np.percentile(x, q)) if len(x) else None


def coverage(res: pd.DataFrame, sd: pd.DataFrame, culture_limit: float) -> dict:
    """Part 1 numbers for one population of results / sample-days."""
    out: dict = {}
    if res.empty:
        return {"results": 0}
    n_months_window = (TODAY.to_period("M") - START.to_period("M")).n  # full months 2022-01 .. 2026-09
    per_st = sd.groupby("station_id").agg(n=("sample_date", "size"), first=("sample_date", "min"),
                                          last=("sample_date", "max"))
    res_per_st = res.groupby("station_id").size()
    span_months = ((per_st["last"] - per_st["first"]).dt.days / 30.44).clip(lower=1.0)
    out["stations_ge1_result"] = int((res_per_st >= 1).sum())
    out["stations_ge10_results"] = int((res_per_st >= 10).sum())
    out["stations_ge1_sampleday_per_month_over_window"] = int((per_st["n"] >= n_months_window).sum())
    out["stations_ge1_sampleday_per_month_over_own_span"] = int((per_st["n"] / span_months >= 1).sum())
    out["window_months"] = int(n_months_window)
    out["results"] = int(len(res))
    out["sample_days"] = int(len(sd))
    out["results_per_year"] = {int(k): int(v) for k, v in res.groupby(res["sample_date"].dt.year).size().items()}
    sy = sd.groupby([sd["station_id"], sd["sample_date"].dt.year]).size()
    out["sample_days_per_station_year"] = {
        int(y): {"stations": int(len(v)), "median": _pct(v, 50), "p25": _pct(v, 25), "p75": _pct(v, 75)}
        for y, v in sy.groupby(level=1)}
    gaps = sd.sort_values(["station_id", "sample_date"]).groupby("station_id")["sample_date"].diff().dt.days.dropna()
    out["gap_days"] = {"median": _pct(gaps, 50), "p90": _pct(gaps, 90), "n_gaps": int(len(gaps))}
    out["sample_days_by_calendar_month"] = {int(k): int(v) for k, v in
                                           sd.groupby(sd["sample_date"].dt.month).size().items()}
    newest = sd["sample_date"].max()
    out["newest_sample_date"] = str(newest.date())
    out["lag_days_to_today"] = int((TODAY - newest).days)
    last = per_st["last"]
    out["share_stations_sampled_last_30d"] = float((last >= TODAY - pd.Timedelta(days=30)).mean())
    out["share_stations_sampled_last_90d"] = float((last >= TODAY - pd.Timedelta(days=90)).mean())
    out["share_stations_sampled_last_365d"] = float((last >= TODAY - pd.Timedelta(days=365)).mean())
    out["units"] = {str(k): int(v) for k, v in res["units"].value_counts().items()}
    out["methods"] = {str(k): int(v) for k, v in res["method"].value_counts().head(12).items()}
    out["assay"] = {str(k): int(v) for k, v in res["assay"].value_counts().items()}
    out["share_nondetect"] = float(res["nondetect"].mean())
    out["share_censored_any"] = float(res["censored"].mean())
    # Some labs report "<DL" as the bare DL with no qualifier (Florida DOH: 10, 4 or 2).
    if "dl" in res.columns:
        dl = pd.to_numeric(res["dl"], errors="coerce")
        out["share_at_or_below_reported_detection_limit"] = float(((res["value"] <= dl) | res["nondetect"]).mean())
        out["share_rows_with_detection_limit"] = float(dl.notna().mean())
    out["share_value_missing_after_nd_fill"] = float(res["value"].isna().mean())
    out["exceedance_rate_sampleday_state_limit"] = float(sd["exceeds"].mean())
    out["exceedance_rate_sampleday_104"] = float(sd["exceeds104"].mean())
    out["state_limit"] = culture_limit
    out["positive_sample_days_per_year"] = {int(k): int(v) for k, v in
                                           sd.groupby(sd["sample_date"].dt.year)["exceeds"].sum().items()}
    out["positive_sample_days_total"] = int(sd["exceeds"].sum())
    return out


# --------------------------------------------------------------------------- rain

def _coord_key(lat: float, lon: float) -> str:
    return f"{round(lat, 1):.1f}_{round(lon, 1):.1f}"


def fetch_rain(state: str, stations: pd.DataFrame | None = None, start: str = "2021-12-25",
               prefix: str | None = None) -> None:
    """One Open-Meteo archive request per 0.1 deg coord: hourly precipitation, local time."""
    cfg = STATES[state]
    RAW_RAIN.mkdir(parents=True, exist_ok=True)
    if stations is None:
        stations = pd.read_parquet(OUT / f"{state}_stations_kept.parquet")
    coords = sorted({_coord_key(a, b) for a, b in zip(stations["lat"], stations["lon"])
                     if np.isfinite(a) and np.isfinite(b)})
    log(f"{state}: {len(coords)} rain coords")
    end = (TODAY - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    with httpx.Client(timeout=TIMEOUT) as client:
        for i, key in enumerate(coords):
            path = RAW_RAIN / f"{prefix or state}_{key}.parquet"
            if path.exists():
                continue
            lat, lon = map(float, key.split("_"))
            params = {"latitude": lat, "longitude": lon, "start_date": start, "end_date": end,
                      "hourly": "precipitation", "timezone": cfg["tz"], "precipitation_unit": "mm"}
            resp = None
            for attempt in range(1, 7):
                try:
                    resp = client.get(OPEN_METEO_ARCHIVE, params=params)
                    if resp.status_code == 429:
                        reason = resp.text[:160]
                        # Open-Meteo free tier: 600 weighted calls/min, 5000/hour, 10000/day.
                        wait = 900 if "hour" in reason.lower() else 70 * attempt
                        log(f"  429 rate-limited ({reason}); sleep {wait}s")
                        time.sleep(wait)
                        resp = None
                        continue
                    resp.raise_for_status()
                    break
                except (httpx.HTTPError, httpx.TimeoutException) as exc:
                    log(f"  {key} attempt {attempt} failed: {type(exc).__name__}")
                    resp = None
                    if attempt >= MAX_ATTEMPTS:
                        raise
                    time.sleep(5 * 2 ** (attempt - 1))
            if resp is None:
                raise RuntimeError(f"Open-Meteo kept rate-limiting {key}; rerun later (cache resumes)")
            h = resp.json()["hourly"]
            df = pd.DataFrame({"time": pd.to_datetime(h["time"]), "precip_mm": h["precipitation"]})
            tmp = path.with_suffix(".tmp")
            df.to_parquet(tmp, index=False)
            tmp.replace(path)
            if i % 10 == 0:
                log(f"{state} rain {i + 1}/{len(coords)} {key}")
            weight = max(1.0, (pd.Timestamp(end) - pd.Timestamp(start)).days / 14 / 10)
            time.sleep(max(1.0, weight * 60 / 400))
    log(f"{state}: rain complete")


def rain_72h_to_5am(prefix: str, keys: pd.Series, dates: pd.Series) -> np.ndarray:
    """mm of rain in the 72 h ending 05:00 local on each date; NaN if the coord is not cached."""
    out = np.full(len(keys), np.nan)
    frame = pd.DataFrame({"k": keys.to_numpy(), "d": pd.to_datetime(dates).dt.normalize().to_numpy()})
    for key, idx in frame.groupby("k").groups.items():
        path = RAW_RAIN / f"{prefix}_{key}.parquet"
        if not path.exists():
            continue
        h = pd.read_parquet(path).set_index("time")["precip_mm"].astype(float)
        # Window [D-3 05:00, D 05:00): hourly stamps label the hour ENDING at that time in
        # Open-Meteo, so the hour ending 05:00 on D is included and the hour ending 05:00
        # on D-3 is not.
        cs = h.fillna(0.0).cumsum()
        ends = frame.loc[idx, "d"] + pd.Timedelta(hours=5)
        starts = ends - pd.Timedelta(hours=72)
        a = cs.reindex(ends.to_numpy(), method="ffill").to_numpy()
        b = cs.reindex(starts.to_numpy(), method="ffill").to_numpy()
        out[np.asarray(idx)] = a - b
    return out


# --------------------------------------------------------------------------- model

def lab_features(sd: pd.DataFrame, query: pd.DataFrame, window_days: int = 365, prior: float = 5.0) -> pd.DataFrame:
    """Lookup + last-result features per query (station, date), strictly before the date.

    Reuses the served model's pure feature function so the lookup and R/F terms are
    identical to production.
    """
    from app.ml.logit_challenger import lab_history_features
    bd = pd.DataFrame({"beach_id": sd["station_id"], "sample_date": sd["sample_date"],
                       "exceeds_stv": sd["exceeds"].astype(bool), "enterococcus_action_ratio": sd["ratio"]})
    return lab_history_features(bd, query["station_id"].tolist(), query["sample_date"].tolist(),
                                window_days=window_days, prior_strength=prior)


def fit_offset_logit(X: np.ndarray, off: np.ndarray, y: np.ndarray, ridge: float = 1e-4) -> np.ndarray:
    X1 = np.column_stack([np.ones(len(X)), X])
    beta = np.zeros(X1.shape[1])
    pen = ridge * np.eye(X1.shape[1])
    pen[0, 0] = 0.0
    for _ in range(60):
        p = 1.0 / (1.0 + np.exp(-(off + X1 @ beta)))
        w = p * (1 - p)
        step = np.linalg.solve((X1 * w[:, None]).T @ X1 + pen, X1.T @ (y - p) - pen @ beta)
        beta += step
        if np.max(np.abs(step)) < 1e-8:
            break
    return beta


def predict_offset_logit(X: np.ndarray, off: np.ndarray, beta: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-(off + np.column_stack([np.ones(len(X)), X]) @ beta)))


VARIANTS = {
    "logistic": ["R", "RF", "W", "S"],                    # the served form (CA phase)
    "logistic_free_phase": ["R", "RF", "W", "S", "S_sin"],  # cos + sin: season peak at any time of year
}


def metrics(y, p, b) -> dict:
    from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

    from app.ml.two_tier import within_beach_auroc
    y = np.asarray(y, int)
    wb, nb, nr = within_beach_auroc(y, p, b)
    return {"auroc": float(roc_auc_score(y, p)), "aucpr": float(average_precision_score(y, p)),
            "brier": float(brier_score_loss(y, p)), "within_station_auroc": wb,
            "within_station_n_stations": nb, "within_station_n_rows": nr}


def cluster_bootstrap(y, pa, pb, b, reps: int = 500, seed: int = 0) -> dict:
    """Beach-cluster bootstrap of metric(a) - metric(b): resample stations with replacement."""
    from sklearn.metrics import average_precision_score, roc_auc_score

    from app.ml.two_tier import within_beach_auroc
    rng = np.random.default_rng(seed)
    y = np.asarray(y, int)
    b = np.asarray(b, object)
    groups = pd.Series(np.arange(len(y))).groupby(b).apply(lambda s: s.to_numpy()).to_list()
    deltas = {k: [] for k in ("auroc", "aucpr", "brier", "within_station_auroc")}
    for _ in range(reps):
        pick = rng.integers(0, len(groups), len(groups))
        idx = np.concatenate([groups[i] for i in pick])
        # keep bootstrap copies of a station distinct for within-station AUROC
        bid = np.concatenate([np.full(len(groups[i]), j) for j, i in enumerate(pick)])
        yy = y[idx]
        if yy.min() == yy.max():
            continue
        a, c = pa[idx], pb[idx]
        deltas["auroc"].append(roc_auc_score(yy, a) - roc_auc_score(yy, c))
        deltas["aucpr"].append(average_precision_score(yy, a) - average_precision_score(yy, c))
        deltas["brier"].append(np.mean((a - yy) ** 2) - np.mean((c - yy) ** 2))
        wa = within_beach_auroc(yy, a, bid)[0]
        wc = within_beach_auroc(yy, c, bid)[0]
        if np.isfinite(wa) and np.isfinite(wc):
            deltas["within_station_auroc"].append(wa - wc)
    return {k: {"ci_low": _pct(v, 2.5), "ci_high": _pct(v, 97.5), "reps": len(v)} for k, v in deltas.items()}


def walk_forward(state: str, sd: pd.DataFrame, stations: pd.DataFrame, label: str,
                 end_month: pd.Period | None = None, n_months: int = 12,
                 history_start: pd.Timestamp = START, rain_prefix: str | None = None) -> dict:
    """Monthly refit on every sample-day before the month; score the 12 months ending at
    ``end_month`` (default: the newest month with data)."""
    sd = sd.sort_values(["station_id", "sample_date"]).reset_index(drop=True)
    feats = lab_features(sd, sd)
    sd = sd.join(feats[["n", "pos", "g", "lookup", "L", "last_exceeds", "R", "F", "age_days"]])
    coord = stations.set_index("MonitoringLocationIdentifier")
    keys = sd["station_id"].map(lambda s: _coord_key(coord.at[s, "lat"], coord.at[s, "lon"])
                                if s in coord.index and np.isfinite(coord.at[s, "lat"]) else "none")
    mm = rain_72h_to_5am(rain_prefix or state, keys, sd["sample_date"])
    rain_cov = float(np.isfinite(mm).mean())
    sd["rain_mm_72h"] = mm
    sd["W"] = np.log2(1.0 + 4.0 * np.nan_to_num(mm, nan=0.0).clip(min=0) / 25.4)
    doy = sd["sample_date"].dt.dayofyear.to_numpy()
    sd["S"] = np.cos(2 * np.pi * (doy - 15) / 365.25)
    sd["S_sin"] = np.sin(2 * np.pi * (doy - 15) / 365.25)
    sd["RF"] = sd["R"] * sd["F"]
    has_qpcr = bool(sd["is_qpcr"].any())
    variants = dict(VARIANTS)
    if has_qpcr:
        # assay of the station's most recent prior sample-day (strictly before D)
        sd["qpcr"] = sd.groupby("station_id")["is_qpcr"].shift(1).fillna(False).astype(float)
        variants["logistic_qpcr"] = ["R", "RF", "W", "S", "qpcr"]
    sd["persistence"] = np.where(sd["last_exceeds"] == 1, 1.0, sd["g"])
    # training rows need a full 365-day lookup window behind them
    eligible = sd["sample_date"] >= history_start + pd.Timedelta(days=365)
    last_month = end_month or sd["sample_date"].max().to_period("M")
    months = pd.period_range(last_month - (n_months - 1), last_month, freq="M")
    preds = []
    coefs = []
    for m in months:
        in_m = sd["sample_date"].dt.to_period("M").eq(m)
        train = sd.loc[eligible & (sd["sample_date"] < m.start_time)]
        test = sd.loc[in_m].copy()
        if test.empty or train["exceeds"].sum() < 10:
            continue
        for name, cols in variants.items():
            beta = fit_offset_logit(train[cols].to_numpy(float), train["L"].to_numpy(float),
                                    train["exceeds"].astype(float).to_numpy())
            test[f"p_{name}"] = predict_offset_logit(test[cols].to_numpy(float), test["L"].to_numpy(float), beta)
            coefs.append({"month": str(m), "variant": name, "train_rows": int(len(train)),
                          "train_pos": int(train["exceeds"].sum()),
                          **dict(zip(["intercept", *cols], map(float, beta)))})
        preds.append(test)
    if not preds:
        return {"status": "no scorable months"}
    scored = pd.concat(preds, ignore_index=True)
    scored.to_parquet(OUT / f"{state}_{label}_walkforward_predictions.parquet", index=False)
    y = scored["exceeds"].astype(int).to_numpy()
    b = scored["station_id"].to_numpy()
    res = {"scored_months": [str(m) for m in months], "scored_rows": int(len(scored)),
           "scored_positives": int(y.sum()), "scored_base_rate": float(y.mean()),
           "scored_stations": int(scored["station_id"].nunique()),
           "rain_coverage_all_sample_days": rain_cov,
           "rain_coverage_scored": float(scored["rain_mm_72h"].notna().mean()),
           "share_scored_with_no_prior_sample_in_window": float((scored["n"] == 0).mean()),
           "median_age_days_of_last_sample": _pct(scored["age_days"].dropna(), 50),
           "has_qpcr": has_qpcr, "metrics": {}, "bootstrap_logistic_minus_lookup": {}, "coefficients": coefs}
    res["metrics"]["lookup"] = metrics(y, scored["lookup"].to_numpy(), b)
    res["metrics"]["persistence"] = metrics(y, scored["persistence"].to_numpy(), b)
    for name in variants:
        res["metrics"][name] = metrics(y, scored[f"p_{name}"].to_numpy(), b)
        res["bootstrap_logistic_minus_lookup"][name] = cluster_bootstrap(
            y, scored[f"p_{name}"].to_numpy(), scored["lookup"].to_numpy(), b)
    return res


CA_REFERENCE = {
    "source": "CLAUDE.md 'Served estimate: logistic model on top of the lookup' walk-forward backtest "
              "(2025-09-01..2026-09-21, forward D+1..3 days, monthly refit)",
    "lookup": {"auroc": 0.827, "aucpr": 0.548, "brier": 0.0803, "within_station_auroc": 0.45},
    "logistic": {"auroc": 0.851, "aucpr": 0.591, "brier": 0.0766, "within_station_auroc": 0.64},
    "caveat": "CA is scored on forward served days (every beach, every day) against the next lab result; "
              "here we score lab sample-days. Base rates differ, and AUCPR scales with the base rate, so only "
              "AUROC / within-station AUROC compare loosely across states.",
}


# --------------------------------------------------------------------------- analyze

def prepare(state: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    raw, stations = load_raw(state)
    res_all = normalize(raw)
    sites = classify_sites(stations, raw)
    # sites that appear in results but not in the station file
    missing = sorted(set(res_all["station_id"]) - set(sites["MonitoringLocationIdentifier"]))
    filt: dict = {"raw_results": int(len(res_all)), "raw_stations_in_results": int(res_all["station_id"].nunique()),
                  "stations_missing_metadata": len(missing)}
    keep_ids = set(sites.loc[sites["keep"], "MonitoringLocationIdentifier"])
    in_results = sites[sites["MonitoringLocationIdentifier"].isin(set(res_all["station_id"]))]
    filt["site_types_in_results"] = {str(k): int(v) for k, v in in_results["type"].value_counts().items()}
    filt["stations_dropped_by_site_filter"] = int((~in_results["keep"]).sum()) + len(missing)
    filt["dropped_site_types"] = {str(k): int(v) for k, v in
                                  in_results.loc[~in_results["keep"], "type"].value_counts().items()}
    filt["kept_by_rule"] = {str(k): int(v) for k, v in
                            in_results.loc[in_results["keep"], "reason"].value_counts().items()}
    filt["dropped_stations_by_org"] = {str(k): int(v) for k, v in in_results.loc[
        ~in_results["keep"], "OrganizationIdentifier"].value_counts().head(15).items()}
    res = res_all[res_all["station_id"].isin(keep_ids)]
    filt["results_dropped_by_site_filter"] = int(len(res_all) - len(res))
    act = res["activity_type"].str.lower()
    qc = act.str.contains("|".join(QC_ACTIVITY))
    filt["results_dropped_qc_activity"] = int(qc.sum())
    filt["activity_types_kept"] = {str(k): int(v) for k, v in res.loc[~qc, "activity_type"].value_counts().items()}
    res = res.loc[~qc]
    nov = res["value"].isna()
    filt["results_dropped_no_value"] = int(nov.sum())
    res = res.loc[~nov]
    neg = res["value"] < 0
    filt["results_dropped_negative"] = int(neg.sum())
    res = res.loc[~neg].copy()
    filt["results_kept"] = int(len(res))
    filt["stations_kept"] = int(res["station_id"].nunique())
    kept_sites = sites[sites["MonitoringLocationIdentifier"].isin(set(res["station_id"]))].copy()
    OUT.mkdir(parents=True, exist_ok=True)
    kept_sites.to_parquet(OUT / f"{state}_stations_kept.parquet", index=False)
    return res, kept_sites, sites, filt


# Extra scoring windows. Hawaii DOH stopped publishing routine results after 2024-04 (WQP and its
# own export), so the default "last 12 months" window holds only City & County of Honolulu
# stations; the DOH-era window scores the state program itself.
EXTRA_WINDOWS = {"HI": {"doh_era": "2024-04"}}


def analyze(state: str, with_model: bool = True) -> dict:
    limit = STATE_LIMIT[state]
    res, kept_sites, sites, filt = prepare(state)
    sd = build_sample_days(res, limit)
    sd.to_parquet(OUT / f"{state}_wqp_sample_days.parquet", index=False)
    out = {"state": STATES[state]["name"], "wqp_statecode": STATES[state]["fips"], "filter": filt,
           "coverage_state": coverage(res, sd, limit), "coverage_by_org": {}}
    org_names = {}
    for org, r in res.groupby("org"):
        out["coverage_by_org"][org] = coverage(r, sd[sd["org"] == org], limit)
        org_names[org] = None
    out["other_indicators_wqp_counts"] = json.loads((RAW_WQP / f"{state}_other_indicator_counts.json").read_text()) \
        if (RAW_WQP / f"{state}_other_indicator_counts.json").exists() else None
    gate = out["coverage_state"]
    years = (sd["sample_date"].max() - sd["sample_date"].min()).days / 365.25
    out["model_gate"] = {"years_of_history": years, "positive_sample_days": gate["positive_sample_days_total"],
                         "passes": bool(years >= 2 and gate["positive_sample_days_total"] >= 100)}
    if with_model and out["model_gate"]["passes"]:
        out["model_wqp"] = walk_forward(state, sd, kept_sites, "wqp")
        for name, end in EXTRA_WINDOWS.get(state, {}).items():
            out[f"model_wqp_{name}"] = walk_forward(state, sd, kept_sites, f"wqp_{name}", pd.Period(end, "M"))
        out["model_ca_reference"] = CA_REFERENCE
    return out


# --------------------------------------------------------------------------- Hawaii DOH own feed

HI_CWB = REPO / "data" / "raw" / "hi_cwb"
CWB_HISTORY_START = pd.Timestamp("2015-01-01")


def load_hi_cwb() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Hawaii DOH Clean Water Branch public export -> results in ``normalize``'s schema.

    Source: https://eha-cloud.doh.hawaii.gov/cwb/api/sample-test-results/csv?format=csv
    (no auth). Its latitude/longitude columns are swapped on every row; '<' values are
    non-detects, '>' above-range, 'LA'/'INV' are lab-accident/invalid and dropped.
    """
    s = pd.read_csv(HI_CWB / "sample-test-results.csv", encoding="utf-8-sig", low_memory=False, dtype=str)
    e = s[s["Parameter"].eq("Enterococcus")].copy()
    fr = e["Final Result"].fillna("").str.strip()
    flag = fr.str.replace(r"[0-9\.\s]", "", regex=True)
    res = pd.DataFrame({
        "station_id": "CWB-" + e["Station Number"].astype(str),
        "org": "21HI (CWB export)",
        "sample_date": pd.to_datetime(e["Sample Date"], format="%m-%d-%Y", errors="coerce"),
        "value": pd.to_numeric(fr.str.extract(r"([0-9\.]+)")[0], errors="coerce"),
        "nondetect": flag.str.contains("<|ND"), "above_range": flag.str.contains(">"),
        "units": e["Unit of Measure"], "method": e["Method Description"], "assay": "MPN (Enterolert)",
        "flag": flag,
    })
    res["censored"] = res["nondetect"] | res["above_range"]
    res.loc[res["flag"].eq("ND") & res["value"].isna(), "value"] = 0.0
    res = res[~res["flag"].isin(["LA", "INV"]) & res["value"].notna() & res["sample_date"].notna()]
    st = pd.DataFrame({
        "MonitoringLocationIdentifier": "CWB-" + e["Station Number"].astype(str),
        "lat": pd.to_numeric(e["Longitude (decimal degrees)"], errors="coerce"),  # swapped in source
        "lon": pd.to_numeric(e["Latitude (decimal degrees)"], errors="coerce"),
        "name": e["Location Name"],
    }).groupby("MonitoringLocationIdentifier", as_index=False).agg(lat=("lat", "median"), lon=("lon", "median"),
                                                                 name=("name", "first"))
    return res.reset_index(drop=True), st


def analyze_hi_cwb(with_model: bool = True) -> dict:
    """Same coverage numbers on the state's own export, plus a long-history model check.

    The DOH program has 2005-2024 history in its own export, far more than WQP's 2022+ pull,
    so the served model gets a fair test here: refit monthly on 2016+ sample-days and score
    the 36 months to 2024-04 (the last month the program published routine results).
    """
    res, st = load_hi_cwb()
    sd_all = build_sample_days(res, STATE_LIMIT["HI"])
    recent = res[res["sample_date"] >= START]
    fetched = HI_CWB / "fetched_at.txt"
    out = {"source": "https://eha-cloud.doh.hawaii.gov/cwb/api/sample-test-results/csv?format=csv",
           "fetched_at_utc": fetched.read_text().strip() if fetched.exists() else None,
           "results_all_years": int(len(res)), "first_date": str(res["sample_date"].min().date()),
           "results_per_year_all": {int(k): int(v) for k, v in res.groupby(res["sample_date"].dt.year).size().items()},
           "coverage_2022_on": coverage(recent, sd_all[sd_all["sample_date"] >= START], STATE_LIMIT["HI"])}
    if with_model:
        hist = res[res["sample_date"] >= CWB_HISTORY_START]
        sd = build_sample_days(hist, STATE_LIMIT["HI"])
        st = st[st["MonitoringLocationIdentifier"].isin(set(sd["station_id"]))]
        fetch_rain("HI", st, start=str((CWB_HISTORY_START - pd.Timedelta(days=7)).date()), prefix="HIcwb")
        cov = coverage(hist, sd, STATE_LIMIT["HI"])
        out["coverage_2015_on"] = {k: cov[k] for k in
                                   ("sample_days", "positive_sample_days_total", "exceedance_rate_sampleday_state_limit",
                                    "positive_sample_days_per_year")}
        out["model_cwb_36m_to_2024_04"] = walk_forward("HI", sd, st, "cwb", pd.Period("2024-04", "M"), n_months=36,
                                                      history_start=CWB_HISTORY_START, rain_prefix="HIcwb")
    return out


def write_results(state: str, payload: dict) -> None:
    from app.core.json_safe import dumps_strict, json_safe
    path = OUT / "feasibility_results.json"
    allres = json.loads(path.read_text()) if path.exists() else {}
    allres["generated_at"] = pd.Timestamp.now(tz="UTC").isoformat()
    allres["today"] = str(TODAY.date())
    allres[state] = {**allres.get(state, {}), **payload}
    path.write_text(dumps_strict(json_safe(allres), indent=1))
    log(f"wrote {path}")

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["fetch", "rain", "analyze", "hi-cwb"])
    ap.add_argument("--state", choices=list(STATES), required=True)
    ap.add_argument("--no-model", action="store_true", help="Part 1 coverage only")
    args = ap.parse_args()
    if args.stage == "fetch":
        fetch_state(args.state)
    elif args.stage == "rain":
        if not (OUT / f"{args.state}_stations_kept.parquet").exists():
            prepare(args.state)
        # rain is only needed on training/scored rows (>= START + 365 d); HI was cached from 2021-12-25
        fetch_rain(args.state, start=str((START + pd.Timedelta(days=358)).date()))
    elif args.stage == "hi-cwb":
        write_results("HI", {"state_feed_cwb": analyze_hi_cwb(with_model=not args.no_model)})
    else:
        write_results(args.state, analyze(args.state, with_model=not args.no_model))


if __name__ == "__main__":
    sys.exit(main())
