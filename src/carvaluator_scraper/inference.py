from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from carvaluator_scraper.models import CarListing
from carvaluator_scraper.normalize import NormalizedListing, normalize_record
from carvaluator_scraper.scrapers.autovit import AutovitScraper


@dataclass(slots=True)
class PricePrediction:
    source: str
    url: str
    title: str
    model_name: str
    actual_price_eur: float | None
    predicted_price_eur: float
    delta_eur: float | None
    delta_percent: float | None
    verdict: str
    threshold_percent: float
    selected_features: list[str]
    normalized_listing: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_model_bundle(path: Path) -> dict[str, Any]:
    return joblib.load(path)


def predict_from_link(
    *,
    site: str,
    url: str,
    model_bundle_path: Path,
    threshold_percent: float = 15.0,
) -> PricePrediction:
    if site != "autovit":
        raise ValueError("Only autovit is currently supported for predict-from-link.")
    return predict_from_autovit_link(
        url=url,
        model_bundle_path=model_bundle_path,
        threshold_percent=threshold_percent,
    )


def predict_from_autovit_link(
    *,
    url: str,
    model_bundle_path: Path,
    threshold_percent: float = 15.0,
) -> PricePrediction:
    scraper = AutovitScraper()
    listing = scraper.scrape_detail(url)
    normalized = normalize_record(listing.to_dict())
    return predict_normalized_listing(
        normalized=normalized,
        model_bundle_path=model_bundle_path,
        threshold_percent=threshold_percent,
    )


def predict_normalized_listing(
    *,
    normalized: NormalizedListing,
    model_bundle_path: Path,
    threshold_percent: float = 15.0,
) -> PricePrediction:
    bundle = load_model_bundle(model_bundle_path)
    pipeline = bundle["pipeline"]
    selected_features: list[str] = bundle["selected_features"]
    log_target: bool = bundle.get("log_target", False)
    model_name: str = bundle.get("model_name", "unknown_model")

    frame = pd.DataFrame([{feature: getattr(normalized, feature, None) for feature in selected_features}])
    raw_prediction = float(pipeline.predict(frame)[0])
    predicted_price = float(np.expm1(raw_prediction)) if log_target else raw_prediction
    predicted_price = max(predicted_price, 0.0)

    actual_price = normalized.price_eur
    delta_eur = actual_price - predicted_price if actual_price is not None else None
    delta_percent = ((delta_eur / predicted_price) * 100.0) if (delta_eur is not None and predicted_price > 0) else None
    verdict = classify_price(
        actual_price_eur=actual_price,
        predicted_price_eur=predicted_price,
        threshold_percent=threshold_percent,
    )
    normalized_payload = normalized.to_dict()
    normalized_payload.pop("raw", None)

    return PricePrediction(
        source=normalized.source,
        url=normalized.url,
        title=normalized.title,
        model_name=model_name,
        actual_price_eur=actual_price,
        predicted_price_eur=predicted_price,
        delta_eur=delta_eur,
        delta_percent=delta_percent,
        verdict=verdict,
        threshold_percent=threshold_percent,
        selected_features=selected_features,
        normalized_listing=normalized_payload,
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
