from __future__ import annotations

import os
import json
import re
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")

import joblib
import numpy as np
import pandas as pd

from carvaluator_scraper.models import CarListing
from carvaluator_scraper.normalize import NormalizedListing, normalize_record, normalize_url
from carvaluator_scraper.scrapers.autovit import AutovitFetchError, AutovitScraper
from carvaluator_scraper.scrapers.mobilede import MobileDeBlockedError, MobileDeScraper
from carvaluator_scraper.similarity import SimilarListing, find_similar_listings


DEFAULT_MOBILEDE_LOOKUP_URL = "https://suchen.mobile.de/fahrzeuge/search.html?dam=false&isSearchRequest=true&ref=quickSearch&s=Car&vc=Car"
ENSEMBLE_METHODS = {"inverse_mae", "inverse_mae_with_agreement"}
DEFAULT_ENSEMBLE_METHOD = "inverse_mae_with_agreement"


@dataclass(slots=True)
class PricePrediction:
    source: str
    url: str
    title: str
    image_url: str | None
    model_name: str
    actual_price_eur: float | None
    predicted_price_eur: float
    delta_eur: float | None
    delta_percent: float | None
    verdict: str
    threshold_percent: float
    selected_features: list[str]
    normalized_listing: dict[str, Any]
    similar_listings: list[dict[str, Any]]
    model_estimates: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_model_bundle(path: Path) -> dict[str, Any]:
    bundle = joblib.load(path)
    force_single_threaded_prediction(bundle.get("pipeline"))
    for pipeline in (bundle.get("all_pipelines") or {}).values():
        force_single_threaded_prediction(pipeline)
    return bundle


def force_single_threaded_prediction(estimator: Any) -> None:
    if estimator is None or not hasattr(estimator, "get_params") or not hasattr(estimator, "set_params"):
        return
    params = estimator.get_params(deep=True)
    single_thread_params = {name: 1 for name in params if name == "n_jobs" or name.endswith("__n_jobs")}
    if single_thread_params:
        estimator.set_params(**single_thread_params)
    for child in getattr(estimator, "estimators_", []) or []:
        force_single_threaded_prediction(child)
    for child in getattr(estimator, "estimators", []) or []:
        if isinstance(child, tuple) and len(child) == 2:
            force_single_threaded_prediction(child[1])


def predict_from_link(
    *,
    site: str,
    url: str,
    model_bundle_path: Path,
    threshold_percent: float = 15.0,
    similarity_csv_path: Path | None = None,
    similar_limit: int = 5,
    ensemble_method: str = DEFAULT_ENSEMBLE_METHOD,
) -> PricePrediction:
    ensemble_method = validate_ensemble_method(ensemble_method)
    normalized_site = site.casefold().replace("-", "").replace(".", "")
    if normalized_site == "autovit":
        validate_autovit_url(url)
        return predict_from_autovit_link(
            url=url,
            model_bundle_path=model_bundle_path,
            threshold_percent=threshold_percent,
            similarity_csv_path=similarity_csv_path,
            similar_limit=similar_limit,
            ensemble_method=ensemble_method,
        )
    if normalized_site in {"mobilede", "mobile"}:
        validate_mobilede_url(url)
        return predict_from_mobilede_link(
            url=url,
            model_bundle_path=model_bundle_path,
            threshold_percent=threshold_percent,
            similarity_csv_path=similarity_csv_path,
            similar_limit=similar_limit,
            ensemble_method=ensemble_method,
        )
    raise ValueError("Site-ul trebuie sa fie autovit sau mobilede.")


def predict_from_autovit_link(
    *,
    url: str,
    model_bundle_path: Path,
    threshold_percent: float = 15.0,
    similarity_csv_path: Path | None = None,
    similar_limit: int = 5,
    ensemble_method: str = DEFAULT_ENSEMBLE_METHOD,
) -> PricePrediction:
    scraper = AutovitScraper()
    try:
        listing = scraper.scrape_detail(url)
        normalized = normalize_record(listing.to_dict())
    except AutovitFetchError as exc:
        normalized = load_listing_from_similarity_csv(url=url, similarity_csv_path=similarity_csv_path)
        if normalized is None:
            raise ValueError(
                "Nu am putut descarca anuntul de pe Autovit in acest moment. "
                "Autovit a refuzat conexiunea, iar linkul nu exista in baza locala de date. "
                "Incearca un anunt proaspat sau ruleaza din nou scraperul."
            ) from exc
    return predict_normalized_listing(
        normalized=normalized,
        model_bundle_path=model_bundle_path,
        threshold_percent=threshold_percent,
        similarity_csv_path=similarity_csv_path,
        similar_limit=similar_limit,
        ensemble_method=ensemble_method,
    )


def validate_autovit_url(url: str) -> None:
    parsed = urlparse(url)
    host = parsed.netloc.casefold()
    if parsed.scheme not in {"http", "https"} or not host.endswith("autovit.ro"):
        raise ValueError("Te rog introdu un link valid de pe autovit.ro.")


def validate_mobilede_url(url: str) -> None:
    parsed = urlparse(url)
    host = parsed.netloc.casefold()
    if parsed.scheme not in {"http", "https"} or not host.endswith("mobile.de"):
        raise ValueError("Te rog introdu un link valid de pe mobile.de.")
    if not extract_mobilede_listing_id(url):
        raise ValueError("Linkul mobile.de nu contine un ID de anunt pe care il pot identifica.")


def validate_ensemble_method(method: str) -> str:
    normalized = (method or DEFAULT_ENSEMBLE_METHOD).strip().casefold().replace("-", "_")
    if normalized not in ENSEMBLE_METHODS:
        raise ValueError("Metoda de combinare trebuie sa fie inverse_mae sau inverse_mae_with_agreement.")
    return normalized


def predict_from_mobilede_link(
    *,
    url: str,
    model_bundle_path: Path,
    threshold_percent: float = 15.0,
    similarity_csv_path: Path | None = None,
    similar_limit: int = 5,
    ensemble_method: str = DEFAULT_ENSEMBLE_METHOD,
) -> PricePrediction:
    listing_id = extract_mobilede_listing_id(url)
    normalized = load_listing_from_similarity_csv(
        url=url,
        similarity_csv_path=similarity_csv_path,
        source="mobilede",
        listing_id=listing_id,
    )
    if normalized is None:
        normalized = load_mobilede_listing_from_local_datasets(url=url, listing_id=listing_id)
    if normalized is None:
        normalized = scrape_mobilede_listing_from_detail(url=url)
    if normalized is None:
        normalized = scrape_mobilede_listing_from_search(listing_id=listing_id)
    if normalized is None:
        raise ValueError(
            "Nu am gasit anuntul mobile.de in baza locala si nu l-am putut citi nici din pagina de detalii, "
            "nici din cautarea live. "
            "Ruleaza scraperul mobile.de pentru cautarea care contine acest anunt, exporta CSV-ul, apoi seteaza "
            "CARVALUATOR_SIMILARITY_CSV catre acel CSV sau combina-l cu datasetul principal."
        )

    return predict_normalized_listing(
        normalized=normalized,
        model_bundle_path=model_bundle_path,
        threshold_percent=threshold_percent,
        similarity_csv_path=similarity_csv_path,
        similar_limit=similar_limit,
        ensemble_method=ensemble_method,
    )


def extract_mobilede_listing_id(url: str) -> str | None:
    parsed = urlparse(url)
    query_id = parse_qs(parsed.query).get("id")
    if query_id and query_id[0].isdigit():
        return query_id[0]
    match = re.search(r"/(\d{6,})\.html$", parsed.path)
    if match:
        return match.group(1)
    fallback = re.search(r"(\d{6,})", url)
    return fallback.group(1) if fallback else None


def scrape_mobilede_listing_from_detail(*, url: str) -> NormalizedListing | None:
    scraper = MobileDeScraper()
    try:
        listing = scraper.scrape_detail(url)
    except (MobileDeBlockedError, OSError, ValueError):
        return None
    return normalize_record(listing.to_dict())


def scrape_mobilede_listing_from_search(*, listing_id: str | None) -> NormalizedListing | None:
    if not listing_id:
        return None
    pages = int(os.getenv("CARVALUATOR_MOBILEDE_LOOKUP_PAGES", "5"))
    search_url = os.getenv("CARVALUATOR_MOBILEDE_LOOKUP_URL", DEFAULT_MOBILEDE_LOOKUP_URL)
    scraper = MobileDeScraper()
    try:
        rows = scraper.scrape_search(search_url, pages=pages, delay_seconds=0.5)
    except MobileDeBlockedError:
        return None
    for row in rows:
        if row.listing_id == listing_id:
            return normalize_record(row.to_dict())
    return None


def load_mobilede_listing_from_local_datasets(*, url: str, listing_id: str | None) -> NormalizedListing | None:
    configured = os.getenv("CARVALUATOR_MOBILEDE_DATASETS")
    if configured:
        paths = [Path(item.strip()) for item in configured.split(os.pathsep) if item.strip()]
    else:
        data_dir = Path.cwd() / "data"
        paths = sorted(data_dir.glob("mobilede*.jsonl")) + sorted(data_dir.glob("mobilede*.csv"))

    target_url = normalize_url(url)
    for path in paths:
        if not path.exists():
            continue
        if path.suffix.casefold() == ".jsonl":
            match = load_mobilede_listing_from_jsonl(path=path, target_url=target_url, listing_id=listing_id)
            if match is not None:
                return match
        elif path.suffix.casefold() == ".csv":
            match = load_listing_from_similarity_csv(
                url=url,
                similarity_csv_path=path,
                source="mobilede",
                listing_id=listing_id,
            )
            if match is not None:
                return match
    return None


def load_mobilede_listing_from_jsonl(
    *,
    path: Path,
    target_url: str,
    listing_id: str | None,
) -> NormalizedListing | None:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("source") != "mobilede":
                continue
            row_id = str(row.get("listing_id") or "")
            row_url = normalize_url(row.get("url") or "")
            if (listing_id and row_id == str(listing_id)) or (target_url and row_url == target_url):
                return normalize_record(row)
    return None


def load_listing_from_similarity_csv(
    *,
    url: str,
    similarity_csv_path: Path | None,
    source: str | None = None,
    listing_id: str | None = None,
) -> NormalizedListing | None:
    if similarity_csv_path is None or not similarity_csv_path.exists():
        return None
    frame = pd.read_csv(similarity_csv_path)
    if "url" not in frame.columns:
        return None
    target_url = normalize_url(url)
    matches = frame[frame["url"].fillna("").map(normalize_url).eq(target_url)]
    if listing_id and "listing_id" in frame.columns:
        id_matches = frame[frame["listing_id"].fillna("").astype(str).eq(str(listing_id))]
        matches = pd.concat([matches, id_matches]).drop_duplicates()
    if source and "source" in matches.columns:
        matches = matches[matches["source"].fillna("").astype(str).str.casefold().eq(source.casefold())]
    if matches.empty:
        return None
    payload = {key: none_if_missing(value) for key, value in matches.iloc[0].to_dict().items()}
    payload.setdefault("raw", {})
    allowed_fields = {field.name for field in fields(NormalizedListing)}
    filtered_payload = {key: value for key, value in payload.items() if key in allowed_fields}
    return NormalizedListing(**filtered_payload)


def none_if_missing(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    return value


def predict_normalized_listing(
    *,
    normalized: NormalizedListing,
    model_bundle_path: Path,
    threshold_percent: float = 15.0,
    similarity_csv_path: Path | None = None,
    similar_limit: int = 5,
    ensemble_method: str = DEFAULT_ENSEMBLE_METHOD,
) -> PricePrediction:
    ensemble_method = validate_ensemble_method(ensemble_method)
    bundle = load_model_bundle(model_bundle_path)
    pipeline = bundle["pipeline"]
    all_pipelines: dict[str, Any] = bundle.get("all_pipelines") or {bundle.get("model_name", "best_model"): pipeline}
    selected_features: list[str] = bundle["selected_features"]
    log_target: bool = bundle.get("log_target", False)
    model_name: str = bundle.get("model_name", "unknown_model")
    metrics_by_model = {item["model"]: item for item in bundle.get("metrics", [])}

    frame = pd.DataFrame([build_feature_payload(normalized, selected_features)])
    normalized_payload = normalized.to_dict()
    normalized_payload.pop("raw", None)
    image_url = extract_primary_image_url(normalized.raw)
    similar_listings_payload: list[dict[str, Any]] = []
    if similarity_csv_path is not None and similar_limit > 0 and similarity_csv_path.exists():
        similar_listings_payload = [
            listing.to_dict()
            for listing in find_similar_listings(
                normalized,
                csv_path=similarity_csv_path,
                limit=similar_limit,
            )
        ]

    model_estimates_payload = build_model_estimates(
        frame=frame,
        all_pipelines=all_pipelines,
        metrics_by_model=metrics_by_model,
        log_target=log_target,
        best_model_name=model_name,
    )
    predicted_price = compute_weighted_model_prediction(model_estimates_payload, ensemble_method=ensemble_method)
    model_estimates_payload.insert(
        0,
        {
            "model": "weighted_average",
            "predicted_price_eur": predicted_price,
            "rmse": None,
            "mae": None,
            "r2": None,
            "cv_rmse": None,
            "is_best_model": True,
            "weighting": ensemble_method,
            "excluded_models": ["voting_ensemble"],
        }
    )

    actual_price = normalized.price_eur
    delta_eur = actual_price - predicted_price if actual_price is not None else None
    delta_percent = ((delta_eur / predicted_price) * 100.0) if (delta_eur is not None and predicted_price > 0) else None
    verdict = classify_price(
        actual_price_eur=actual_price,
        predicted_price_eur=predicted_price,
        threshold_percent=threshold_percent,
    )

    return PricePrediction(
        source=normalized.source,
        url=normalized.url,
        title=normalized.title,
        image_url=image_url,
        model_name="weighted_average",
        actual_price_eur=actual_price,
        predicted_price_eur=predicted_price,
        delta_eur=delta_eur,
        delta_percent=delta_percent,
        verdict=verdict,
        threshold_percent=threshold_percent,
        selected_features=selected_features,
        normalized_listing=normalized_payload,
        similar_listings=similar_listings_payload,
        model_estimates=model_estimates_payload,
    )


def extract_primary_image_url(raw: dict[str, Any]) -> str | None:
    for key in ("image_url", "previewImage"):
        candidate = raw.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    api_item = raw.get("api_item") if isinstance(raw.get("api_item"), dict) else {}
    preview_image = api_item.get("previewImage") if isinstance(api_item.get("previewImage"), dict) else {}
    candidate = preview_image.get("src")
    if isinstance(candidate, str) and candidate.strip():
        return candidate
    images = raw.get("images") or {}
    photos = images.get("photos") or []
    for photo in photos:
        if not isinstance(photo, dict):
            continue
        candidate = photo.get("url") or photo.get("id")
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return None


def build_feature_payload(normalized: NormalizedListing, selected_features: list[str]) -> dict[str, Any]:
    current_year = datetime.now(timezone.utc).year
    vehicle_age = current_year - normalized.year if normalized.year else None
    if vehicle_age is not None and vehicle_age < 0:
        vehicle_age = 0
    mileage_per_year = (
        normalized.mileage_km / vehicle_age
        if normalized.mileage_km is not None and vehicle_age not in (None, 0)
        else None
    )
    hp_per_liter = (
        normalized.power_hp / (normalized.engine_capacity_cm3 / 1000.0)
        if normalized.power_hp is not None and normalized.engine_capacity_cm3 not in (None, 0)
        else None
    )
    engineered = {
        "make_model": " ".join(part for part in [normalized.make, normalized.model] if part) or None,
        "vehicle_age": vehicle_age,
        "mileage_per_year": mileage_per_year,
        "hp_per_liter": hp_per_liter,
    }
    return {
        feature: engineered.get(feature, getattr(normalized, feature, None))
        for feature in selected_features
    }


def build_model_estimates(
    *,
    frame: pd.DataFrame,
    all_pipelines: dict[str, Any],
    metrics_by_model: dict[str, dict[str, Any]],
    log_target: bool,
    best_model_name: str,
) -> list[dict[str, Any]]:
    estimates: list[dict[str, Any]] = []
    for name, candidate_pipeline in all_pipelines.items():
        raw_prediction = float(candidate_pipeline.predict(frame)[0])
        predicted_price = float(np.expm1(raw_prediction)) if log_target else raw_prediction
        predicted_price = max(predicted_price, 0.0)
        metric = metrics_by_model.get(name, {})
        estimates.append(
            {
                "model": name,
                "predicted_price_eur": predicted_price,
                "rmse": metric.get("rmse"),
                "mae": metric.get("mae"),
                "r2": metric.get("r2"),
                "cv_rmse": metric.get("cv_rmse"),
                "is_best_model": False,
            }
        )
    estimates.sort(key=lambda item: (item["rmse"] is None, item["rmse"] if item["rmse"] is not None else float("inf")))
    return estimates


def compute_weighted_model_prediction(
    model_estimates: list[dict[str, Any]],
    *,
    ensemble_method: str = DEFAULT_ENSEMBLE_METHOD,
) -> float:
    ensemble_method = validate_ensemble_method(ensemble_method)
    candidates = [
        estimate
        for estimate in model_estimates
        if estimate.get("model") != "voting_ensemble"
        and estimate.get("predicted_price_eur") is not None
        and float(estimate.get("predicted_price_eur") or 0.0) > 0
    ]
    if not candidates:
        fallback = next((estimate for estimate in model_estimates if estimate.get("predicted_price_eur") is not None), None)
        return float(fallback["predicted_price_eur"]) if fallback else 0.0

    if ensemble_method == "inverse_mae_with_agreement":
        prices = np.array([float(estimate["predicted_price_eur"]) for estimate in candidates], dtype=float)
        median_prediction = float(np.median(prices))
        absolute_deviations = np.abs(prices - median_prediction)
        median_absolute_deviation = float(np.median(absolute_deviations))
        disagreement_scale = max(median_absolute_deviation * 2.5, median_prediction * 0.15, 1.0)
    else:
        median_prediction = 0.0
        disagreement_scale = 1.0

    weights: list[float] = []
    for estimate in candidates:
        mae = estimate.get("mae")
        if mae is not None and float(mae) > 0:
            performance_weight = 1.0 / float(mae)
        else:
            rmse = estimate.get("rmse")
            performance_weight = 1.0 / float(rmse) if rmse is not None and float(rmse) > 0 else 1.0
        prediction = float(estimate["predicted_price_eur"])
        agreement_weight = (
            float(np.exp(-abs(prediction - median_prediction) / disagreement_scale))
            if ensemble_method == "inverse_mae_with_agreement"
            else 1.0
        )
        weight = performance_weight * agreement_weight
        if ensemble_method == "inverse_mae_with_agreement":
            estimate["agreement_weight"] = agreement_weight
        weights.append(weight)

    weight_sum = sum(weights)
    if weight_sum <= 0:
        return float(np.mean([float(estimate["predicted_price_eur"]) for estimate in candidates]))

    for estimate, weight in zip(candidates, weights):
        estimate["ensemble_weight"] = float(weight / weight_sum)

    return float(
        sum(float(estimate["predicted_price_eur"]) * weight for estimate, weight in zip(candidates, weights)) / weight_sum
    )


def classify_price(
    *,
    actual_price_eur: float | None,
    predicted_price_eur: float,
    threshold_percent: float,
) -> str:
    if actual_price_eur is None or predicted_price_eur <= 0:
        return "unknown"

    lower_bound = predicted_price_eur * (1.0 - (threshold_percent / 100.0))
    upper_bound = predicted_price_eur * (1.0 + (threshold_percent / 100.0))
    if actual_price_eur < lower_bound:
        return "too_low_suspicious"
    if actual_price_eur > upper_bound:
        return "too_high"
    return "fair"
