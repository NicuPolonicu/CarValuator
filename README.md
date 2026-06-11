# CarValuator

CarValuator is a thesis prototype for evaluating second-hand car ads. It accepts an Autovit listing link, extracts the car data, predicts a fair market price with trained regression models, classifies the ad as fair / suspiciously cheap / overpriced, and shows similar cars from the scraped dataset.

The current app supports Autovit and `mobile.de` links for prediction. Search scraping works for both sites; mobile.de uses its search JSON endpoint with browser-like headers and keeps a visible-browser fallback for cases where the endpoint is blocked.

## 1. Setup

Create and activate the virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install the project:

```powershell
python -m pip install -e .
python -m playwright install chromium
```

If PowerShell blocks activation, run this once in the current terminal:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
```

You can also avoid activation and call Python directly:

```powershell
.\.venv\Scripts\python.exe -m carvaluator_scraper.api
```

## 2. Scrape Data

Small Autovit scrape:

```powershell
python -m carvaluator_scraper.cli scrape-search autovit "https://www.autovit.ro/autoturisme" --pages 3 --delay 0.75 --output data\autovit_search.jsonl
```

Larger training scrape:

```powershell
python -m carvaluator_scraper.cli scrape-search autovit "https://www.autovit.ro/autoturisme" --pages 150 --delay 0.4 --output data\autovit_xl.jsonl
```

Scrape one detail page:

```powershell
python -m carvaluator_scraper.cli scrape-detail autovit "https://www.autovit.ro/autoturisme/anunt/example.html"
```

Try `mobile.de`:

```powershell
python -m carvaluator_scraper.cli scrape-search mobilede "https://suchen.mobile.de/fahrzeuge/search.html?dam=false&isSearchRequest=true&ref=quickSearch&s=Car&vc=Car" --pages 5 --delay 1 --output data\mobilede_search.jsonl
```

If mobile.de returns `401`, `403`, or `429`, wait a bit and retry with fewer pages. You can also attempt the Playwright fallback with `--headful --browser-channel msedge`, but the rendered site is more likely to show an access-denied page than the JSON endpoint.

mobile.de repeats promoted listings across pages, so the scraper deduplicates by listing ID during each run. For a larger dataset, run several filtered searches by make/model/year/price instead of relying only on one very broad URL.

## 3. Normalize And Export CSV

Normalize JSONL data:

```powershell
python -m carvaluator_scraper.cli normalize data\autovit_xl.jsonl --output data\autovit_xl_normalized.jsonl --drop-fuzzy-duplicates --report data\autovit_xl_normalized_report.json
```

Export model-ready CSV:

```powershell
python -m carvaluator_scraper.cli export-csv data\autovit_xl.jsonl --output data\autovit_xl.csv --drop-fuzzy-duplicates --report data\autovit_xl_export_report.json
```

The CSV is used both for model training and for similar-car suggestions in the web app.

## 4. Train Models

Train all regression models with log-price target:

```powershell
python -m carvaluator_scraper.cli train-models data\autovit_xl.csv --output-dir data\model_results_xl_log --log-target
```

The training pipeline currently includes:

- `SVR`
- `Ridge`
- `KNN`
- `RandomForest`
- `ExtraTrees`
- `GradientBoosting`
- `VotingRegressor` ensemble

The training command also performs:

- missing-value imputation
- numeric scaling where needed
- one-hot encoding for categorical fields
- significance-based feature filtering
- feature engineering such as `vehicle_age`, `mileage_per_year`, `hp_per_liter`, and `make_model`
- outlier filtering for unrealistic prices/specs
- model comparison metrics
- plot generation

Training outputs:

- `best_model.joblib`
- `metrics.csv`
- `training_report.json`
- `feature_significance.csv`
- `best_model_predictions.csv`
- `predictions_<model>.csv`
- `model_performance.png`
- `actual_vs_predicted.png`
- `price_distribution.png`
- `price_vs_mileage.png`
- `correlation_heatmap.png`

## 5. Predict From CLI

Predict one Autovit ad:

```powershell
python -m carvaluator_scraper.cli predict-from-link autovit "https://www.autovit.ro/autoturisme/anunt/example.html" --model-bundle data\model_results_xl_log\best_model.joblib --similarity-csv data\autovit_xl.csv
```

Predict one mobile.de ad that exists in your scraped mobile.de JSONL/CSV files:

```powershell
python -m carvaluator_scraper.cli predict-from-link mobilede "https://suchen.mobile.de/auto-inserat/example/445288256.html" --model-bundle data\model_results_xl_log\best_model.joblib --similarity-csv data\autovit_xl.csv
```

For mobile.de prediction, the app first looks in the configured CSV, then in local `data\mobilede*.jsonl` / `data\mobilede*.csv` files, then tries a small live search scan. If you keep mobile.de data somewhere else, set `CARVALUATOR_MOBILEDE_DATASETS` to one or more paths separated by `;` on Windows.

The response includes:

- listing title and URL
- listing image URL when available
- actual ad price
- best-model predicted price
- verdict
- estimates from every trained model
- similar cars from the scraped dataset

## 6. Start The Web App

Fastest option: use the helper script. It sets the model, dataset, auth database, host and port environment variables for you, then starts the API.

```powershell
.\scripts\start-carvaluator.ps1 -Port 8017
```

If the port is already used by an older CarValuator process:

```powershell
.\scripts\start-carvaluator.ps1 -Port 8017 -StopExisting
```

Run the server in the background:

```powershell
.\scripts\start-carvaluator.ps1 -Port 8017 -Background -StopExisting
```

Scrape first, export a fresh CSV, retrain models, then start the server using the new model:

```powershell
.\scripts\start-carvaluator.ps1 -ScrapeAutovit -AutovitPages 50 -ExportCsv -Train -Port 8017 -StopExisting
```

Scrape both Autovit and mobile.de before retraining:

```powershell
.\scripts\start-carvaluator.ps1 -ScrapeAutovit -AutovitPages 50 -ScrapeMobileDe -MobileDePages 5 -ExportCsv -Train -Port 8017 -StopExisting
```

Retrain from existing JSONL files in `data`:

```powershell
.\scripts\start-carvaluator.ps1 -UseExistingJsonl -ExportCsv -Train -NoServer
```

The helper script supports these useful switches:

- `-InstallDependencies`: run `pip install -e .` and install Playwright Chromium.
- `-ScrapeAutovit`: scrape Autovit search pages before startup.
- `-ScrapeMobileDe`: scrape mobile.de search pages before startup.
- `-ExportCsv`: convert JSONL files to a model-ready CSV.
- `-Train`: train models and use the new `best_model.joblib`.
- `-Background`: start the API in the background and write logs under `data`.
- `-NoServer`: run setup/scrape/train steps only.

Recommended local start:

```powershell
$env:CARVALUATOR_MODEL_BUNDLE = "data\model_results_xl_log\best_model.joblib"
$env:CARVALUATOR_SIMILARITY_CSV = "data\autovit_xl.csv"
$env:CARVALUATOR_API_PORT = "8001"
.\.venv\Scripts\python.exe -m carvaluator_scraper.api
```

Then open:

```text
http://127.0.0.1:8001/
```

Health check:

```text
http://127.0.0.1:8001/health
```

The web app shows:

- Romanian interface
- dark/light mode
- email/username/password account creation and login
- per-account prediction history
- loading animation
- main car image when Autovit or mobile.de provides one
- fair-price verdict
- estimates from every trained model
- Python-generated model performance plots
- similar car ads from the scraped CSV

Account data and prediction history are stored locally in `data\carvaluator_users.db` by default. Passwords are stored as salted PBKDF2 hashes, and logged-in sessions use an HTTP-only cookie. To move the auth database, set `CARVALUATOR_AUTH_DB`.

## 7. API Routes

Main routes:

- `GET /`
- `GET /health`
- `POST /predict`
- `GET /history`
- `GET /model-artifacts/model_performance.png`
- `GET /model-artifacts/actual_vs_predicted.png`

Example API request:

```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8001/predict" -ContentType "application/json" -Body '{"site":"autovit","url":"https://www.autovit.ro/autoturisme/anunt/example.html","threshold_percent":15,"similar_limit":4}'
```

## 8. Deploy On Render

The repo includes a `render.yaml` Blueprint and a `Dockerfile` for deploying the FastAPI app as one public Render web service. Docker keeps the ML runtime reproducible and installs the Chromium browser required by the mobile.de fallback.

The repository includes a prepared `deploy_artifacts` folder, so Render does not need access to the ignored local `data` directory. Regenerate it from the current combined dataset and model with:

```powershell
.\scripts\prepare-render-artifacts.ps1 -Clean
```

This creates:

- `deploy_artifacts\model_results\best_model.joblib`
- `deploy_artifacts\datasets\combined_reader_20260606.csv`
- copied training metrics and plots when available

The cloud bundle keeps SVR, Ridge, KNN, and Gradient Boosting. The UI still shows four model estimates plus the weighted final estimate, while avoiding the much larger Random Forest, Extra Trees, and duplicated Voting Regressor objects. The resulting model file is approximately 1 MB instead of approximately 204 MB.

Then commit and push these deployment files to GitHub:

```powershell
git add .dockerignore Dockerfile pyproject.toml render.yaml README.md src scripts deploy_artifacts
git commit -m "Fix Render ML and mobile.de runtime"
git push origin main
```

In Render:

1. Sign in at `https://dashboard.render.com` with GitHub.
2. Choose `New` and then `Blueprint`.
3. Connect `NicuPolonicu/CarValuator`.
4. Select the `main` branch. Render detects the root `render.yaml`.
5. Apply the Blueprint and wait for the `carvaluator` service to become live.
6. Open the generated `https://carvaluator-....onrender.com` URL.

The default Render config uses:

```text
Region: Frankfurt
Plan: Free
Runtime: Docker
Dockerfile: ./Dockerfile
Health check: /health
```

The Docker build pins the same `scikit-learn`, NumPy, SciPy, pandas, and joblib versions used to create the deployed model bundle. It also installs Playwright Chromium instead of assuming that Microsoft Edge exists on the Linux server. The app binds to `0.0.0.0` and reads Render's `PORT` environment variable.

After changing runtime dependencies, use `Manual Deploy` and `Clear build cache & deploy` in Render. Once live, open `/health` and verify that `runtime_versions.scikit_learn` is `1.8.0` and `runtime_versions.playwright` is `1.58.0`.

Important demo limitations:

- Render Free has 512 MB RAM and spins down after 15 minutes without traffic. The first request after that can take about one minute.
- Accounts and history use `/tmp/carvaluator_users.db`. They can reset after a restart, redeploy, or spin-down, which is acceptable for a faculty demo but not production.
- mobile.de and Autovit can block requests originating from cloud IP addresses. For the safest demo, test links already present in `combined_reader_20260606.csv`.
- Open the public site several minutes before presenting, log in, and run one test prediction to warm the service.

## 9. Current Best Dataset And Model

The recommended current files are:

- raw scrape: `data\autovit_xl.jsonl`
- training CSV: `data\autovit_xl.csv`
- model bundle: `data\model_results_xl_log\best_model.joblib`
- model output folder: `data\model_results_xl_log`

Latest XL training result:

- best model: `ridge`
- RMSE: about `5511.87 EUR`
- MAE: about `2920.33 EUR`
- R2: about `0.9225`

## 10. Troubleshooting

If `carvaluator-api` is not recognized, call the module directly:

```powershell
.\.venv\Scripts\python.exe -m carvaluator_scraper.api
```

If port `8000` is blocked, use another port:

```powershell
$env:CARVALUATOR_API_PORT = "8001"
.\.venv\Scripts\python.exe -m carvaluator_scraper.api
```

If the page only shows one model estimate, check `/health` and confirm the app is using:

```text
data\model_results_xl_log\best_model.joblib
```

If Autovit prediction fails for a specific link, the ad may have expired or Autovit may have changed/blocked the response. Try a fresh listing from the search page.

## 11. Thesis Notes

For the thesis write-up, the project can be described as:

1. web scraping from Autovit search/detail pages
2. raw JSONL storage
3. normalization and deduplication
4. CSV preparation for machine learning
5. statistical feature filtering
6. regression model comparison
7. log-price training
8. fair-price prediction from a live ad link
9. similar-listing retrieval with nearest-neighbor search
10. web interface for user-facing evaluation
