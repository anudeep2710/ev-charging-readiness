"""Build the editable Power BI project from the processed snapshot.

The output uses Microsoft's PBIP, PBIR and TMDL text formats. Open the PBIP
in Desktop, refresh, and save to populate its local data cache.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BI = ROOT / "power_bi"
REPORT = BI / "EVChargingReadiness.Report"
MODEL = BI / "EVChargingReadiness.SemanticModel"
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/"
INK, MUTED, TEAL, BLUE, PALE = "#173C48", "#5E7780", "#167E91", "#87BAC8", "#E5F3F7"


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, indent=2, ensure_ascii=False) if isinstance(value, dict) else value
    path.write_text(text + "\n", encoding="utf-8")


def ident(text):
    return hashlib.sha1(text.encode()).hexdigest()[:20]


def lit(value):
    if isinstance(value, bool):
        value = str(value).lower()
    elif isinstance(value, (int, float)):
        value = str(value) + "D"
    else:
        value = "'" + value.replace("'", "''") + "'"
    return {"expr": {"Literal": {"Value": value}}}


def color(value):
    return {"solid": {"color": lit(value)}}


def props(**kwargs):
    return [{"properties": kwargs}]


def field(table, name, measure=False):
    return {"Measure" if measure else "Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": name}}


def projection(table, name, measure=False, label=None):
    p = {"field": field(table, name, measure), "queryRef": f"{table}.{name}", "nativeQueryRef": label or name}
    if label:
        p["displayName"] = label
    return p


def container(title=None, subtitle=None, background=True):
    result = {
        "background": props(show=lit(background), color=color("#FFFFFF"), transparency=lit(0)),
        "border": props(show=lit(background), color=color("#D6EBF0"), radius=lit(16), width=lit(1)),
        "dropShadow": props(show=lit(background), color=color("#719BA8"), position=lit("Outer"), preset=lit("BottomRight"), transparency=lit(88), angle=lit(90)),
        "visualHeader": props(show=lit(False)),
        "padding": props(top=lit(12), bottom=lit(12), left=lit(14), right=lit(14)),
        "title": props(show=lit(bool(title)), text=lit(title or ""), fontColor=color(INK), fontSize=lit(12), fontFamily=lit("Segoe UI Semibold"), alignment=lit("left")),
    }
    if subtitle:
        result["subTitle"] = props(show=lit(True), text=lit(subtitle), fontColor=color(MUTED), fontSize=lit(9))
    return result


def visual(page, key, kind, box, roles=None, title=None, subtitle=None, objects=None, background=True, sort=None):
    name = ident(page + key)
    x, y, width, height = box
    v = {"visualType": kind, "visualContainerObjects": container(title, subtitle, background), "drillFilterOtherVisuals": True}
    if roles:
        v["query"] = {"queryState": {role: {"projections": values} for role, values in roles.items()}}
        if sort:
            v["query"]["sortDefinition"] = {"sort": [{"field": sort[0], "direction": sort[1]}], "isDefaultSort": True}
    if objects:
        v["objects"] = objects
    doc = {"$schema": SCHEMA + "item/report/definition/visualContainer/2.7.0/schema.json", "name": name,
           "position": {"x": x, "y": y, "z": 1000 + len(VISUALS[page]), "width": width, "height": height, "tabOrder": len(VISUALS[page])}, "visual": v}
    VISUALS[page].append(name)
    write(REPORT / "definition/pages" / ident(page) / "visuals" / name / "visual.json", doc)
    return doc


def text_box(page, key, box, lines, background=False):
    paragraphs = []
    for text, size, bold, shade in lines:
        paragraphs.append({"textRuns": [{"value": text, "textStyle": {"fontFamily": "Segoe UI", "fontSize": f"{size}pt", "fontWeight": "bold" if bold else "normal", "color": shade}}]})
    doc = visual(page, key, "textbox", box, objects={"general": [{"properties": {"paragraphs": paragraphs}}]}, background=background)
    doc["visual"]["visualContainerObjects"]["padding"] = props(top=lit(4 if background else 0), bottom=lit(0), left=lit(12 if background else 0), right=lit(12 if background else 0))
    write(REPORT / "definition/pages" / ident(page) / "visuals" / doc["name"] / "visual.json", doc)
    return doc


def card(page, key, measure, title, box, note=None):
    return visual(page, key, "card", box, {"Values": [projection("Stations", measure, True)]}, title, note,
                  {"labels": props(color=color(INK), fontSize=lit(30), labelDisplayUnits=lit(0), labelPrecision=lit(1)),
                   "categoryLabels": props(show=lit(False)), "wordWrap": props(show=lit(True))})


def chart_objects(teal=TEAL):
    return {"dataPoint": props(defaultColor=color(teal)),
            "categoryAxis": props(showAxisTitle=lit(False), labelColor=color(MUTED), fontSize=lit(10)),
            "valueAxis": props(showAxisTitle=lit(False), labelColor=color(MUTED), fontSize=lit(9), gridlineShow=lit(True), gridlineColor=color("#E4EEF1")),
            "legend": props(show=lit(False)),
            "labels": props(show=lit(True), color=color(INK), fontSize=lit(10), labelPrecision=lit(1))}


def slicer(page, key, table, column, title, box):
    return visual(page, key, "slicer", box, {"Values": [projection(table, column)]}, title,
                  objects={"data": props(mode=lit("Dropdown")), "header": props(show=lit(False)),
                           "items": props(fontColor=color(INK), textSize=lit(11)),
                           "selection": props(singleSelect=lit(False), selectAllCheckboxEnabled=lit(True))}, background=False)


def header(page, title, subtitle, access=True):
    text_box(page, "header", (24, 18, 1392, 88), [(title, 22, True, INK), (subtitle, 10, False, MUTED)], True)
    slicer(page, "state", "Geography", "state_name", "State / jurisdiction", (938, 28, 235, 65))
    if access:
        slicer(page, "access", "Stations", "access_label", "Access", (1182, 28, 214, 65))
    else:
        text_box(page, "scope", (1180, 38, 214, 44), [("50 states + D.C. + PR", 11, True, TEAL), ("Population: July 2025", 9, False, MUTED)])


def build_model():
    write(BI / "EVChargingReadiness.pbip", {"$schema": SCHEMA + "pbip/pbipProperties/1.0.0/schema.json", "version": "1.0", "artifacts": [{"report": {"path": REPORT.name}}], "settings": {"enableAutoRecovery": True}})
    write(REPORT / "definition.pbir", {"$schema": SCHEMA + "item/report/definitionProperties/2.0.0/schema.json", "version": "4.0", "datasetReference": {"byPath": {"path": "../" + MODEL.name}}})
    write(MODEL / "definition.pbism", {"$schema": SCHEMA + "item/semanticModel/definitionProperties/1.0.0/schema.json", "version": "5.0", "settings": {"qnaEnabled": False}})
    write(MODEL / "definition/database.tmdl", "database EVChargingReadiness\n\tcompatibilityLevel: 1606\n\tcompatibilityMode: powerBI\n\tlanguage: 1033")
    write(MODEL / "definition/model.tmdl", "model Model\n\tculture: en-US\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n\tsourceQueryCulture: en-US\n\tvalueFilterBehavior: independent\n\nref expression ProjectRoot\nref table Stations\nref table Geography")
    write(MODEL / "definition/expressions.tmdl", f'expression ProjectRoot = "{ROOT}" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]')
    write(MODEL / "definition/relationships.tmdl", "relationship Geography_Stations\n\tfromColumn: Stations.state_abbr\n\ttoColumn: Geography.state_abbr\n\tcrossFilteringBehavior: oneDirection")
    measures = [
        ("Total Stations", "COALESCE(DISTINCTCOUNT(Stations[station_id]), 0)", "#,##0", "Distinct stations, not charging ports."),
        ("Opening Cohort Stations", "IF(NOT ISBLANK(SELECTEDVALUE(Stations[open_year])), [Total Stations])", "#,##0", "Only stations with a reported opening year. Current inventory, not historical openings."),
        ("Public Share", "DIVIDE(CALCULATE([Total Stations], KEEPFILTERS(Stations[is_public] = TRUE())), [Total Stations])", "0.0%", "Public stations divided by all stations in the current filters."),
        ("Availability Rate", "DIVIDE(CALCULATE([Total Stations], KEEPFILTERS(Stations[is_available] = TRUE())), [Total Stations])", "0.0%", "Inventory status, not measured uptime."),
        ("DC Fast Share", "DIVIDE(CALCULATE([Total Stations], KEEPFILTERS(Stations[has_dc_fast] = TRUE())), [Total Stations])", "0.0%", "Stations with reported DC fast ports divided by all stations."),
        ("Average Readiness", "AVERAGE(Stations[readiness_score])", "0.0", "Mean 0-100 screening heuristic; not a quality certification."),
        ("Public Available Stations", "CALCULATE([Total Stations], KEEPFILTERS(Stations[is_public_available] = TRUE()))", "#,##0", "Stations both public and marked available."),
        ("Coverage per 100k", "DIVIDE([Public Available Stations] * 100000, SUM(Geography[population_2025]))", "0.0", "Ratio of counts to selected population, never an unweighted average of state rates."),
        ("Unknown Facility Share", 'DIVIDE(CALCULATE([Total Stations], KEEPFILTERS(Stations[facility_type_label] = "Unknown")), [Total Stations])', "0.0%", "Share with unspecified facility type; retain instead of guessing."),
        ("Coverage Rank", "RANKX(ALLSELECTED(Geography[state_name]), [Coverage per 100k], , DESC, DENSE)", "0", "Rank within the selected jurisdictions."),
        ("Top Coverage", "IF([Coverage Rank] <= 8, [Coverage per 100k])", "0.0", "Top eight selected jurisdictions by public-and-available station density."),
        ("Network Rank", "RANKX(ALLSELECTED(Stations[ev_network]), [Total Stations], , DESC, DENSE)", "0", "Station-count ranking within current filters."),
        ("Top Network Stations", "IF([Network Rank] <= 6, [Total Stations])", "#,##0", "Top six networks; ties retained."),
        ("Snapshot Priority", "IF(HASONEVALUE(Geography[state_abbr]), MAX(Geography[priority_score]))", "0.0", "Fixed snapshot score; shown only at jurisdiction grain, not summed or averaged."),
        ("Snapshot Coverage", "DIVIDE(SUM(Geography[public_available_stations]) * 100000, SUM(Geography[population_2025]))", "0.0", "Unfiltered station-inventory coverage for selected jurisdictions."),
        ("Snapshot Availability", "DIVIDE(SUM(Geography[available_stations]), SUM(Geography[total_stations]))", "0.0%", "Weighted availability from the full snapshot for selected jurisdictions."),
        ("Median Coverage", "CALCULATE(MAX(Geography[national_median_public_available_per_100k]), REMOVEFILTERS(Geography))", "0.0", "Fixed median across the 52 source jurisdictions, including D.C. and Puerto Rico."),
        ("Jurisdictions", "COUNTROWS(Geography)", "0", "Selected population jurisdictions."),
        ("Below Median", "COUNTROWS(FILTER(Geography, Geography[public_available_per_100k] < [Median Coverage]))", "0", "Jurisdictions below the fixed snapshot median."),
        ("Priority Rank", "RANKX(ALLSELECTED(Geography[state_name]), [Snapshot Priority], , DESC, DENSE)", "0", "Priority rank within selected jurisdictions."),
        ("Top Priority", "IF([Priority Rank] <= 8, [Snapshot Priority])", "0.0", "Eight highest screening priorities; ties retained."),
    ]
    station_cols = {"station_id": "int64", "state_abbr": "string", "station_name": "string", "city": "string", "access_label": "string", "status_label": "string", "facility_type_label": "string", "ev_network": "string", "total_ports": "double", "dc_fast_ports": "double", "is_public": "boolean", "is_available": "boolean", "is_public_available": "boolean", "has_dc_fast": "boolean", "readiness_score": "int64", "readiness_band": "string", "open_year": "int64"}
    geo_cols = {"state_abbr": "string", "state_name": "string", "population_2025": "int64", "total_stations": "int64", "available_stations": "int64", "public_available_stations": "int64", "public_available_per_100k": "double", "priority_score": "double", "priority_band": "string", "national_median_public_available_per_100k": "double"}
    for table, filename, columns in [("Stations", "ev_stations_clean.csv", station_cols), ("Geography", "state_summary.csv", geo_cols)]:
        lines = [f"table {table}"]
        if table == "Stations":
            for name, dax, fmt, description in measures:
                lines += [f"\t/// {description}", f"\tmeasure '{name}' = {dax}", f"\t\tformatString: {fmt}", ""]
        for name, dtype in columns.items():
            lines += [f"\tcolumn {name}", f"\t\tdataType: {dtype}", "\t\tsummarizeBy: none", f"\t\tsourceColumn: {name}"]
            if name in {"station_id", "state_abbr"} or (table == "Geography" and name not in {"state_name", "priority_band"}):
                lines += ["\t\tisHidden"]
            if table == "Geography" and name == "state_abbr":
                lines += ["\t\tisKey"]
            lines += [""]
        types = {"int64": "Int64.Type", "double": "type number", "string": "type text", "boolean": "type logical"}
        select = ", ".join(f'"{c}"' for c in columns)
        casts = ", ".join('{"' + c + '", ' + types[t] + '}' for c, t in columns.items())
        lines += [f"\tpartition {table} = m", "\t\tmode: import", "\t\tsource =", "\t\t\tlet",
                  f'\t\t\t\tSource = Csv.Document(File.Contents(ProjectRoot & "\\data\\processed\\{filename}"), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),',
                  '\t\t\t\tHeaders = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),',
                  f'\t\t\t\tSelected = Table.SelectColumns(Headers, {{{select}}}),',
                  '\t\t\t\tNulls = Table.ReplaceValue(Selected, "", null, Replacer.ReplaceValue, Table.ColumnNames(Selected)),',
                  f'\t\t\t\tTyped = Table.TransformColumnTypes(Nulls, {{{casts}}}, "en-US")',
                  '\t\t\tin', '\t\t\t\tTyped']
        write(MODEL / f"definition/tables/{table}.tmdl", "\n".join(lines))


VISUALS = {"overview": [], "coverage": []}


def build_report():
    metadata = json.loads((ROOT / "data/raw/source_metadata.json").read_text(encoding="utf-8"))
    snapshot_date = datetime.fromisoformat(metadata["downloaded_at_utc"])
    write(REPORT / "definition/version.json", {"$schema": SCHEMA + "item/report/definition/versionMetadata/1.0.0/schema.json", "version": "2.0.0"})
    version = {"visual": "2.5.0", "report": "3.0.0", "page": "2.1.0"}
    write(REPORT / "definition/report.json", {"$schema": SCHEMA + "item/report/definition/report/3.0.0/schema.json",
          "themeCollection": {"baseTheme": {"name": "CY25SU12", "reportVersionAtImport": version, "type": "SharedResources"}, "customTheme": {"name": "CoastalReadiness.json", "reportVersionAtImport": version, "type": "RegisteredResources"}},
          "resourcePackages": [{"name": "RegisteredResources", "type": "RegisteredResources", "items": [{"name": "CoastalReadiness.json", "path": "CoastalReadiness.json", "type": "CustomTheme"}]}],
          "settings": {"useStylableVisualContainerHeader": True, "defaultFilterActionIsDataFilter": True, "defaultDrillFilterOtherVisuals": True, "allowChangeFilterTypes": True, "useEnhancedTooltips": True}})
    write(REPORT / "StaticResources/RegisteredResources/CoastalReadiness.json", {"name": "Coastal Readiness", "dataColors": [BLUE, "#E5AD91", TEAL, "#599B8C", "#C1D9DE", "#9D8BBA"], "background": "#FFFFFF", "foreground": INK, "tableAccent": TEAL, "textClasses": {"label": {"fontFace": "Segoe UI", "fontSize": 11, "color": INK}, "title": {"fontFace": "Segoe UI Semibold", "fontSize": 12, "color": INK}, "callout": {"fontFace": "Segoe UI Semibold", "fontSize": 30, "color": INK}}})
    write(REPORT / "definition/pages/pages.json", {"$schema": SCHEMA + "item/report/definition/pagesMetadata/1.0.0/schema.json", "pageOrder": [ident(p) for p in VISUALS], "activePageName": ident("overview")})
    for page, name in [("overview", "01  Network overview"), ("coverage", "02  Coverage priorities")]:
        write(REPORT / f"definition/pages/{ident(page)}/page.json", {"$schema": SCHEMA + "item/report/definition/page/2.1.0/schema.json", "name": ident(page), "displayName": name, "displayOption": "FitToPage", "width": 1440, "height": 900, "objects": {"background": props(color=color(PALE), transparency=lit(0))}})
    page = "overview"
    header(page, "EV CHARGING READINESS", f"Access, coverage & service-readiness  /  U.S. inventory snapshot · {snapshot_date:%d %b %Y}")
    for i, (measure, title, note) in enumerate([
        ("Total Stations", "Total stations", "Distinct sites · not ports"),
        ("Public Share", "Public access", "Share of selected stations"),
        ("Availability Rate", "Marked available", "Snapshot status · not uptime"),
        ("DC Fast Share", "DC-fast capable", "At least one reported fast port"),
        ("Average Readiness", "Readiness score", "Explainable heuristic / 100"),
    ]):
        card(page, f"kpi{i}", measure, title, (24 + i * 282, 122, 264, 116), note)
    line = chart_objects()
    line.pop("dataPoint")
    line["legend"] = props(show=lit(True), position=lit("Top"), showTitle=lit(False), fontSize=lit(9))
    line["labels"] = props(show=lit(False))
    line["lineStyles"] = props(strokeWidth=lit(3), showMarker=lit(False))
    visual(page, "cohorts", "lineChart", (24, 256, 660, 285), {"Category": [projection("Stations", "open_year", label="Opening year")], "Y": [projection("Stations", "Opening Cohort Stations", True, "Stations")], "Series": [projection("Stations", "access_label", label="Access")]}, "Stations by reported opening year", f"Current inventory cohorts · {snapshot_date.year} is partial · unknown years excluded", line, sort=(field("Stations", "open_year"), "Ascending"))
    donut = chart_objects()
    donut.pop("dataPoint")
    donut["legend"] = props(show=lit(True), position=lit("Bottom"), showTitle=lit(False), fontSize=lit(10))
    donut["labels"] = props(show=lit(True), labelStyle=lit("Percent of total"), fontSize=lit(10), labelPrecision=lit(1))
    visual(page, "readiness", "donutChart", (702, 256, 360, 285), {"Category": [projection("Stations", "readiness_band")], "Y": [projection("Stations", "Total Stations", True)]}, "Station readiness mix", "Ready ≥80 · partly ready 50–79 · review <50", donut)
    table_roles = {"Values": [projection("Geography", "state_name", label="Jurisdiction"), projection("Stations", "Total Stations", True, "Stations"), projection("Stations", "Coverage per 100k", True, "Public + available / 100k"), projection("Stations", "Availability Rate", True, "Available"), projection("Stations", "DC Fast Share", True, "DC fast")]}
    table_obj = {"grid": props(gridVertical=lit(False), gridHorizontal=lit(True), gridHorizontalColor=color("#E7F1F4"), rowPadding=lit(6), textSize=lit(10)), "columnHeaders": props(fontColor=color(INK), backColor=color("#E5F1F5"), fontSize=lit(10), wordWrap=lit(True)), "values": props(fontColorPrimary=color(INK), backColorPrimary=color("#FFFFFF"), backColorSecondary=color("#F2F8FA"), fontSize=lit(10)), "total": props(totals=lit(False))}
    visual(page, "states", "tableEx", (24, 559, 660, 291), table_roles, "Coverage by jurisdiction", "Population-normalized access · sorted by density", table_obj, sort=(field("Stations", "Coverage per 100k", True), "Descending"))
    networks = chart_objects(BLUE)
    networks["categoryAxis"] = props(showAxisTitle=lit(False), labelColor=color(MUTED), fontSize=lit(9), maxMarginFactor=lit(50))
    visual(page, "networks", "clusteredBarChart", (702, 559, 360, 291), {"Category": [projection("Stations", "ev_network", label="Network")], "Y": [projection("Stations", "Top Network Stations", True, "Stations")]}, "Largest network footprints", "Top six by station count in the selection", networks, sort=(field("Stations", "Top Network Stations", True), "Descending"))
    text_box(page, "quality-note", (1080, 256, 336, 186), [("01 / READ THE SIGNAL", 10, True, MUTED), ("Coverage ≠ reliability", 18, True, TEAL), ("Available is a status in one inventory", 11, False, INK), ("snapshot. Validate outage and charging", 11, False, INK), ("session history before claiming uptime.", 11, False, INK)], True)
    card(page, "unknown-facility", "Unknown Facility Share", "02 / Facility type not reported", (1080, 459, 336, 186), "Keep missing categories visible")
    text_box(page, "next", (1080, 662, 336, 188), [("03 / NEXT DECISION", 10, True, MUTED), ("Prioritize a closer look", 18, True, TEAL), ("Open Coverage priorities below.", 11, False, INK), ("Screen low-coverage areas, then check", 11, False, INK), ("EV demand, travel routes and site costs.", 11, False, INK)], True)
    text_box(page, "footer", (30, 864, 1380, 28), [("NREL station inventory × U.S. Census population  |  Click charts to cross-filter; Ctrl+click for multiple selections  |  Screening, not an investment recommendation", 9, False, MUTED)])
    page = "coverage"
    header(page, "WHERE SHOULD COVERAGE IMPROVE?", "An explainable shortlist for follow-up research · full inventory metrics, not live reliability", False)
    for i, (measure, title, note) in enumerate([
        ("Jurisdictions", "Jurisdictions", "Selected from 52 areas"), ("Snapshot Coverage", "Public + available / 100k", "Population-weighted coverage"),
        ("Median Coverage", "Jurisdiction median / 100k", "Fixed benchmark across 52 areas"), ("Below Median", "Below the benchmark", "Count within your selection"),
        ("Snapshot Availability", "Marked available", "Weighted inventory status"),
    ]):
        card(page, f"kpi{i}", measure, title, (24 + i * 282, 122, 264, 116), note)
    visual(page, "priority-bars", "clusteredBarChart", (24, 256, 660, 288), {"Category": [projection("Geography", "state_name")], "Y": [projection("Stations", "Top Priority", True, "Priority score")]}, "Where to investigate first", "Top eight · higher score = larger screening gap", chart_objects(TEAL), sort=(field("Stations", "Top Priority", True), "Descending"))
    visual(page, "coverage-bars", "clusteredBarChart", (702, 256, 714, 288), {"Category": [projection("Geography", "state_name")], "Y": [projection("Stations", "Top Coverage", True, "Public + available / 100k")]}, "Coverage leaders for comparison", "Top eight selected jurisdictions · not a quality ranking", chart_objects(BLUE), sort=(field("Stations", "Top Coverage", True), "Descending"))
    roles = {"Values": [projection("Geography", "state_name", label="Jurisdiction"), projection("Stations", "Snapshot Coverage", True, "Public + available / 100k"), projection("Stations", "Snapshot Availability", True, "Available"), projection("Stations", "Snapshot Priority", True, "Priority / 100"), projection("Geography", "priority_band", label="Review band")]}
    visual(page, "priority-table", "tableEx", (24, 562, 918, 288), roles, "The follow-up shortlist", "Sortable jurisdiction detail · including D.C. and Puerto Rico", table_obj, sort=(field("Stations", "Snapshot Priority", True), "Descending"))
    text_box(page, "method", (960, 562, 456, 288), [("HOW THE SCORE WORKS", 11, True, MUTED), ("70% coverage gap", 20, True, TEAL), ("Shortfall below the jurisdiction median", 12, False, INK), ("+ 30% status gap", 20, True, TEAL), ("Share not currently marked available", 12, False, INK), ("Weights are analyst choices, not learned effects.", 11, False, MUTED), ("Check EV adoption, roads and rural access next.", 11, False, MUTED)], True)
    text_box(page, "footer", (30, 864, 1380, 28), [("Coverage gap is capped at zero above the median  |  A low score is not proof of adequate service  |  Population alone does not measure charging demand", 9, False, MUTED)])


if __name__ == "__main__":
    build_model()
    build_report()
    print(f"Built {sum(map(len, VISUALS.values()))} native visuals across two Power BI pages.")
    print(f"Open {BI / 'EVChargingReadiness.pbip'} and refresh in Power BI Desktop.")
