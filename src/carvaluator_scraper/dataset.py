from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from carvaluator_scraper.normalize import (
    NormalizationReport,
    NormalizedListing,
    load_jsonl,
    normalize_records,
)


CSV_COLUMNS = [
    "source",
    "source_listing_key",
    "listing_id",
    "url",
    "title",
    "make",
    "model",
    "version",
    "year",
    "first_registration_month",
    "first_registration_year",
    "mileage_km",
    "price_eur",
    "original_price_value",
    "original_currency",
    "market_price_label",
    "fuel_type",
    "transmission",
    "body_type",
    "power_hp",
    "engine_capacity_cm3",
    "seller_type",
    "seller_name",
    "location_city",
    "location_region",
    "scraped_at",
    "completeness_score",
    "dedupe_exact_key",
    "dedupe_fuzzy_key",
]


def prepare_dataframe_from_jsonl(
    inputs: Iterable[Path],
    *,
    drop_fuzzy_duplicates: bool = False,
) -> tuple[pd.DataFrame, NormalizationReport]:
    rows: list[dict[str, Any]] = []
    for path in inputs:
        rows.extend(load_jsonl(path))

    if rows and "source_listing_key" in rows[0]:
        normalized_rows = [NormalizedListing(**row) for row in rows]
        report = NormalizationReport(
            loaded_rows=len(normalized_rows),
            normalized_rows=len(normalized_rows),
            kept_rows=len(normalized_rows),
            exact_duplicates_removed=0,
            fuzzy_duplicates_removed=0,
            rows_missing_price=sum(1 for row in normalized_rows if row.price_eur is None),
            rows_missing_year=sum(1 for row in normalized_rows if row.year is None),
            rows_missing_mileage=sum(1 for row in normalized_rows if row.mileage_km is None),
        )
    else:
        normalized_rows, report = normalize_records(rows, drop_fuzzy_duplicates=drop_fuzzy_duplicates)

    frame = pd.DataFrame([row.to_dict() for row in normalized_rows])
    if frame.empty:
        return frame, report

    for column in CSV_COLUMNS:
        if column not in frame.columns:
            frame[column] = pd.NA

    frame = frame[CSV_COLUMNS]
    return frame, report


def save_dataframe_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8")


def save_json_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
