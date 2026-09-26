# Report and model guide

## Open the report

Use `EVChargingReadiness.pbix` for the saved, populated report. Use `EVChargingReadiness.pbip` for the editable source. Power BI Desktop is required; no Power BI Service account is needed for local use.

On another computer, update **Transform data → Edit parameters → ProjectRoot** to the repository's absolute path before refreshing. Or run `python scripts/build_powerbi.py` to regenerate the project with its local path.

Keep the `.Report` and `.SemanticModel` folders alongside the PBIP. Local `.pbi` cache folders are ignored by Git.

## Model

```text
Geography [state_abbr]  1 ───▶ *  Stations [state_abbr]
  52 jurisdictions                 89,394 station locations
  Census population                access, status, network, ports
  fixed snapshot aggregates        readiness, reported opening year
```

Filtering is single-direction from Geography to Stations. Every overview chart uses the station fact table so jurisdiction and access selections reach the same records. There are no disconnected facility/year summary charts.

Supplementary summary CSVs support Python checks but are not separate reporting facts. Jurisdiction snapshot measures read Geography deliberately; they are used on the coverage-priority page, where only jurisdiction selection is offered.

## Pages

**01 Network overview:** five KPI cards, opening-year cohorts split by access, readiness donut, jurisdiction table, six largest network footprints and a missing-facility KPI. Use the dropdowns or click chart marks. Click a selected mark again to clear it. Slicer selections apply to that page.

**02 Coverage priorities:** weighted coverage, fixed median benchmark, below-median count, top-eight priorities, coverage leaders and a sortable shortlist. Cross-filtering changes the selected geography, not the benchmark or source score.

Both pages use native visuals with pale-blue backgrounds, rounded white containers and teal accents. Text notes are methodological guidance, not dynamic findings.

## Important DAX patterns

```DAX
Total Stations = COALESCE(DISTINCTCOUNT(Stations[station_id]), 0)

Public Available Stations =
CALCULATE(
    [Total Stations],
    KEEPFILTERS(Stations[is_public_available] = TRUE())
)

Coverage per 100k =
DIVIDE(
    [Public Available Stations] * 100000,
    SUM(Geography[population_2025])
)

Availability Rate =
DIVIDE(
    CALCULATE([Total Stations], KEEPFILTERS(Stations[is_available] = TRUE())),
    [Total Stations]
)

Snapshot Priority =
IF(
    HASONEVALUE(Geography[state_abbr]),
    MAX(Geography[priority_score])
)
```

`KEEPFILTERS` intersects the numerator with existing selections. Priority is blank at a multi-jurisdiction total because adding or averaging scores would not answer the question. Per-capita totals use summed counts and summed population.

Complete measure definitions and descriptions are in `EVChargingReadiness.SemanticModel/definition/tables/Stations.tmdl`.

## Validation and editing

- Run `python scripts/validate_project.py` for keys, joins, score formulas, aggregate reconciliations and notebook execution.
- Add `--schemas` to check definitions against Microsoft's published schemas; internet is required. Desktop may save a newer schema before Microsoft publishes it. The validator reports those files as unavailable, not passed; opening and testing the report in Desktop remains necessary.
- Refresh in Desktop and compare unfiltered and California-filtered results with the processed CSV.
- Actual report screenshots are in `outputs/dashboards/`; supplementary Python figures are separate.

To redesign through code, edit `scripts/build_powerbi.py` and regenerate with Desktop closed. To retain manual visual changes, do not regenerate over them—edit/save the project directly instead.

## Verification record

Validated on September 26, 2026 against the September 20 source snapshot:

- All 11 notebook code cells executed in order, with saved outputs and no errors.
- 89,394 station IDs and all 52 jurisdiction joins, score formulas and aggregate reconciliations passed.
- 312 live DAX results (52 jurisdictions × six metrics) matched the Python tables. National weighted coverage, blank priority totals and public/private filter intersections also passed.
- 26 definition files passed their published Microsoft JSON schemas. The Desktop-emitted visual-container 2.12.0 schema was not yet available at its public URL; those files were checked by opening the report in Desktop, not certified by the schema validator.

The read-only `scripts/validate_powerbi.ps1 -Port <local-model-port>` check compares an open Desktop model to the processed CSV. The local model port changes when Desktop restarts.
