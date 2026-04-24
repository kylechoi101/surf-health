from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from app.data.connectors.base import SourceConnector, SourceContext

CEDEN_FIB_RESULTS_2020_PRESENT_URL = (
    "https://data.ca.gov/dataset/6723ab78-4530-4e97-ba5e-6ffd17a4c139/resource/"
    "15a63495-8d9f-4a49-b43a-3092ef3106b9/download/safetoswim_geomeans_2020-present.csv"
)
CEDEN_FIB_RESULTS_2020_PRESENT_RESOURCE_ID = "15a63495-8d9f-4a49-b43a-3092ef3106b9"
CEDEN_FIB_RESULTS_2010_2020_URL = (
    "https://data.ca.gov/dataset/6723ab78-4530-4e97-ba5e-6ffd17a4c139/resource/"
    "04d98c22-5523-4cc1-86e7-3a6abf40bb60/download/safetoswim_geomeans_2010-2020.csv"
)
CEDEN_FIB_RESULTS_2010_2020_RESOURCE_ID = "04d98c22-5523-4cc1-86e7-3a6abf40bb60"
CEDEN_FIB_RESULTS_BEFORE_2010_URL = (
    "https://data.ca.gov/dataset/6723ab78-4530-4e97-ba5e-6ffd17a4c139/resource/"
    "1d333989-559a-433f-b93f-bb43d21da2b9/download/safetoswim_geomeans_before-2010.csv"
)
CEDEN_FIB_RESULTS_BEFORE_2010_RESOURCE_ID = "1d333989-559a-433f-b93f-bb43d21da2b9"
CEDEN_FIB_SITES_URL = (
    "https://data.ca.gov/dataset/6723ab78-4530-4e97-ba5e-6ffd17a4c139/resource/"
    "848d2e3f-2846-449c-90e0-9aaf5c45853e/download/safetoswim_sites_2025-03-25.csv"
)
CEDEN_FIB_SITES_FILENAME = "ceden_fib_monitoring_sites_for_safe_to_swim_no_longer_updated.csv"


def _safe_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _parquet_safe_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    normalized = frame.copy()
    for column in normalized.columns:
        if normalized[column].map(lambda value: isinstance(value, (list, dict))).any():
            normalized[column] = normalized[column].map(
                lambda value: json.dumps(value) if isinstance(value, (list, dict)) else value
            )
    return normalized


def _resource_slug(name: str) -> str:
    return (
        name.lower()
        .replace(" - ", "_")
        .replace(" ", "_")
        .replace("/", "_")
        .replace("(", "")
        .replace(")", "")
        .replace(",", "")
    )


@dataclass
class CaliforniaOpenDataConnector(SourceConnector):
    dataset_slug: str
    source_name: str = "ca_open_data"

    async def fetch(self, context: SourceContext) -> pd.DataFrame:
        context.raw_dir.mkdir(parents=True, exist_ok=True)
        url = f"https://data.ca.gov/api/3/action/package_search?q={self.dataset_slug}"
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url)
            response.raise_for_status()
        payload = response.json()
        results = payload.get("result", {}).get("results", [])
        frame = _safe_frame(results)
        if not frame.empty:
            _parquet_safe_frame(frame).to_parquet(
                context.raw_dir / f"{self.source_name}_packages.parquet",
                index=False,
            )
        return frame


@dataclass
class CaliforniaOpenDataPackageConnector(SourceConnector):
    dataset_slug: str
    source_name: str

    async def _package_payload(self) -> dict[str, Any]:
        url = f"https://data.ca.gov/api/3/action/package_show?id={self.dataset_slug}"
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
        payload = response.json()
        return payload.get("result", {})

    async def fetch(self, context: SourceContext) -> pd.DataFrame:
        context.raw_dir.mkdir(parents=True, exist_ok=True)
        payload = await self._package_payload()
        resources = payload.get("resources", [])
        frame = _safe_frame(resources)
        manifest = {
            "id": payload.get("id"),
            "name": payload.get("name"),
            "title": payload.get("title"),
            "metadata_modified": payload.get("metadata_modified"),
            "resources": resources,
        }
        (context.raw_dir / f"{self.source_name}_package.json").write_text(json.dumps(manifest, indent=2))
        if not frame.empty:
            _parquet_safe_frame(frame).to_parquet(
                context.raw_dir / f"{self.source_name}_resources.parquet",
                index=False,
            )
        return frame


@dataclass
class CedenFibConnector(CaliforniaOpenDataPackageConnector):
    dataset_slug: str
    source_name: str = "ceden_fib"
    max_auto_download_bytes: int = 2_000_000

    async def _download_resource(
        self,
        client: httpx.AsyncClient,
        url: str,
        destination: Path,
    ) -> None:
        response = await client.get(url, timeout=60.0)
        response.raise_for_status()
        destination.write_bytes(response.content)

    async def fetch(self, context: SourceContext) -> pd.DataFrame:
        frame = await super().fetch(context)
        if frame.empty:
            return frame

        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            for _, row in frame.iterrows():
                resource_name = str(row.get("name") or "")
                url = row.get("url")
                size = row.get("size")
                if not isinstance(url, str) or not url:
                    continue
                if not resource_name.lower().startswith("monitoring sites for safe to swim"):
                    continue
                if pd.notna(size) and int(size) > self.max_auto_download_bytes:
                    continue
                destination = context.raw_dir / f"{self.source_name}_{_resource_slug(resource_name)}.csv"
                await self._download_resource(client, url, destination)
        return frame


@dataclass
class JsonEndpointConnector(SourceConnector):
    source_name: str
    url: str

    async def fetch(self, context: SourceContext) -> pd.DataFrame:
        context.raw_dir.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(self.url)
            response.raise_for_status()
        payload = response.json()
        rows = payload if isinstance(payload, list) else payload.get("results", payload)
        if isinstance(rows, dict):
            rows = [rows]
        frame = _safe_frame(rows)
        if not frame.empty:
            frame.to_parquet(context.raw_dir / f"{self.source_name}.parquet", index=False)
        return frame


def default_connectors(dataset_slug: str, ceden_fib_dataset_slug: str) -> list[SourceConnector]:
    return [
        CaliforniaOpenDataConnector(dataset_slug=dataset_slug),
        CedenFibConnector(dataset_slug=ceden_fib_dataset_slug),
        JsonEndpointConnector(
            source_name="epa_uv",
            url="https://data.epa.gov/efservice/getEnvirofactsUVDAILY/ZIP/92037/JSON",
        ),
    ]
