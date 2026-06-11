from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.neighbors import NearestNeighbors
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from carvaluator_scraper.normalize import NormalizedListing


SIMILARITY_NUMERIC_COLUMNS = [
    "year",
    "mileage_km",
    "power_hp",
    "engine_capacity_cm3",
    "price_eur",
]

SIMILARITY_CATEGORICAL_COLUMNS = [
    "make",
    "model",
    "version",
    "fuel_type",
    "transmission",
    "body_type",
    "seller_type",
]

SIMILARITY_OUTPUT_COLUMNS = [
    "source_listing_key",
    "listing_id",
    "url",
    "title",
    "make",
    "model",
    "version",
    "year",
    "mileage_km",
    "price_eur",
    "fuel_type",
    "transmission",
    "body_type",
    "power_hp",
    "engine_capacity_cm3",
    "seller_type",
    "seller_name",
    "location_city",
    "location_region",
]


@dataclass(slots=True)
class SimilarListing:
    title: str
    url: str
    price_eur: float | None
    year: int | None
    mileage_km: int | None
    fuel_type: str | None
    transmission: str | None
    power_hp: int | None
    engine_capacity_cm3: int | None
    location_city: str | None
    seller_type: str | None
    similarity_score: float
    match_quality: str
    match_reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SimilarityFinder:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame.copy()
        self.feature_columns = [
            column
            for column in SIMILARITY_NUMERIC_COLUMNS + SIMILARITY_CATEGORICAL_COLUMNS
            if column in self.frame.columns
        ]
        self.numeric_columns = [column for column in SIMILARITY_NUMERIC_COLUMNS if column in self.feature_columns]
        self.categorical_columns = [column for column in SIMILARITY_CATEGORICAL_COLUMNS if column in self.feature_columns]

    def find_similar(
        self,
        query: NormalizedListing,
        *,
        limit: int = 5,
    ) -> list[SimilarListing]:
        if self.frame.empty:
            return []

        candidate_frame = self._select_candidate_pool(query)
        if candidate_frame.empty:
            return []

        limit = max(1, limit)
        max_neighbors = min(len(candidate_frame), max(limit + 1, 12))
        transformed_frame = candidate_frame[self.feature_columns].copy()
        query_frame = pd.DataFrame([{column: getattr(query, column, None) for column in self.feature_columns}])

        preprocessor = self._build_preprocessor(candidate_frame)
        candidate_matrix = preprocessor.fit_transform(transformed_frame)
        query_matrix = preprocessor.transform(query_frame)

        model = NearestNeighbors(n_neighbors=max_neighbors, metric="euclidean")
        model.fit(candidate_matrix)
        distances, indices = model.kneighbors(query_matrix)

        results: list[SimilarListing] = []
        query_key = query.source_listing_key
        for distance, index in zip(distances[0], indices[0]):
            row = candidate_frame.iloc[int(index)]
            if row.get("source_listing_key") == query_key or row.get("url") == query.url:
                continue
            results.append(
                SimilarListing(
                    title=str(row.get("title") or "Untitled Listing"),
                    url=str(row.get("url") or ""),
                    price_eur=_float_or_none(row.get("price_eur")),
                    year=_int_or_none(row.get("year")),
                    mileage_km=_int_or_none(row.get("mileage_km")),
                    fuel_type=_str_or_none(row.get("fuel_type")),
                    transmission=_str_or_none(row.get("transmission")),
                    power_hp=_int_or_none(row.get("power_hp")),
                    engine_capacity_cm3=_int_or_none(row.get("engine_capacity_cm3")),
                    location_city=_str_or_none(row.get("location_city")),
                    seller_type=_str_or_none(row.get("seller_type")),
                    similarity_score=round(_distance_to_similarity(distance), 1),
                    match_quality=self._match_quality(query, row),
                    match_reasons=self._match_reasons(query, row),
                )
            )
            if len(results) >= limit:
                break
        return results

    def _select_candidate_pool(self, query: NormalizedListing) -> pd.DataFrame:
        pool = self.frame
        if query.make and query.model:
            same_model = pool[
                pool["make"].fillna("").str.casefold().eq(str(query.make).casefold())
                & pool["model"].fillna("").str.casefold().eq(str(query.model).casefold())
            ]
            if len(same_model) >= 5:
                return same_model.reset_index(drop=True)
        if query.make:
            same_make = pool[pool["make"].fillna("").str.casefold().eq(str(query.make).casefold())]
            if len(same_make) >= 8:
                return same_make.reset_index(drop=True)
        return pool.reset_index(drop=True)

    def _build_preprocessor(self, candidate_frame: pd.DataFrame) -> ColumnTransformer:
        active_numeric_columns = [column for column in self.numeric_columns if candidate_frame[column].notna().any()]
        active_categorical_columns = [column for column in self.categorical_columns if candidate_frame[column].notna().any()]

        numeric_pipeline = Pipeline(
            steps=[
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
            ]
        )
        categorical_pipeline = Pipeline(
            steps=[
                ("imputer", SimpleImputer(strategy="most_frequent")),
                ("onehot", OneHotEncoder(handle_unknown="ignore")),
            ]
        )
        return ColumnTransformer(
            transformers=[
                ("num", numeric_pipeline, active_numeric_columns),
                ("cat", categorical_pipeline, active_categorical_columns),
            ],
            remainder="drop",
        )

    def _match_reasons(self, query: NormalizedListing, row: pd.Series) -> list[str]:
        reasons: list[str] = []
        if _text_equals(query.make, row.get("make")):
            reasons.append("same make")
        if _text_equals(query.model, row.get("model")):
            reasons.append("same model")
        if _text_equals(query.fuel_type, row.get("fuel_type")):
            reasons.append("same fuel")
        if _text_equals(query.transmission, row.get("transmission")):
            reasons.append("same gearbox")
        if _close_numeric(query.year, row.get("year"), tolerance=1):
            reasons.append("year within 1")
        if _close_numeric(query.mileage_km, row.get("mileage_km"), tolerance=25000):
            reasons.append("mileage within 25k km")
        if _close_numeric(query.power_hp, row.get("power_hp"), tolerance=20):
            reasons.append("power within 20 hp")
        if _close_numeric(query.engine_capacity_cm3, row.get("engine_capacity_cm3"), tolerance=250):
            reasons.append("engine within 250 cm3")
        return reasons[:4]

    def _match_quality(self, query: NormalizedListing, row: pd.Series) -> str:
        reasons = self._match_reasons(query, row)
        if "same model" in reasons and "mileage within 25k km" in reasons:
            return "very_close"
        if len(reasons) >= 3:
            return "close"
        return "broad_match"


@lru_cache(maxsize=4)
def load_similarity_finder(csv_path: Path) -> SimilarityFinder:
    frame = pd.read_csv(csv_path)
    for column in SIMILARITY_OUTPUT_COLUMNS:
        if column not in frame.columns:
            frame[column] = pd.NA
    cleaned_frame = frame[SIMILARITY_OUTPUT_COLUMNS].copy()
    cleaned_frame = cleaned_frame.dropna(subset=["url", "title"])
    return SimilarityFinder(cleaned_frame)


def find_similar_listings(
    normalized: NormalizedListing,
    *,
    csv_path: Path,
    limit: int = 5,
) -> list[SimilarListing]:
    finder = load_similarity_finder(csv_path.resolve())
    return finder.find_similar(normalized, limit=limit)


def _distance_to_similarity(distance: float) -> float:
    return float(max(0.0, min(100.0, np.exp(-float(distance) / 2.2) * 100.0)))


def _close_numeric(left: Any, right: Any, *, tolerance: int | float) -> bool:
    left_value = _float_or_none(left)
    right_value = _float_or_none(right)
    if left_value is None or right_value is None:
        return False
    return abs(left_value - right_value) <= tolerance


def _text_equals(left: Any, right: Any) -> bool:
    if left in (None, "") or right in (None, ""):
        return False
    return str(left).casefold() == str(right).casefold()


def _float_or_none(value: Any) -> float | None:
    if pd.isna(value):
        return None
    if value is None:
        return None
    return float(value)


def _int_or_none(value: Any) -> int | None:
    parsed = _float_or_none(value)
    if parsed is None:
        return None
    return int(round(parsed))


def _str_or_none(value: Any) -> str | None:
    if pd.isna(value) or value in (None, ""):
        return None
    return str(value)
