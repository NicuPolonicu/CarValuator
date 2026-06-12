param(
    [int]$Pages = 100,
    [double]$Delay = 0.35,
    [int]$Port = 8017,
    [switch]$UpdateRenderArtifacts,
    [switch]$RestartServer
)

$ErrorActionPreference = "Stop"

$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Virtual environment not found. Run .\scripts\start-carvaluator.ps1 -InstallDependencies -NoServer first."
}

Set-Location $projectRoot

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$scrapeDir = Join-Path $projectRoot "data\scrapes"
$datasetDir = Join-Path $projectRoot "data\datasets"
$rawOutput = Join-Path $scrapeDir "similarity_autovit_$stamp.jsonl"
$csvArchive = Join-Path $datasetDir "similarity_autovit_$stamp.csv"
$reportArchive = Join-Path $datasetDir "similarity_autovit_$stamp.report.json"
$currentCsv = Join-Path $projectRoot "data\similarity_current.csv"
$currentReport = Join-Path $projectRoot "data\similarity_current.report.json"

New-Item -ItemType Directory -Force -Path $scrapeDir, $datasetDir | Out-Null

Write-Host "Collecting current Autovit listings..." -ForegroundColor Cyan
& $python -m carvaluator_scraper.cli scrape-search autovit `
    "https://www.autovit.ro/autoturisme" `
    --pages "$Pages" `
    --delay "$Delay" `
    --output $rawOutput
if ($LASTEXITCODE -ne 0) {
    throw "Autovit scraping failed."
}

Write-Host "Normalizing and deduplicating the similarity dataset..." -ForegroundColor Cyan
& $python -m carvaluator_scraper.cli export-csv $rawOutput `
    --output $csvArchive `
    --drop-fuzzy-duplicates `
    --report $reportArchive
if ($LASTEXITCODE -ne 0) {
    throw "Similarity CSV export failed."
}

# Replace the active snapshot only after scraping and export both succeeded.
Copy-Item -LiteralPath $csvArchive -Destination $currentCsv -Force
Copy-Item -LiteralPath $reportArchive -Destination $currentReport -Force

if ($UpdateRenderArtifacts) {
    Write-Host "Refreshing Render artifacts..." -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot "prepare-render-artifacts.ps1") `
        -SimilarityCsv $currentCsv `
        -Clean
    if ($LASTEXITCODE -ne 0) {
        throw "Render artifact preparation failed."
    }
}

if ($RestartServer) {
    Write-Host "Restarting the local server..." -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot "start-carvaluator.ps1") `
        -Port $Port `
        -SimilarityCsv $currentCsv `
        -Background `
        -StopExisting
    if ($LASTEXITCODE -ne 0) {
        throw "Server restart failed."
    }
}

Write-Host ""
Write-Host "Similarity refresh completed." -ForegroundColor Green
Write-Host "Active CSV: $currentCsv"
Write-Host "Archived CSV: $csvArchive"
if ($UpdateRenderArtifacts) {
    Write-Host "Render artifacts were refreshed locally. Commit, push and redeploy to update the public site."
}
