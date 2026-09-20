"""Download the public source datasets used by the EV charging project."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

# The official NREL hostname may be unavailable in some local DNS environments.
# The second hostname is the working NREL Developer Network endpoint used by the
# browser/docs environment; the script tries the official hostname first.
NREL_ENDPOINTS = [
    "https://developer.nrel.gov/api/alt-fuel-stations/v1.json",
    "https://developer.nlr.gov/api/alt-fuel-stations/v1.json",
]
POPULATION_URL = (
    "https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/"
    "state/totals/NST-EST2025-ALLDATA.csv"
)


def download_nrel_stations() -> tuple[dict, str]:
    """Download all U.S. electric charging stations from the NREL API."""

    api_key = os.getenv("NREL_API_KEY", "DEMO_KEY")
    params = {
        "api_key": api_key,
        "country": "US",
        "fuel_type": "ELEC",
        "status": "all",
        "access": "all",
        "limit": "all",
    }
    errors: list[str] = []

    for endpoint in NREL_ENDPOINTS:
        try:
            response = requests.get(endpoint, params=params, timeout=180)
            response.raise_for_status()
            payload = response.json()
            stations = payload.get("fuel_stations", [])
            if len(stations) < 1_000:
                raise RuntimeError(
                    f"The response contained only {len(stations):,} records;"
                    " refusing to save a likely partial response."
                )

            output_path = RAW_DIR / "nrel_ev_stations.json"
            output_path.write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
            return payload, endpoint
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            errors.append(f"{endpoint}: {exc}")

    raise RuntimeError("NREL download failed:\n" + "\n".join(errors))


def download_population() -> None:
    """Download Census Vintage 2025 state population estimates."""

    response = requests.get(POPULATION_URL, timeout=60)
    response.raise_for_status()
    (RAW_DIR / "census_state_population_2025.csv").write_bytes(response.content)


def main() -> None:
    payload, endpoint = download_nrel_stations()
    download_population()

    metadata = {
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "nrel_endpoint_used": endpoint,
        "nrel_total_results": payload.get("total_results"),
        "nrel_records_saved": len(payload.get("fuel_stations", [])),
        "nrel_source_url": "https://developer.nrel.gov/docs/transportation/alt-fuel-stations-v1/all/",
        "census_source_url": "https://www.census.gov/data/datasets/time-series/demo/popest/2020s-state-total.html",
        "population_file": POPULATION_URL,
    }
    (RAW_DIR / "source_metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )

    print(
        f"Downloaded {metadata['nrel_records_saved']:,} NREL station records "
        f"and the Census population file."
    )
    print(f"Source metadata: {RAW_DIR / 'source_metadata.json'}")


if __name__ == "__main__":
    main()
