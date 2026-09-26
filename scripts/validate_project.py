"""Check dataset integrity, calculations, notebook execution and PBIR schemas."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import nbformat
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def validate_data():
    fact = pd.read_csv(ROOT / "data/processed/ev_stations_clean.csv", low_memory=False)
    encoded = pd.read_csv(ROOT / "data/processed/station_features_encoded.csv", low_memory=False)
    state = pd.read_csv(ROOT / "data/processed/state_summary.csv")
    assert fact.station_id.notna().all() and fact.station_id.is_unique
    assert state.state_abbr.is_unique and state.population_2025.gt(0).all()
    assert set(fact.state_abbr) <= set(state.state_abbr)
    assert len(state) == 52
    assert fact.status_label.isin(["Available", "Planned", "Temporarily unavailable"]).all()
    assert fact.access_label.isin(["Public", "Private"]).all()
    assert fact.total_ports.ge(0).all()
    expected_score = (fact.is_public * 30 + fact.is_available * 30 + fact.has_dc_fast * 25
                      + fact.has_four_or_more_ports * 10 + fact.pricing_listed * 5)
    np.testing.assert_array_equal(fact.readiness_score, expected_score)
    assert state.total_stations.sum() == len(fact)
    assert encoded.shape[0] == len(fact)
    assert encoded.station_id.is_unique
    assert not encoded.isna().any().any()
    encoded_dummy = encoded.filter(regex=r"^(access_label|status_label|facility_type_label|readiness_band)_")
    assert encoded_dummy.shape[1] > 0
    assert set(encoded_dummy.stack().unique()) <= {0, 1}
    assert state.public_available_stations.sum() == fact.is_public_available.sum()
    grouped = fact.groupby("state_abbr").agg(n=("station_id", "size"), a=("is_available", "sum"), p=("is_public_available", "sum"))
    merged = state.merge(grouped, on="state_abbr", validate="one_to_one")
    np.testing.assert_allclose(merged.availability_rate, merged.a / merged.n)
    np.testing.assert_allclose(merged.public_available_per_100k, merged.p / merged.population_2025 * 100000)
    median = state.public_available_per_100k.median()
    expected_priority = (0.7 * (median - state.public_available_per_100k).clip(lower=0) / median * 100
                         + 0.3 * (1 - state.availability_rate) * 100).round(1)
    np.testing.assert_allclose(state.priority_score, expected_priority)
    meta = json.loads((ROOT / "data/raw/source_metadata.json").read_text())
    assert fact.extracted_at_utc.eq(meta["downloaded_at_utc"]).all()
    notebook = nbformat.read(ROOT / "notebooks/ev_charging_preprocessing.ipynb", 4)
    code = [cell for cell in notebook.cells if cell.cell_type == "code"]
    assert all(cell.execution_count is not None for cell in code)
    assert [cell.execution_count for cell in code] == list(range(1, len(code) + 1))
    assert not [out for cell in code for out in cell.outputs if out.output_type == "error"]
    print(f"PASS: {len(fact):,} stations, 52 jurisdictions; keys, joins, rates, scores and source timestamp.")
    print(f"PASS: one-hot analysis matrix has {encoded.shape[0]:,} rows and {encoded.shape[1]:,} columns.")
    print(f"PASS: all {len(code)} notebook code cells executed in sequence, without errors.")


def validate_schemas():
    import requests
    import jsonschema
    import warnings
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    cache = {}

    def retrieve(uri):
        if uri not in cache:
            response = requests.get(uri, timeout=30)
            response.raise_for_status()
            cache[uri] = response.json()
            # Some Microsoft embedded schemas use a canonical $id that differs
            # from their download URL. Register both names for relative refs.
            canonical = cache[uri].get("$id")
            if canonical:
                cache[canonical] = cache[uri]
        return cache[uri]

    checked = 0
    unavailable = set()
    for folder in [ROOT / "power_bi/EVChargingReadiness.Report", ROOT / "power_bi/EVChargingReadiness.SemanticModel"]:
        for path in folder.rglob("*"):
            if not path.is_file() or ".pbi" in path.parts:
                continue
            if path.suffix not in [".json", ".pbir", ".pbism"]:
                continue
            document = json.loads(path.read_text(encoding="utf-8-sig"))
            uri = document.get("$schema")
            if not uri:
                continue
            if uri in unavailable:
                continue
            try:
                schema = retrieve(uri)
            except requests.HTTPError as exc:
                if exc.response.status_code == 404:
                    # Desktop can emit a newer schema before Microsoft publishes it.
                    # Do not pretend these files were schema-validated.
                    unavailable.add(uri)
                    continue
                raise
            resolver = jsonschema.RefResolver(uri, schema, handlers={"https": retrieve})
            validator = jsonschema.validators.validator_for(schema)(schema, resolver=resolver)
            errors = list(validator.iter_errors(document))
            if errors:
                raise AssertionError(f"{path.relative_to(ROOT)}: " + "\n".join(e.message for e in errors))
            checked += 1
    print(f"PASS: {checked} Power BI definition files match their Microsoft JSON schemas.")
    for uri in sorted(unavailable):
        print(f"UNAVAILABLE: Microsoft has not published {uri}; validate these definitions in Desktop.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--schemas", action="store_true", help="Also fetch and validate Microsoft report schemas.")
    args = parser.parse_args()
    validate_data()
    if args.schemas:
        validate_schemas()
