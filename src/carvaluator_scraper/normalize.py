from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from carvaluator_scraper.utils import clean_whitespace, ensure_parent_dir, parse_float, parse_int


KNOWN_MAKES = [
    "Mercedes-Benz",
    "Land Rover",
    "Alfa Romeo",
    "Aston Martin",
    "Rolls-Royce",
    "Volkswagen",
    "Mercedes",
    "Citroën",
    "Citroen",
    "Peugeot",
    "Renault",
    "Toyota",
    "Hyundai",
    "Porsche",
    "Suzuki",
    "Nissan",
    "Dacia",
    "Skoda",
    "Volvo",
    "Honda",
    "Tesla",
    "Mazda",
    "Audi",
    "Ford",
    "Seat",
    "Mini",
    "BMW",
    "Kia",
    "Jeep",
    "Fiat",
    "Opel",
]

FUEL_MAP = {
    "diesel": "diesel",
    "motorina": "diesel",
    "benzin": "petrol",
    "benzina": "petrol",
    "petrol": "petrol",
    "hybrid": "hybrid",
    "hibrid": "hybrid",
    "hibrid-plug-in": "plug_in_hybrid",
    "hibrid-plug--in": "plug_in_hybrid",
    "plug-in-hybrid": "plug_in_hybrid",
    "electro": "electric",
    "electric": "electric",
    "lpg": "lpg",
    "gpl": "lpg",
    "cng": "cng",
}

TRANSMISSION_MAP = {
    "automata": "automatic",
    "automatic": "automatic",
    "automat": "automatic",
    "manuala": "manual",
    "manual": "manual",
    "schaltgetriebe": "manual",
    "halbautomatik": "semi_automatic",
    "semiautomatic": "semi_automatic",
}

BODY_TYPE_MAP = {
    "masina-mica": "small_car",
    "autovehicul-mic": "small_car",
    "mini": "small_car",
    "suv": "suv",
    "sedan": "sedan",
    "break": "wagon",
    "wagon": "wagon",
    "kombi": "wagon",
    "combi": "wagon",
    "hatchback": "hatchback",
    "cabrio": "convertible",
    "convertible": "convertible",
    "coupe": "coupe",
    "van": "van",
    "monovolum": "minivan",
}

PRICE_INDICATOR_MAP = {
    "below": "low",
    "in": "fair",
    "above": "high",
    "none": None,
    "sehr-guter-preis": "low",
    "guter-preis": "low",
    "fairer-preis": "fair",
    "hoher-preis": "high",
    "erhohter-preis": "high",
    "ohne-bewertung": None,
    "pret-foarte-bun": "low",
    "pret-bun": "low",
    "pret-corect": "fair",
    "pret-ridicat": "high",
    "pret-mare": "high",
}

SELLER_TYPE_MAP = {
    "professionalseller": "dealer",
    "professional": "dealer",
    "dealer": "dealer",
    "private": "private",
    "for-sale-by-owner": "private",
}


@dataclass(slots=True)
class NormalizedListing:
    source: str
    source_listing_key: str
    url: str
    title: str
    make: str | None = None
    model: str | None = None
    version: str | None = None
    year: int | None = None
    first_registration_month: int | None = None
    first_registration_year: int | None = None
    mileage_km: int | None = None
    price_eur: float | None = None
    original_price_value: float | None = None
    original_currency: str | None = None
    market_price_label: str | None = None
    fuel_type: str | None = None
    transmission: str | None = None
    body_type: str | None = None
    power_hp: int | None = None
    engine_capacity_cm3: int | None = None
    seller_type: str | None = None
    seller_name: str | None = None
    location_city: str | None = None
    location_region: str | None = None
    listing_id: str | None = None
    scraped_at: str | None = None
    completeness_score: int = 0
    dedupe_exact_key: str | None = None
    dedupe_fuzzy_key: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class NormalizationReport:
    loaded_rows: int
    normalized_rows: int
    kept_rows: int
    exact_duplicates_removed: int
    fuzzy_duplicates_removed: int
    rows_missing_price: int
    rows_missing_year: int
    rows_missing_mileage: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_normalized_jsonl(path: Path, rows: Iterable[NormalizedListing]) -> None:
    ensure_parent_dir(path)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row.to_dict(), ensure_ascii=False) + "\n")


def write_report(path: Path, report: NormalizationReport) -> None:
    ensure_parent_dir(path)
    path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_records(
    rows: Iterable[dict[str, Any]],
    *,
    drop_fuzzy_duplicates: bool = False,
) -> tuple[list[NormalizedListing], NormalizationReport]:
    normalized_rows = [normalize_record(row) for row in rows]
    exact_kept: dict[str, NormalizedListing] = {}
    exact_duplicates_removed = 0

    for row in normalized_rows:
        key = row.dedupe_exact_key or row.source_listing_key
        existing = exact_kept.get(key)
        if existing is None or _prefer_candidate(row, existing):
            if existing is not None:
                exact_duplicates_removed += 1
            exact_kept[key] = row
        else:
            exact_duplicates_removed += 1

    kept_rows = list(exact_kept.values())
    fuzzy_duplicates_removed = 0
    if drop_fuzzy_duplicates:
        fuzzy_kept: dict[str, NormalizedListing] = {}
        final_rows: list[NormalizedListing] = []
        for row in kept_rows:
            if not row.dedupe_fuzzy_key:
                final_rows.append(row)
                continue
            existing = fuzzy_kept.get(row.dedupe_fuzzy_key)
            if existing is None or _prefer_candidate(row, existing):
                if existing is not None:
                    fuzzy_duplicates_removed += 1
                    final_rows.remove(existing)
                fuzzy_kept[row.dedupe_fuzzy_key] = row
                final_rows.append(row)
            else:
                fuzzy_duplicates_removed += 1
        kept_rows = final_rows

    report = NormalizationReport(
        loaded_rows=len(normalized_rows),
        normalized_rows=len(normalized_rows),
        kept_rows=len(kept_rows),
        exact_duplicates_removed=exact_duplicates_removed,
        fuzzy_duplicates_removed=fuzzy_duplicates_removed,
        rows_missing_price=sum(1 for row in kept_rows if row.price_eur is None),
        rows_missing_year=sum(1 for row in kept_rows if row.year is None),
        rows_missing_mileage=sum(1 for row in kept_rows if row.mileage_km is None),
    )
    return kept_rows, report


def normalize_record(row: dict[str, Any]) -> NormalizedListing:
    raw = row.get("raw") or {}
    source = row.get("source") or "unknown"
    title = clean_whitespace(row.get("title")) or ""

    make = clean_whitespace(row.get("make")) or _extract_site_value(source, raw, "make")
    model = clean_whitespace(row.get("model")) or _extract_site_value(source, raw, "model")
    version = clean_whitespace(row.get("version")) or _extract_site_value(source, raw, "version")
    if not make or not model:
        inferred_make, inferred_model, inferred_version = infer_make_model_version(title)
        make = make or inferred_make
        model = model or inferred_model
        version = version or inferred_version

    first_registration = clean_whitespace(row.get("first_registration"))
    registration_month, registration_year = parse_registration(first_registration)
    year = _coerce_int(_extract_site_value(source, raw, "year")) or _coerce_int(row.get("year")) or registration_year

    original_currency = clean_whitespace(row.get("currency"))
    original_price_value = _extract_raw_price(source, raw)
    if original_price_value is None:
        original_price_value = _coerce_float(row.get("price_value"))
    price_eur = original_price_value if (original_currency or "").upper() == "EUR" else None

    normalized = NormalizedListing(
        source=source,
        source_listing_key=build_source_listing_key(source, row),
        url=row.get("url") or "",
        title=title,
        make=normalize_make(make),
        model=normalize_text(model, title_case=False),
        version=clean_whitespace(version),
        year=year,
        first_registration_month=registration_month,
        first_registration_year=registration_year,
        mileage_km=_coerce_int(_extract_site_value(source, raw, "mileage")) or _coerce_int(row.get("mileage_km")),
        price_eur=price_eur,
        original_price_value=original_price_value,
        original_currency=original_currency,
        market_price_label=normalize_enum(row.get("price_indicator"), PRICE_INDICATOR_MAP),
        fuel_type=normalize_enum(_extract_site_value(source, raw, "fuel_type") or row.get("fuel_type"), FUEL_MAP),
        transmission=normalize_enum(_extract_site_value(source, raw, "gearbox") or row.get("transmission"), TRANSMISSION_MAP),
        body_type=normalize_enum(_extract_site_value(source, raw, "body_type") or row.get("body_type"), BODY_TYPE_MAP),
        power_hp=_coerce_int(_extract_site_value(source, raw, "engine_power")) or _coerce_int(row.get("power_hp")),
        engine_capacity_cm3=_coerce_int(_extract_site_value(source, raw, "engine_capacity")) or _coerce_int(row.get("engine_capacity_cm3")),
        seller_type=normalize_enum(row.get("seller_type"), SELLER_TYPE_MAP),
        seller_name=clean_whitespace(row.get("seller_name")),
        location_city=normalize_text(row.get("location_city"), title_case=True),
        location_region=normalize_text(row.get("location_region"), title_case=True),
        listing_id=clean_whitespace(row.get("listing_id")),
        scraped_at=clean_whitespace(row.get("scraped_at")),
        raw=raw,
    )
    normalized.completeness_score = compute_completeness_score(normalized)
    normalized.dedupe_exact_key = build_exact_dedupe_key(normalized)
    normalized.dedupe_fuzzy_key = build_fuzzy_dedupe_key(normalized)
    return normalized


def infer_make_model_version(title: str) -> tuple[str | None, str | None, str | None]:
    cleaned = clean_whitespace(title) or ""
    if not cleaned:
        return None, None, None
    for make in sorted(KNOWN_MAKES, key=len, reverse=True):
        if cleaned.lower().startswith(make.lower() + " ") or cleaned.lower() == make.lower():
            remainder = cleaned[len(make):].strip()
            model, version = split_model_and_version(remainder)
            return make, model, version
    parts = cleaned.split()
    if not parts:
        return None, None, None
    model, version = split_model_and_version(" ".join(parts[1:]))
    return parts[0], model, version


def split_model_and_version(remainder: str) -> tuple[str | None, str | None]:
    remainder = clean_whitespace(remainder) or ""
    if not remainder:
        return None, None
    tokens = remainder.split()
    if tokens[0].lower() in {"seria", "series"} and len(tokens) >= 2:
        return " ".join(tokens[:2]), " ".join(tokens[2:]) or None
    return tokens[0], " ".join(tokens[1:]) or None


def parse_registration(value: str | None) -> tuple[int | None, int | None]:
    if not value:
        return None, None
    match = re.fullmatch(r"(\d{2})/(\d{4})", value)
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def build_source_listing_key(source: str, row: dict[str, Any]) -> str:
    listing_id = clean_whitespace(row.get("listing_id"))
    if listing_id:
        return f"{source}:{listing_id}"
    return f"{source}:{normalize_url(row.get('url') or '')}"


def build_exact_dedupe_key(row: NormalizedListing) -> str:
    if row.listing_id:
        return f"{row.source}:{row.listing_id}"
    return f"{row.source}:{normalize_url(row.url)}"


def build_fuzzy_dedupe_key(row: NormalizedListing) -> str | None:
    if not all([row.make, row.model, row.year, row.mileage_km, row.price_eur]):
        return None
    seller_or_city = normalize_key_part(row.seller_name) or normalize_key_part(row.location_city)
    if not seller_or_city:
        return None
    return "|".join(
        [
            normalize_key_part(row.make) or "",
            normalize_key_part(row.model) or "",
            str(row.year),
            str(row.mileage_km),
            str(int(round(row.price_eur))),
            seller_or_city,
        ]
    )


def compute_completeness_score(row: NormalizedListing) -> int:
    fields = [
        row.make,
        row.model,
        row.version,
        row.year,
        row.mileage_km,
        row.price_eur,
        row.fuel_type,
        row.transmission,
        row.body_type,
        row.power_hp,
        row.engine_capacity_cm3,
        row.seller_type,
        row.location_city,
    ]
    score = sum(1 for value in fields if value not in (None, "", 0))
    if row.raw:
        score += 1
    return score


def normalize_make(value: str | None) -> str | None:
    value = normalize_text(value, title_case=False)
    if not value:
        return None
    for make in KNOWN_MAKES:
        if normalize_key_part(make) == normalize_key_part(value):
            return make
    return value


def normalize_text(value: str | None, *, title_case: bool = False) -> str | None:
    value = clean_whitespace(value)
    if not value:
        return None
    value = value.replace("Ã„", "Ä").replace("Ã–", "Ö").replace("Ãœ", "Ü")
    value = value.replace("Ã¤", "ä").replace("Ã¶", "ö").replace("Ã¼", "ü")
    value = value.replace("ÃŸ", "ß").replace("â€“", "-").replace("â€”", "-")
    return value.title() if title_case else value


def normalize_url(url: str) -> str:
    return clean_whitespace(url.split("?")[0].rstrip("/")) or ""


def normalize_key_part(value: str | None) -> str | None:
    if not value:
        return None
    text = normalize_text(value, title_case=False) or ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text or None


def normalize_enum(value: Any, mapping: dict[str, str | None]) -> str | None:
    key = normalize_key_part(str(value)) if value not in (None, "") else None
    if not key:
        return None
    return mapping.get(key, key)


def _extract_site_value(source: str, raw: dict[str, Any], key: str) -> str | None:
    if source == "autovit":
        parameters = raw.get("parameters") or []
        for item in parameters:
            if item.get("key") == key:
                return item.get("displayValue") or item.get("value")
        parameters_dict = raw.get("parametersDict") or {}
        item = parameters_dict.get(key)
        if item:
            values = item.get("values") or []
            if values:
                return values[0].get("label") or values[0].get("value")
    return None


def _extract_raw_price(source: str, raw: dict[str, Any]) -> float | None:
    if source != "autovit":
        return None
    price = raw.get("price") or {}
    amount = price.get("amount") or {}
    for candidate in [amount.get("value"), price.get("value")]:
        parsed = _coerce_float(candidate)
        if parsed is not None:
            return parsed
    return None


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return parse_int(str(value))


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return parse_float(str(value))


def _prefer_candidate(candidate: NormalizedListing, current: NormalizedListing) -> bool:
    if candidate.completeness_score != current.completeness_score:
        return candidate.completeness_score > current.completeness_score
    return _scraped_at_timestamp(candidate.scraped_at) >= _scraped_at_timestamp(current.scraped_at)


def _scraped_at_timestamp(value: str | None) -> float:
    if not value:
        return float("-inf")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return float("-inf")
