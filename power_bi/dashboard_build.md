# Power BI build guide

## Load the data

In Power BI Desktop, use **Get data → Text/CSV** and load these tables from `data/processed/`:

- `ev_stations_clean.csv` — station-level detail
- `state_summary.csv` — state-level metrics and population denominator
- `network_summary.csv` — network comparison
- `facility_summary.csv` — site/facility comparison
- `open_year_summary.csv` — station opening trend
- `dim_state.csv`, `dim_network.csv`, `dim_facility.csv`, `dim_year.csv` — small dimensions for slicers and relationships

The summary tables are already aggregated for simple, reliable visuals. The station table is the detail table for slicers and drill-through.

## Recommended relationships

Use the generated dimensions to keep the model close to a star schema. Create these single-direction relationships:

- `dim_state[state_abbr]` → `ev_stations_clean[state_abbr]`
- `dim_state[state_abbr]` → `state_summary[state_abbr]`
- `dim_network[ev_network]` → `ev_stations_clean[ev_network]`
- `dim_network[ev_network]` → `network_summary[ev_network]`
- `dim_facility[facility_type]` → `ev_stations_clean[facility_type]`
- `dim_facility[facility_type_label]` → `facility_summary[facility_type_label]`
- `dim_year[open_year]` → `ev_stations_clean[open_year]`
- `dim_year[open_year]` → `open_year_summary[open_year]`

Do not relate the summary tables directly to each other.

## Page 1 — Executive overview

Add four Card visuals:

- `Total Stations` = count of `ev_stations_clean[station_id]`
- `Public Share`
- `Availability Rate`
- `DC Fast Station Share`

Add these visuals:

1. Clustered bar: `state_summary[state_abbr]` by `public_available_per_100k`, sorted descending.
2. Donut: `ev_stations_clean[readiness_band]` by count of `station_id`.
3. Line chart: `open_year_summary[open_year]` by `new_stations`.
4. Slicers: `state_abbr`, `access_label`, `status_label`, `ev_network`.

## Page 2 — Where is coverage weak?

Use `state_summary`.

1. Scatter chart:
   - X-axis: `public_available_per_100k`
   - Y-axis: `availability_rate`
   - Size: `population_2025`
   - Legend or color: `priority_band`
   - Details: `state_abbr`
2. Table:
   - `state_abbr`, `population_2025`, `public_available_per_100k`, `availability_rate`, `dc_fast_station_share`, `priority_score`, `priority_band`
   - Conditional formatting on `priority_score`.
3. Filled map or Azure Maps: state location using `state_abbr`, color by `priority_score`.

Call out the limitation in a text box: “State is the first-pass planning geography; county/ZIP analysis is a recommended next step.”

## Page 3 — What drives readiness?

1. Bar chart: `facility_summary[facility_type_label]` by `stations`, with `availability_rate` in tooltips.
2. Bar chart: `network_summary[ev_network]` by `stations`, filtered to top networks.
3. 100% stacked bar: `access_label` by `status_label` using the station table.
4. Table for station drill-through: name, city, state, status, access, network, total ports, DC fast ports, readiness score.

## DAX measures

```DAX
Total Stations = DISTINCTCOUNT(ev_stations_clean[station_id])

Public Stations =
CALCULATE(
    [Total Stations],
    ev_stations_clean[is_public] = TRUE()
)

Available Stations =
CALCULATE(
    [Total Stations],
    ev_stations_clean[is_available] = TRUE()
)

Public Available Stations =
CALCULATE(
    [Total Stations],
    ev_stations_clean[is_public_available] = TRUE()
)

Public Share = DIVIDE([Public Stations], [Total Stations])

Availability Rate = DIVIDE([Available Stations], [Total Stations])

DC Fast Station Share =
DIVIDE(
    CALCULATE([Total Stations], ev_stations_clean[has_dc_fast] = TRUE()),
    [Total Stations]
)

Average Readiness Score = AVERAGE(ev_stations_clean[readiness_score])
```

## Dashboard design choices

- Use a dark navy background, teal for healthy/available, amber for watch-list states, and coral for priority review.
- Format rates as percentages and per-capita metrics to two decimals.
- Keep the priority score labeled as a “screening heuristic.” Do not present it as a forecast.
- Use tooltips to show station counts behind every rate.
