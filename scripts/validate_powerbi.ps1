param(
    [Parameter(Mandatory = $true)] [int]$Port
)

# Read-only validation against the model in an open Power BI Desktop session.
$ErrorActionPreference = 'Stop'
$evRoot = Split-Path -Parent $PSScriptRoot
$evClient = 'C:\Program Files\Microsoft Power BI Desktop\bin\Microsoft.PowerBI.AdomdClient.dll'
if (-not (Test-Path -LiteralPath $evClient)) { throw 'Power BI Desktop client library not found.' }
Add-Type -Path $evClient
$evConnection = [Microsoft.AnalysisServices.AdomdClient.AdomdConnection]::new("Data Source=localhost:$Port")
$evConnection.Open()

function Read-EvQuery([string]$Dax) {
    $evCommand = $evConnection.CreateCommand()
    $evCommand.CommandText = $Dax
    $evReader = $evCommand.ExecuteReader()
    try {
        while ($evReader.Read()) {
            $evRow = [ordered]@{}
            for ($evIndex = 0; $evIndex -lt $evReader.FieldCount; $evIndex++) {
                $evRow[$evReader.GetName($evIndex)] = $evReader.GetValue($evIndex)
            }
            [pscustomobject]$evRow
        }
    } finally { $evReader.Close() }
}

function Assert-EvNear([double]$Actual, [double]$Expected, [string]$Label) {
    if ([Math]::Abs($Actual - $Expected) -gt 0.0000001) {
        throw "$Label differs: $Actual vs expected $Expected"
    }
}

try {
    $evSummary = Import-Csv -LiteralPath (Join-Path $evRoot 'data\processed\state_summary.csv')
    $evLookup = @{}
    foreach ($evItem in $evSummary) { $evLookup[$evItem.state_abbr] = $evItem }
    $evRows = @(Read-EvQuery 'EVALUATE SUMMARIZECOLUMNS(Geography[state_abbr], "Stations", [Total Stations], "Coverage", [Coverage per 100k], "Available", [Availability Rate], "Public", [Public Share], "Fast", [DC Fast Share], "Priority", [Snapshot Priority])')
    if ($evRows.Count -ne 52) { throw 'Expected 52 jurisdiction rows.' }
    foreach ($evRow in $evRows) {
        $evCode = $evRow.'Geography[state_abbr]'
        $evExpected = $evLookup[$evCode]
        Assert-EvNear $evRow.'[Stations]' $evExpected.total_stations "$evCode station count"
        Assert-EvNear $evRow.'[Coverage]' $evExpected.public_available_per_100k "$evCode coverage"
        Assert-EvNear $evRow.'[Available]' $evExpected.availability_rate "$evCode availability"
        Assert-EvNear $evRow.'[Public]' $evExpected.public_share "$evCode public share"
        Assert-EvNear $evRow.'[Fast]' $evExpected.dc_fast_station_share "$evCode fast share"
        Assert-EvNear $evRow.'[Priority]' $evExpected.priority_score "$evCode priority"
    }
    $evTotals = Read-EvQuery 'EVALUATE ROW("Stations", [Total Stations], "Coverage", [Coverage per 100k], "SnapshotCoverage", [Snapshot Coverage], "Priority", [Snapshot Priority])'
    Assert-EvNear $evTotals.'[Stations]' ($evSummary | Measure-Object total_stations -Sum).Sum 'Total stations'
    $evExpectedCoverage = 100000 * ($evSummary | Measure-Object public_available_stations -Sum).Sum / ($evSummary | Measure-Object population_2025 -Sum).Sum
    Assert-EvNear $evTotals.'[Coverage]' $evExpectedCoverage 'Weighted coverage'
    Assert-EvNear $evTotals.'[SnapshotCoverage]' $evExpectedCoverage 'Weighted snapshot coverage'
    if (($null -ne $evTotals.'[Priority]') -and ($evTotals.'[Priority]' -isnot [DBNull])) {
        throw 'Priority must be blank for a multi-jurisdiction total.'
    }
    $evPrivate = Read-EvQuery 'EVALUATE CALCULATETABLE(ROW("PublicShare", [Public Share], "Coverage", [Coverage per 100k]), Stations[access_label] = "Private")'
    Assert-EvNear $evPrivate.'[PublicShare]' 0 'Private selection public share'
    Assert-EvNear $evPrivate.'[Coverage]' 0 'Private selection public coverage'
    $evPublic = Read-EvQuery 'EVALUATE CALCULATETABLE(ROW("PublicShare", [Public Share]), Stations[access_label] = "Public")'
    Assert-EvNear $evPublic.'[PublicShare]' 1 'Public selection public share'
    Write-Output 'PASS: 52 jurisdictions x 6 live DAX metrics match the Python CSV.'
    Write-Output 'PASS: national ratio-of-sums coverage and blank priority total.'
    Write-Output 'PASS: public/private filter intersections.'
} finally { $evConnection.Close() }
