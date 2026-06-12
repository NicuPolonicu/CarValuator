param(
    [string]$ModelResultsDir = "data\model_results_combined_reader_20260606_log",
    [string]$SimilarityCsv = "data\similarity_current.csv",
    [string]$OutputRoot = "deploy_artifacts",
    [string[]]$CloudModels = @("svr_rbf", "ridge", "knn_distance", "gradient_boosting"),
    [int]$CompressionLevel = 3,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$modelSource = Resolve-Path $ModelResultsDir
$csvSource = Resolve-Path $SimilarityCsv
$outputPath = Join-Path $projectRoot $OutputRoot
$modelOutput = Join-Path $outputPath "model_results"
$datasetOutput = Join-Path $outputPath "datasets"

if ($Clean -and (Test-Path $outputPath)) {
    Remove-Item -LiteralPath $outputPath -Recurse -Force
}

New-Item -ItemType Directory -Path $modelOutput -Force | Out-Null
New-Item -ItemType Directory -Path $datasetOutput -Force | Out-Null

$requiredModel = Join-Path $modelSource "best_model.joblib"
if (-not (Test-Path $requiredModel)) {
    throw "Could not find best_model.joblib in $modelSource"
}

$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

$cloudModelOutput = Join-Path $modelOutput "best_model.joblib"
$cloudModelScript = Join-Path $PSScriptRoot "prepare_cloud_model.py"
$cloudModelArgs = @(
    $cloudModelScript,
    $requiredModel,
    $cloudModelOutput,
    "--compress",
    "$CompressionLevel",
    "--models"
) + $CloudModels

& $python @cloudModelArgs
if ($LASTEXITCODE -ne 0) {
    throw "Could not create the cloud model bundle."
}

$artifactPatterns = @(
    "metrics.csv",
    "training_report.json",
    "feature_significance.csv",
    "model_performance.png",
    "actual_vs_predicted.png",
    "price_distribution.png",
    "price_vs_mileage.png",
    "correlation_heatmap.png"
)

foreach ($artifact in $artifactPatterns) {
    $source = Join-Path $modelSource $artifact
    if (Test-Path $source) {
        Copy-Item -LiteralPath $source -Destination (Join-Path $modelOutput $artifact) -Force
    }
}

Copy-Item -LiteralPath $csvSource -Destination (Join-Path $datasetOutput "similarity_current.csv") -Force

Write-Host "Prepared Render artifacts in $outputPath"
Write-Host ""
Write-Host "Render environment paths:"
Write-Host "  CARVALUATOR_MODEL_BUNDLE=deploy_artifacts/model_results/best_model.joblib"
Write-Host "  CARVALUATOR_SIMILARITY_CSV=deploy_artifacts/datasets/similarity_current.csv"
Write-Host ""
Write-Host "Tip: refresh artifacts before a Render deployment:"
Write-Host "  .\scripts\prepare-render-artifacts.ps1 -Clean"
