param(
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8017,

    [string]$ModelBundle = "data\model_results_combined_reader_20260606_log\best_model.joblib",
    [string]$SimilarityCsv = "data\similarity_current.csv",
    [string]$AuthDb = "data\carvaluator_users.db",

    [switch]$InstallDependencies,
    [switch]$ScrapeAutovit,
    [switch]$ScrapeMobileDe,
    [switch]$UseExistingJsonl,
    [switch]$ExportCsv,
    [switch]$Train,
    [switch]$NoLogTarget,
    [switch]$DisableFeatureSelection,
    [switch]$StopExisting,
    [switch]$Background,
    [switch]$NoServer,

    [string]$AutovitUrl = "https://www.autovit.ro/autoturisme",
    [int]$AutovitPages = 25,
    [double]$AutovitDelay = 0.5,

    [string]$MobileDeUrl = "https://suchen.mobile.de/fahrzeuge/search.html?dam=false&isSearchRequest=true&ref=quickSearch&s=Car&vc=Car",
    [int]$MobileDePages = 5,
    [double]$MobileDeDelay = 1.0,
    [switch]$HeadfulMobileDe,
    [string]$BrowserChannel = "chromium",

    [string[]]$ExtraJsonl = @(),
    [string]$RunName = (Get-Date -Format "yyyyMMdd_HHmmss"),
    [string]$CsvOutput = "",
    [string]$ModelOutputDir = ""
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Resolve-ProjectPath {
    param([string]$PathValue)
    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return [System.IO.Path]::GetFullPath($PathValue)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $PathValue))
}

function Invoke-CarCommand {
    param([string[]]$Arguments)
    Write-Host ("    python " + ($Arguments -join " ")) -ForegroundColor DarkGray
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE."
    }
}

$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
Set-Location $ProjectRoot

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (!(Test-Path $VenvPython)) {
    Write-Step "Creating virtual environment"
    python -m venv .venv
}

$Python = $VenvPython

if ($InstallDependencies) {
    Write-Step "Installing Python package and browser runtime"
    Invoke-CarCommand @("-m", "pip", "install", "-e", ".")
    Invoke-CarCommand @("-m", "playwright", "install", "chromium")
}

New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "data") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "data\scrapes") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "data\datasets") | Out-Null

$RawInputs = @()
foreach ($path in $ExtraJsonl) {
    $RawInputs += (Resolve-ProjectPath $path)
}

if ($ScrapeAutovit) {
    $AutovitOutput = Resolve-ProjectPath "data\scrapes\$RunName`_autovit.jsonl"
    Write-Step "Scraping Autovit search pages"
    Invoke-CarCommand @(
        "-m", "carvaluator_scraper.cli", "scrape-search", "autovit", $AutovitUrl,
        "--pages", "$AutovitPages",
        "--delay", "$AutovitDelay",
        "--output", $AutovitOutput
    )
    $RawInputs += $AutovitOutput
}

if ($ScrapeMobileDe) {
    $MobileOutput = Resolve-ProjectPath "data\scrapes\$RunName`_mobilede.jsonl"
    Write-Step "Scraping mobile.de search pages"
    $mobileArgs = @(
        "-m", "carvaluator_scraper.cli", "scrape-search", "mobilede", $MobileDeUrl,
        "--pages", "$MobileDePages",
        "--delay", "$MobileDeDelay",
        "--output", $MobileOutput,
        "--browser-channel", $BrowserChannel
    )
    if ($HeadfulMobileDe) {
        $mobileArgs += "--headful"
    }
    Invoke-CarCommand $mobileArgs
    $RawInputs += $MobileOutput
}

if ($UseExistingJsonl) {
    Write-Step "Collecting existing JSONL files from data"
    $existing = Get-ChildItem -Path (Join-Path $ProjectRoot "data") -Filter "*.jsonl" -File |
        Where-Object { $_.Length -gt 0 } |
        Select-Object -ExpandProperty FullName
    $RawInputs += $existing
}

$RawInputs = $RawInputs | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique

if ($ExportCsv -or ($Train -and $RawInputs.Count -gt 0)) {
    if ($RawInputs.Count -eq 0) {
        throw "No JSONL inputs found. Use -ScrapeAutovit, -ScrapeMobileDe, -ExtraJsonl, or -UseExistingJsonl."
    }
    if ([string]::IsNullOrWhiteSpace($CsvOutput)) {
        $CsvOutput = "data\datasets\$RunName`_training.csv"
    }
    $CsvOutputResolved = Resolve-ProjectPath $CsvOutput
    $CsvReport = [System.IO.Path]::ChangeExtension($CsvOutputResolved, ".report.json")

    Write-Step "Exporting model-ready CSV"
    $exportArgs = @("-m", "carvaluator_scraper.cli", "export-csv")
    $exportArgs += $RawInputs
    $exportArgs += @(
        "--output", $CsvOutputResolved,
        "--drop-fuzzy-duplicates",
        "--report", $CsvReport
    )
    Invoke-CarCommand $exportArgs
    $SimilarityCsv = $CsvOutputResolved
}

if ($Train) {
    $TrainingCsv = Resolve-ProjectPath $SimilarityCsv
    if (!(Test-Path $TrainingCsv)) {
        throw "Training CSV not found: $TrainingCsv"
    }
    if ([string]::IsNullOrWhiteSpace($ModelOutputDir)) {
        $suffix = if ($NoLogTarget) { "" } else { "_log" }
        $ModelOutputDir = "data\model_results_$RunName$suffix"
    }
    $ModelOutputResolved = Resolve-ProjectPath $ModelOutputDir

    Write-Step "Training models"
    $trainArgs = @(
        "-m", "carvaluator_scraper.cli", "train-models", $TrainingCsv,
        "--output-dir", $ModelOutputResolved
    )
    if (!$NoLogTarget) {
        $trainArgs += "--log-target"
    }
    if ($DisableFeatureSelection) {
        $trainArgs += "--disable-feature-selection"
    }
    Invoke-CarCommand $trainArgs
    $ModelBundle = Join-Path $ModelOutputResolved "best_model.joblib"
}

$ModelBundleResolved = Resolve-ProjectPath $ModelBundle
$SimilarityCsvResolved = Resolve-ProjectPath $SimilarityCsv
$AuthDbResolved = Resolve-ProjectPath $AuthDb

if (!(Test-Path $ModelBundleResolved)) {
    throw "Model bundle not found: $ModelBundleResolved"
}
if (!(Test-Path $SimilarityCsvResolved)) {
    throw "Similarity CSV not found: $SimilarityCsvResolved"
}

$env:CARVALUATOR_MODEL_BUNDLE = $ModelBundleResolved
$env:CARVALUATOR_SIMILARITY_CSV = $SimilarityCsvResolved
$env:CARVALUATOR_AUTH_DB = $AuthDbResolved
$env:CARVALUATOR_API_HOST = $HostName
$env:CARVALUATOR_API_PORT = "$Port"

if ($RawInputs.Count -gt 0) {
    $mobileInputs = $RawInputs | Where-Object { [System.IO.Path]::GetFileName($_).ToLowerInvariant().Contains("mobile") }
    if ($mobileInputs.Count -gt 0) {
        $env:CARVALUATOR_MOBILEDE_DATASETS = ($mobileInputs -join [System.IO.Path]::PathSeparator)
    }
}

Write-Step "Active configuration"
Write-Host "Model bundle:   $env:CARVALUATOR_MODEL_BUNDLE"
Write-Host "Similarity CSV: $env:CARVALUATOR_SIMILARITY_CSV"
Write-Host "Auth DB:        $env:CARVALUATOR_AUTH_DB"
Write-Host "Host/port:      $env:CARVALUATOR_API_HOST`:$env:CARVALUATOR_API_PORT"

if ($NoServer) {
    Write-Host ""
    Write-Host "Skipping server start because -NoServer was provided." -ForegroundColor Yellow
    exit 0
}

$existingConnection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($existingConnection) {
    if ($StopExisting) {
        Write-Step "Stopping existing server on port $Port"
        Stop-Process -Id $existingConnection.OwningProcess -Force
        Start-Sleep -Seconds 1
    }
    else {
        throw "Port $Port is already in use by process $($existingConnection.OwningProcess). Re-run with -StopExisting or choose -Port."
    }
}

Write-Step "Starting CarValuator API"
Write-Host "Open http://$HostName`:$Port/"

if ($Background) {
    $stdout = Resolve-ProjectPath "data\api_$Port.out.log"
    $stderr = Resolve-ProjectPath "data\api_$Port.err.log"
    Start-Process `
        -FilePath $Python `
        -ArgumentList "-m", "carvaluator_scraper.api" `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr
    Write-Host "Server started in background. Logs:"
    Write-Host "  $stdout"
    Write-Host "  $stderr"
}
else {
    & $Python -m carvaluator_scraper.api
}
