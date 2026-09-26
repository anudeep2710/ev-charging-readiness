"""Clean the source data, calculate metrics, and create Power BI tables."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
FIGURES_DIR = PROJECT_ROOT / "outputs" / "figures"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
FIGURES_DIR.mkdir(parents=True, exist_ok=True)

STATE_FIPS_TO_ABBR = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA",
    "08": "CO", "09": "CT", "10": "DE", "11": "DC", "12": "FL",
    "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN",
    "19": "IA", "20": "KS", "21": "KY", "22": "LA", "23": "ME",
    "24": "MD", "25": "MA", "26": "MI", "27": "MN", "28": "MS",
    "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
    "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND",
    "39": "OH", "40": "OK", "41": "OR", "42": "PA", "44": "RI",
    "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT",
    "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI",
    "56": "WY", "72": "PR",
}

STATUS_LABELS = {
    "E": "Available",
    "P": "Planned",
    "T": "Temporarily unavailable",
}
ACCESS_LABELS = {
    "public": "Public",
    "private": "Private",
}


def text_value(value: object, default: str = "Not reported") -> str:
    """Turn NREL scalar/list fields into stable text for Power BI."""

    if value is None:
        return default
    if isinstance(value, float) and math.isnan(value):
        return default
    if isinstance(value, list):
        values = [str(item).strip() for item in value if str(item).strip()]
        return "; ".join(values) if values else default
    value_as_text = str(value).strip()
    return value_as_text if value_as_text else default


def numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    """Read an optional numeric source field and replace missing counts with 0."""

    if column not in frame.columns:
        return pd.Series(0, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce").fillna(0)


def numeric_series_alias(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
    """Use the first available name when an API field has changed over time."""

    for column in columns:
        if column in frame.columns:
            return numeric_series(frame, column)
    return pd.Series(0, index=frame.index, dtype="float64")


def text_series(frame: pd.DataFrame, column: str, default: str = "Not reported") -> pd.Series:
    """Read an optional text/list source field and normalize missing values."""

    if column not in frame.columns:
        return pd.Series(default, index=frame.index, dtype="string")
    return frame[column].map(lambda value: text_value(value, default)).astype("string")


def percentile_rank(series: pd.Series) -> pd.Series:
    """Return a 0-100 percentile rank with a stable value for one row."""

    if series.nunique(dropna=True) <= 1:
        return pd.Series(50.0, index=series.index)
    return series.rank(pct=True, method="average") * 100


def load_and_clean_stations() -> tuple[pd.DataFrame, str]:
    raw_payload = json.loads((RAW_DIR / "nrel_ev_stations.json").read_text(encoding="utf-8"))
    stations = pd.DataFrame(raw_payload["fuel_stations"])
    if stations.empty:
        raise RuntimeError("NREL station file is empty.")

    source_metadata = json.loads((RAW_DIR / "source_metadata.json").read_text(encoding="utf-8"))
    extracted_at = source_metadata["downloaded_at_utc"]
    as_of = datetime.fromisoformat(extracted_at).date()
    as_of_year = as_of.year

    stations = stations[stations["fuel_type_code"].eq("ELEC")].copy()
    stations["station_id"] = stations["id"].astype("Int64")
    stations["state_abbr"] = stations["state"].astype("string").str.upper()
    stations["zip5"] = (
        stations["zip"].astype("string").str.extract(r"(\d{5})", expand=False).fillna("Unknown")
    )
    stations["station_name"] = text_series(stations, "station_name")
    stations["city"] = text_series(stations, "city")
    stations["status_code"] = text_series(stations, "status_code", "Unknown")
    stations["status_label"] = stations["status_code"].map(STATUS_LABELS).fillna("Unknown")
    stations["access_code"] = text_series(stations, "access_code", "Unknown").str.lower()
    stations["access_label"] = stations["access_code"].map(ACCESS_LABELS).fillna("Unknown")
    stations["facility_type"] = text_series(stations, "facility_type", "Unknown")
    stations["facility_type_label"] = (
        stations["facility_type"].str.replace("_", " ", regex=False).str.title()
    )
    stations["ev_network"] = text_series(stations, "ev_network", "Non-networked")
    stations["connector_types"] = text_series(stations, "ev_connector_types")
    stations["funding_sources"] = text_series(stations, "funding_sources")
    stations["pricing"] = text_series(stations, "ev_pricing")
    stations["pricing_listed"] = stations["pricing"].ne("Not reported")

    stations["level_1_ports"] = numeric_series(stations, "ev_level1_evse_num")
    stations["level_2_ports"] = numeric_series(stations, "ev_level2_evse_num")
    stations["dc_fast_ports"] = numeric_series_alias(
        stations, ["ev_dc_fast_num", "ev_dc_fast_count"]
    )
    stations["other_ports"] = numeric_series_alias(stations, ["ev_other_evse"])
    stations["total_ports"] = stations[
        ["level_1_ports", "level_2_ports", "dc_fast_ports", "other_ports"]
    ].sum(axis=1)
    stations["dc_fast_share"] = np.where(
        stations["total_ports"] > 0,
        stations["dc_fast_ports"] / stations["total_ports"],
        np.nan,
    )

    stations["latitude"] = pd.to_numeric(stations["latitude"], errors="coerce")
    stations["longitude"] = pd.to_numeric(stations["longitude"], errors="coerce")
    stations["open_date"] = pd.to_datetime(stations["open_date"], errors="coerce")
    stations["open_year"] = stations["open_date"].dt.year.astype("Int64")
    stations["station_age_years"] = (as_of_year - stations["open_year"]).clip(lower=0)
    stations["last_updated_datetime"] = pd.to_datetime(
        stations["updated_at"], errors="coerce", utc=True
    )
    stations["is_public"] = stations["access_code"].eq("public")
    stations["is_available"] = stations["status_code"].eq("E")
    stations["is_public_available"] = stations["is_public"] & stations["is_available"]
    stations["has_dc_fast"] = stations["dc_fast_ports"].gt(0)
    stations["has_four_or_more_ports"] = stations["total_ports"].ge(4)

    # A transparent, portfolio-friendly heuristic. It indicates site readiness,
    # not actual charger uptime or customer satisfaction.
    stations["readiness_score"] = (
        stations["is_public"].astype(int) * 30
        + stations["is_available"].astype(int) * 30
        + stations["has_dc_fast"].astype(int) * 25
        + stations["has_four_or_more_ports"].astype(int) * 10
        + stations["pricing_listed"].astype(int) * 5
    )
    stations["readiness_band"] = pd.cut(
        stations["readiness_score"],
        bins=[-1, 49, 79, 100],
        labels=["Priority review", "Partly ready", "Ready"],
    ).astype("string")
    stations["extracted_at_utc"] = extracted_at

    output_columns = [
        "station_id", "station_name", "street_address", "city", "state_abbr", "zip5",
        "status_code", "status_label", "access_code", "access_label", "facility_type",
        "facility_type_label", "latitude", "longitude", "open_date", "open_year",
        "station_age_years", "last_updated_datetime", "ev_network", "connector_types",
        "funding_sources", "pricing", "pricing_listed", "level_1_ports", "level_2_ports",
        "dc_fast_ports", "other_ports", "total_ports", "dc_fast_share", "is_public", "is_available",
        "is_public_available", "has_dc_fast", "has_four_or_more_ports", "readiness_score",
        "readiness_band", "extracted_at_utc",
    ]
    for column in output_columns:
        if column not in stations.columns:
            stations[column] = pd.NA

    return stations[output_columns].copy(), as_of.isoformat()


def load_population() -> pd.DataFrame:
    population = pd.read_csv(RAW_DIR / "census_state_population_2025.csv", dtype={"STATE": "string"})
    population["SUMLEV"] = population["SUMLEV"].astype("string").str.zfill(3)
    population["STATE"] = population["STATE"].astype("string").str.zfill(2)
    population = population[population["SUMLEV"].eq("040")].copy()
    population["state_abbr"] = population["STATE"].map(STATE_FIPS_TO_ABBR)
    population["population_2025"] = pd.to_numeric(population["POPESTIMATE2025"], errors="coerce")
    population = population[population["state_abbr"].notna()].copy()
    return population[["state_abbr", "NAME", "population_2025"]].rename(
        columns={"NAME": "state_name"}
    )


def create_state_summary(stations: pd.DataFrame, population: pd.DataFrame) -> pd.DataFrame:
    grouped = stations.groupby("state_abbr", dropna=False)
    state = grouped.agg(
        total_stations=("station_id", "nunique"),
        available_stations=("is_available", "sum"),
        public_stations=("is_public", "sum"),
        public_available_stations=("is_public_available", "sum"),
        dc_fast_stations=("has_dc_fast", "sum"),
        total_ports=("total_ports", "sum"),
        dc_fast_ports=("dc_fast_ports", "sum"),
        mean_readiness_score=("readiness_score", "mean"),
        median_station_age_years=("station_age_years", "median"),
    ).reset_index()
    state = population.merge(state, on="state_abbr", how="left")
    numeric_columns = [column for column in state.columns if column not in {"state_abbr", "state_name"}]
    state[numeric_columns] = state[numeric_columns].fillna(0)

    state["availability_rate"] = np.where(
        state["total_stations"] > 0,
        state["available_stations"] / state["total_stations"],
        np.nan,
    )
    state["public_share"] = np.where(
        state["total_stations"] > 0,
        state["public_stations"] / state["total_stations"],
        np.nan,
    )
    state["dc_fast_station_share"] = np.where(
        state["total_stations"] > 0,
        state["dc_fast_stations"] / state["total_stations"],
        np.nan,
    )
    state["stations_per_100k"] = state["total_stations"] / state["population_2025"] * 100_000
    state["public_available_per_100k"] = (
        state["public_available_stations"] / state["population_2025"] * 100_000
    )

    median_density = state["public_available_per_100k"].median()
    if median_density and not np.isnan(median_density):
        state["coverage_gap_pct"] = (
            (median_density - state["public_available_per_100k"]).clip(lower=0)
            / median_density
            * 100
        )
    else:
        state["coverage_gap_pct"] = 0.0
    state["availability_gap_pct"] = (1 - state["availability_rate"]).clip(lower=0) * 100
    state["priority_score"] = (
        state["coverage_gap_pct"] * 0.70 + state["availability_gap_pct"] * 0.30
    ).round(1)
    state["priority_band"] = pd.cut(
        state["priority_score"],
        bins=[-0.01, 25, 50, 1000],
        labels=["Lower priority", "Watch list", "Priority review"],
    ).astype("string")
    state["national_median_public_available_per_100k"] = median_density
    return state.sort_values("priority_score", ascending=False).reset_index(drop=True)


def create_group_summary(stations: pd.DataFrame, group_column: str) -> pd.DataFrame:
    summary = (
        stations.groupby(group_column, dropna=False)
        .agg(
            stations=("station_id", "nunique"),
            available_stations=("is_available", "sum"),
            public_stations=("is_public", "sum"),
            dc_fast_stations=("has_dc_fast", "sum"),
            total_ports=("total_ports", "sum"),
            mean_readiness_score=("readiness_score", "mean"),
        )
        .reset_index()
    )
    summary["availability_rate"] = np.where(
        summary["stations"] > 0,
        summary["available_stations"] / summary["stations"],
        np.nan,
    )
    summary["public_share"] = np.where(
        summary["stations"] > 0,
        summary["public_stations"] / summary["stations"],
        np.nan,
    )
    return summary.sort_values("stations", ascending=False)


def create_year_summary(stations: pd.DataFrame) -> pd.DataFrame:
    year = stations[stations["open_year"].notna()].copy()
    year["open_year"] = year["open_year"].astype(int)
    year = year[year["open_year"].between(1990, datetime.now().year + 1)]
    summary = (
        year.groupby("open_year")
        .agg(
            new_stations=("station_id", "nunique"),
            public_stations=("is_public", "sum"),
            available_stations=("is_available", "sum"),
            dc_fast_stations=("has_dc_fast", "sum"),
        )
        .reset_index()
    )
    return summary.sort_values("open_year")


def create_dimensions(
    stations: pd.DataFrame, population: pd.DataFrame
) -> dict[str, pd.DataFrame]:
    """Create small dimension tables for a clean Power BI star schema."""

    dim_state = population[["state_abbr", "state_name"]].drop_duplicates().sort_values("state_abbr")
    dim_network = (
        stations[["ev_network"]]
        .drop_duplicates()
        .sort_values("ev_network")
        .reset_index(drop=True)
    )
    dim_facility = (
        stations[["facility_type", "facility_type_label"]]
        .drop_duplicates()
        .sort_values("facility_type_label")
        .reset_index(drop=True)
    )
    years = stations["open_year"].dropna().astype(int).drop_duplicates().sort_values()
    dim_year = pd.DataFrame({"open_year": years})
    dim_year["year_label"] = dim_year["open_year"].astype(str)
    return {
        "dim_state": dim_state.reset_index(drop=True),
        "dim_network": dim_network,
        "dim_facility": dim_facility,
        "dim_year": dim_year.reset_index(drop=True),
    }


def create_encoded_features(stations: pd.DataFrame) -> pd.DataFrame:
    """Create a compact, analysis-ready feature matrix with one-hot categories.

    The Power BI fact table stays human-readable. This separate matrix is for
    exploratory analysis or a future predictive model, so categorical labels
    are encoded without turning the reporting table into opaque dummy fields.
    Numeric missing values retain a flag and use the training-safe median.
    """

    numeric_columns = [
        "latitude", "longitude", "station_age_years", "level_1_ports",
        "level_2_ports", "dc_fast_ports", "other_ports", "total_ports",
        "dc_fast_share", "readiness_score",
    ]
    boolean_columns = [
        "is_public", "is_available", "has_dc_fast", "has_four_or_more_ports",
        "pricing_listed",
    ]
    categorical_columns = [
        "access_label", "status_label", "facility_type_label", "readiness_band",
    ]

    features = pd.DataFrame({"station_id": stations["station_id"].astype("int64")}).reset_index(drop=True)
    for column in numeric_columns:
        values = pd.to_numeric(stations[column], errors="coerce")
        features[f"{column}_missing"] = values.isna().astype("int8")
        fill_value = values.median()
        features[column] = values.fillna(0 if pd.isna(fill_value) else fill_value)
    for column in boolean_columns:
        features[column] = stations[column].fillna(False).astype("int8")

    categorical = stations[categorical_columns].copy().fillna("Not reported").astype("string")
    encoded = pd.get_dummies(
        categorical,
        columns=categorical_columns,
        prefix=categorical_columns,
        dtype="int8",
    )
    return pd.concat([features, encoded.reset_index(drop=True)], axis=1)


def write_data_dictionary() -> None:
    dictionary = pd.DataFrame(
        [
            ("station_id", "Unique NREL station identifier", "NREL"),
            ("status_label", "Available, Planned, Temporarily unavailable, or Unknown", "NREL status_code"),
            ("access_label", "Public, Private, or Unknown access", "NREL access_code"),
            ("public_available_stations", "Stations that are both public and currently available", "Derived"),
            ("public_available_per_100k", "Public-and-available stations per 100,000 residents", "Derived + Census"),
            ("availability_rate", "Available stations divided by all stations in the group", "Derived"),
            ("dc_fast_station_share", "Stations with at least one DC fast port divided by all stations", "Derived"),
            ("readiness_score", "Transparent 0-100 heuristic using access, status, DC fast, port count, and pricing", "Derived"),
            ("priority_score", "70% coverage shortfall versus the jurisdiction median plus 30% share not marked available", "Derived"),
        ],
        columns=["field", "definition", "source_or_transform"],
    )
    dictionary.to_csv(PROCESSED_DIR / "data_dictionary.csv", index=False)


def make_figures(stations: pd.DataFrame, state: pd.DataFrame, year: pd.DataFrame) -> None:
    sns.set_theme(style="whitegrid", palette="viridis")
    plot_state = state.copy()
    for column in [
        "public_available_per_100k",
        "availability_rate",
        "population_2025",
        "priority_score",
    ]:
        plot_state[column] = pd.to_numeric(plot_state[column], errors="coerce").astype(float)

    top = plot_state.nlargest(15, "public_available_per_100k").sort_values("public_available_per_100k")
    fig, ax = plt.subplots(figsize=(10, 7))
    sns.barplot(
        data=top,
        x="public_available_per_100k",
        y="state_abbr",
        hue="state_abbr",
        legend=False,
        ax=ax,
    )
    ax.set_title("Top states by public-and-available EV stations per 100,000 residents")
    ax.set_xlabel("Stations per 100,000 residents")
    ax.set_ylabel("State")
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "top_state_coverage.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 7))
    sns.scatterplot(
        data=plot_state,
        x="public_available_per_100k",
        y="availability_rate",
        size="population_2025",
        hue="priority_score",
        palette="magma",
        sizes=(50, 900),
        alpha=0.85,
        ax=ax,
    )
    for _, row in plot_state.nlargest(8, "priority_score").iterrows():
        ax.annotate(row["state_abbr"], (row["public_available_per_100k"], row["availability_rate"]), fontsize=8)
    ax.set_title("Coverage and availability trade-off by state")
    ax.set_xlabel("Public-and-available stations per 100,000 residents")
    ax.set_ylabel("Availability rate")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda value, _: f"{value:.0%}"))
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "coverage_vs_availability.png", dpi=160)
    plt.close(fig)

    readiness = stations["readiness_band"].value_counts().reindex(
        ["Ready", "Partly ready", "Priority review"], fill_value=0
    )
    fig, ax = plt.subplots(figsize=(8, 5))
    readiness.plot(kind="bar", color=["#2a9d8f", "#e9c46a", "#e76f51"], ax=ax)
    ax.set_title("Station service-readiness mix")
    ax.set_xlabel("")
    ax.set_ylabel("Stations")
    ax.tick_params(axis="x", rotation=0)
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "readiness_mix.png", dpi=160)
    plt.close(fig)

    if not year.empty:
        fig, ax = plt.subplots(figsize=(11, 5))
        sns.lineplot(data=year, x="open_year", y="new_stations", marker="o", color="#264653", ax=ax)
        ax.set_title("Stations by reported opening year")
        ax.set_xlabel("Opening year")
        ax.set_ylabel("Stations in current inventory")
        fig.tight_layout()
        fig.savefig(FIGURES_DIR / "stations_by_open_year.png", dpi=160)
        plt.close(fig)


def main() -> None:
    stations, as_of = load_and_clean_stations()
    population = load_population()
    state = create_state_summary(stations, population)
    network = create_group_summary(stations, "ev_network")
    facility = create_group_summary(stations, "facility_type_label")
    year = create_year_summary(stations)
    dimensions = create_dimensions(stations, population)

    stations.to_csv(PROCESSED_DIR / "ev_stations_clean.csv", index=False)
    state.to_csv(PROCESSED_DIR / "state_summary.csv", index=False)
    network.to_csv(PROCESSED_DIR / "network_summary.csv", index=False)
    facility.to_csv(PROCESSED_DIR / "facility_summary.csv", index=False)
    year.to_csv(PROCESSED_DIR / "open_year_summary.csv", index=False)
    create_encoded_features(stations).to_csv(
        PROCESSED_DIR / "station_features_encoded.csv", index=False
    )
    for name, dimension in dimensions.items():
        dimension.to_csv(PROCESSED_DIR / f"{name}.csv", index=False)
    write_data_dictionary()
    make_figures(stations, state, year)

    quality = pd.DataFrame(
        [
            ("extract_date", as_of),
            ("station_rows", len(stations)),
            ("state_rows", len(state)),
            ("missing_latitude_pct", stations["latitude"].isna().mean()),
            ("missing_longitude_pct", stations["longitude"].isna().mean()),
            ("missing_total_ports_pct", stations["total_ports"].eq(0).mean()),
            ("unknown_access_pct", stations["access_label"].eq("Unknown").mean()),
            ("unknown_status_pct", stations["status_label"].eq("Unknown").mean()),
        ],
        columns=["metric", "value"],
    )
    quality.to_csv(PROCESSED_DIR / "quality_report.csv", index=False)

    print(f"Prepared {len(stations):,} station rows and {len(state):,} state rows.")
    print(f"Power BI tables: {PROCESSED_DIR}")


if __name__ == "__main__":
    main()
