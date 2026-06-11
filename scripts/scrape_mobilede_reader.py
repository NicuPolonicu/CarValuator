from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_PATHS = [
    "audi",
    "audi/a1",
    "audi/a3",
    "audi/a4",
    "audi/a5",
    "audi/a6",
    "audi/q2",
    "audi/q3",
    "audi/q5",
    "audi/q7",
    "bmw",
    "bmw/116",
    "bmw/118",
    "bmw/120",
    "bmw/320",
    "bmw/520",
    "bmw/530",
    "bmw/x1",
    "bmw/x3",
    "bmw/x5",
    "volkswagen",
    "volkswagen/caddy",
    "volkswagen/golf",
    "volkswagen/passat",
    "volkswagen/polo",
    "volkswagen/t-roc",
    "volkswagen/tiguan",
    "volkswagen/touran",
    "volkswagen/transporter",
    "mercedes-benz",
    "mercedes-benz/a-180",
    "mercedes-benz/a-200",
    "mercedes-benz/c-200",
    "mercedes-benz/c-220",
    "mercedes-benz/e-220",
    "mercedes-benz/glc-220",
    "mercedes-benz/gle-350",
    "mercedes-benz/sprinter",
    "ford",
    "ford/fiesta",
    "ford/focus",
    "ford/kuga",
    "ford/mondeo",
    "ford/transit",
    "opel",
    "opel/astra",
    "opel/corsa",
    "opel/insignia",
    "opel/mokka",
    "opel/zafira",
    "skoda",
    "skoda/fabia",
    "skoda/karoq",
    "skoda/kodiaq",
    "skoda/octavia",
    "skoda/superb",
    "toyota",
    "toyota/auris",
    "toyota/avensis",
    "toyota/corolla",
    "toyota/rav-4",
    "toyota/yaris",
    "hyundai",
    "hyundai/i20",
    "hyundai/i30",
    "hyundai/santa-fe",
    "hyundai/tucson",
    "kia",
    "kia/ceed",
    "kia/picanto",
    "kia/sorento",
    "kia/sportage",
    "renault",
    "renault/captur",
    "renault/clio",
    "renault/kadjar",
    "renault/megane",
    "peugeot",
    "peugeot/208",
    "peugeot/308",
    "peugeot/3008",
    "peugeot/508",
    "fiat",
    "fiat/500",
    "fiat/ducato",
    "fiat/panda",
    "fiat/tipo",
    "mazda",
    "mazda/3",
    "mazda/6",
    "mazda/cx-3",
    "mazda/cx-5",
    "seat",
    "seat/alhambra",
    "seat/ateca",
    "seat/ibiza",
    "seat/leon",
    "volvo",
    "volvo/v40",
    "volvo/v60",
    "volvo/xc60",
    "volvo/xc90",
    "dacia",
    "dacia/duster",
    "dacia/logan",
    "dacia/sandero",
    "nissan",
    "nissan/juke",
    "nissan/qashqai",
    "nissan/x-trail",
    "porsche",
    "porsche/911",
    "porsche/cayenne",
    "porsche/macan",
    "tesla",
    "tesla/model-3",
    "tesla/model-s",
    "tesla/model-y",
]

BRANDS = {
    "audi": "Audi",
    "bmw": "BMW",
    "volkswagen": "Volkswagen",
    "mercedes-benz": "Mercedes-Benz",
    "ford": "Ford",
    "opel": "Opel",
    "skoda": "Skoda",
    "toyota": "Toyota",
    "hyundai": "Hyundai",
    "kia": "Kia",
    "renault": "Renault",
    "peugeot": "Peugeot",
    "fiat": "Fiat",
    "mazda": "Mazda",
    "seat": "Seat",
    "volvo": "Volvo",
    "dacia": "Dacia",
    "nissan": "Nissan",
    "porsche": "Porsche",
    "tesla": "Tesla",
}

FUEL_MAP = {
    "diesel": "diesel",
    "benzin": "petrol",
    "benzina": "petrol",
    "gasolina": "petrol",
    "petrol": "petrol",
    "elektro": "electric",
    "electric": "electric",
    "electrico": "electric",
    "hybrid": "hybrid",
    "hibrido": "hybrid",
    "erdgas": "cng",
    "autogas": "lpg",
}

PRICE_RE = re.compile(r"(?:\u20ac\s*)?(\d{1,3}(?:[.,]\d{3})+|\d{4,6})\s*(?:\u20ac|EUR)")
SKIP_TITLE_PREFIXES = (
    "haeufige fragen",
    "häufige fragen",
    "frequently asked",
    "preguntas frecuentes",
    "questions frequentes",
    "questions fréquentes",
    "domande frequenti",
)
POWER_TO_HP = 1.3596216173
ENGINE_LABELS_RE = re.compile(
    r"(?<![A-Za-z0-9])([0-6])[\.,](\d)\s*[- ]?\s*"
    r"(?P<label>"
    r"TDI|TFSI|TSI|FSI|HDI|BlueHDI|dCi|DCI|CDI|CRDI|GDI|T-GDI|DIG-T|"
    r"EcoBoost|EcoBlue|MPI|TDCI|TDDI|CDTI|JTD|JTDM|Multijet|TwinAir|"
    r"PureTech|Skyactiv[- ]?[DGX]?|MHEV|PHEV|Hybrid|Turbo|VTEC|VVT|"
    r"i-VTEC|Kompressor|Benzin|Diesel|Ltr\.?|ltr\.?|L\b|d\b"
    r")",
    re.IGNORECASE,
)
EXPLICIT_CAPACITY_RE = re.compile(r"(?<!\d)([1-7]\d{2,3})\s*(?:cm3|cm³|ccm|cc)\b", re.IGNORECASE)
EXPLICIT_POWER_RE = re.compile(r"(?<!\d)(\d{2,3})\s*(?:PS|HP|CP|CV)\b", re.IGNORECASE)
KW_POWER_RE = re.compile(r"(?<!\d)(\d{2,3})\s*kW\b", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Experimental mobile.de scraper using Jina Reader Markdown pages. "
            "The result is JSONL compatible with the normal CarValuator export-csv pipeline."
        )
    )
    parser.add_argument("--output", type=Path, default=Path("data/mobilede_reader.jsonl"))
    parser.add_argument("--report", type=Path, default=Path("data/mobilede_reader_report.json"))
    parser.add_argument("--cache-dir", type=Path, default=Path("data/mobilede_reader_cache"))
    parser.add_argument("--delay", type=float, default=0.2)
    parser.add_argument("--max-pages", type=int, default=0, help="0 means all default pages")
    parser.add_argument("--paths", nargs="*", default=None, help="Optional /en/car paths, e.g. audi/a4 bmw/320")
    return parser.parse_args()


def parse_int(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"\d[\d.,\s]*", value.replace("\xa0", " "))
    if not match:
        return None
    return int(re.sub(r"[^\d]", "", match.group(0)))


def valid_power_hp(value: int | None) -> int | None:
    if value is None:
        return None
    return value if 30 <= value <= 900 else None


def valid_engine_capacity_cm3(value: int | None) -> int | None:
    if value is None:
        return None
    return value if 600 <= value <= 8000 else None


def infer_power_hp(text: str | None) -> tuple[int | None, str | None]:
    if not text:
        return None, None

    explicit_match = EXPLICIT_POWER_RE.search(text)
    if explicit_match:
        value = valid_power_hp(int(explicit_match.group(1)))
        if value is not None:
            return value, "explicit_hp"

    kw_match = KW_POWER_RE.search(text)
    if kw_match:
        value = valid_power_hp(round(int(kw_match.group(1)) * POWER_TO_HP))
        if value is not None:
            return value, "kw_to_hp"

    return None, None


def infer_engine_capacity_cm3(text: str | None) -> tuple[int | None, str | None]:
    if not text:
        return None, None

    explicit_match = EXPLICIT_CAPACITY_RE.search(text)
    if explicit_match:
        value = valid_engine_capacity_cm3(int(explicit_match.group(1)))
        if value is not None:
            return value, "explicit_capacity"

    for engine_match in ENGINE_LABELS_RE.finditer(text):
        label = engine_match.group("label").casefold()
        tail = text[engine_match.end() : engine_match.end() + 12]
        if label.startswith("l") and re.match(r"\s*/\s*100", tail):
            continue
        if label == "d" and engine_match.group(2) != "0":
            continue
        value = valid_engine_capacity_cm3(int(engine_match.group(1)) * 1000 + int(engine_match.group(2)) * 100)
        if value is not None:
            return value, "title_displacement"

    return None, None


def clean_title(value: str) -> str:
    value = re.sub(
        r"^(Patrocinado|Sponsored|Gesponsert|NEU|New|Nuevo|NUEVO)\s+",
        "",
        value,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", value).strip()


def model_label(source_path: str) -> tuple[str | None, str | None]:
    parts = source_path.split("/")
    make = BRANDS.get(parts[0], parts[0].replace("-", " ").title())
    model = None
    if len(parts) > 1:
        model = parts[1].replace("-", " ").title()
        replacements = {
            "Cx 3": "CX-3",
            "Cx 5": "CX-5",
            "Rav 4": "RAV4",
            "T Roc": "T-Roc",
            "X Trail": "X-Trail",
        }
        model = replacements.get(model, model)
    return make, model


def cache_name(source_path: str) -> str:
    return source_path.strip("/").replace("/", "__") + ".md"


def fetch_markdown(source_path: str, cache_dir: Path) -> tuple[str, str, str | None]:
    reader_url = f"https://r.jina.ai/http://www.mobile.de/en/car/{source_path.strip('/')}"
    cache_path = cache_dir / cache_name(source_path)
    if cache_path.exists() and cache_path.stat().st_size > 1000:
        return cache_path.read_text(encoding="utf-8"), reader_url, None

    request = Request(reader_url, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/plain"})
    try:
        with urlopen(request, timeout=90) as response:
            text = response.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError) as exc:
        return "", reader_url, f"{type(exc).__name__}: {exc}"

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(text, encoding="utf-8")
    return text, reader_url, None


def parse_markdown(text: str, source_path: str, reader_url: str) -> list[dict[str, object]]:
    make, model = model_label(source_path)
    text = text.replace("\xa0", " ")
    if "Access denied" in text or "Target URL returned error 404" in text:
        return []

    text = re.sub(r"(?<!\n)##\s+", "\n## ", text)
    starts = [match.start() for match in re.finditer(r"(?m)^##\s+", text)]
    rows: list[dict[str, object]] = []

    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(text)
        block = text[start:end]
        compact = re.sub(r"\s+", " ", block).strip()
        price_match = PRICE_RE.search(compact)
        if not price_match:
            continue

        title = clean_title(compact[3 : price_match.start()].strip(" -|"))
        normalized_title = title.casefold()
        ascii_title = normalized_title.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
        if (
            len(title) < 5
            or normalized_title.startswith(("image ", "other ", "similar ", "home page"))
            or any(ascii_title.startswith(prefix) or normalized_title.startswith(prefix) for prefix in SKIP_TITLE_PREFIXES)
        ):
            continue

        if not re.search(r"\b(EZ|FR|PR)\s+\d{2}/\d{4}\b|\bNew car\b|\bNeuwagen\b", compact, re.IGNORECASE):
            continue

        specs = re.search(
            r"(?:PR|EZ|FR)\s+(\d{2})/(\d{4}).{0,140}?(\d[\d.,]*)\s*km"
            r".{0,120}?(\d+)\s*kW\s*\((\d+)\s*(?:cv|ps|hp|cp)\)"
            r".{0,90}?([A-Za-z/() -]{3,45})",
            compact,
            re.IGNORECASE,
        )
        first_registration = None
        year = None
        mileage_km = None
        power_hp = None
        fuel_type = None
        if specs:
            first_registration = f"{specs.group(1)}/{specs.group(2)}"
            year = int(specs.group(2))
            mileage_km = parse_int(specs.group(3))
            power_hp = valid_power_hp(parse_int(specs.group(5)))
            raw_fuel = " ".join(specs.group(6).strip().split()[:3]).lower()
            token = raw_fuel.split()[0]
            fuel_type = "hybrid" if raw_fuel.startswith("hybrid") or "benzin/elektro" in raw_fuel else FUEL_MAP.get(token, token)
        power_source = "listing_specs" if power_hp is not None else None
        if power_hp is None:
            power_hp, power_source = infer_power_hp(title)

        engine_capacity_cm3, engine_capacity_source = infer_engine_capacity_cm3(title)

        image_match = re.search(r"!\[[^\]]*\]\((https://img\.classistatic\.de/[^)]+)\)", block)
        location_city = None
        location_match = re.search(
            r"(?:DE-)?(\d{5}\s+[A-Za-z][^\d\[]+?)\s+"
            r"(?:\d(?:[.,]\d)?\s+(?:estrellas|Sterne|stars)|Kontakt|Contact|Aparcar|Parken)",
            compact,
        )
        if location_match:
            location_city = re.sub(r"^\d{5}\s+", "", location_match.group(1)).strip(" *")[:100]

        price_value = parse_int(price_match.group(1))
        fingerprint = "|".join(str(value or "") for value in [title, make, model, year, mileage_km, power_hp, price_value, location_city])
        listing_hash = hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:16]

        rows.append(
            {
                "source": "mobilede",
                "listing_id": f"reader-{listing_hash}",
                "url": f"https://www.mobile.de/en/car/{source_path}#reader-{listing_hash}",
                "title": title,
                "make": make,
                "model": model,
                "version": title,
                "price_value": float(price_value) if price_value else None,
                "currency": "EUR",
                "price_indicator": None,
                "seller_name": None,
                "seller_type": None,
                "location_city": location_city,
                "location_region": None,
                "year": year,
                "first_registration": first_registration,
                "mileage_km": mileage_km,
                "fuel_type": fuel_type,
                "transmission": None,
                "power_hp": power_hp,
                "engine_capacity_cm3": engine_capacity_cm3,
                "body_type": None,
                "description": None,
                "scraped_at": datetime.now(timezone.utc).isoformat(),
                "raw": {
                    "extraction_method": "jina_reader_markdown",
                    "power_source": power_source,
                    "engine_capacity_source": engine_capacity_source,
                    "reader_url": reader_url,
                    "source_path": source_path,
                    "image_url": image_match.group(1) if image_match else None,
                    "reader_block": compact[:1400],
                },
            }
        )

    return rows


def main() -> None:
    args = parse_args()
    paths = args.paths or DEFAULT_PATHS
    if args.max_pages > 0:
        paths = paths[: args.max_pages]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.cache_dir.mkdir(parents=True, exist_ok=True)

    seen: set[str] = set()
    all_rows: list[dict[str, object]] = []
    stats: list[dict[str, object]] = []

    for index, source_path in enumerate(paths, 1):
        text, reader_url, error = fetch_markdown(source_path, args.cache_dir)
        rows = parse_markdown(text, source_path, reader_url) if text else []
        added = 0
        for row in rows:
            key = str(row["listing_id"])
            if key in seen:
                continue
            seen.add(key)
            all_rows.append(row)
            added += 1
        stats.append({"path": source_path, "rows": len(rows), "added": added, "error": error})
        print(f"{index:03d}/{len(paths)} {source_path}: rows={len(rows)} added={added} total={len(all_rows)}")
        time.sleep(args.delay)

    with args.output.open("w", encoding="utf-8") as handle:
        for row in all_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    report = {
        "output": str(args.output),
        "unique_rows": len(all_rows),
        "pages_total": len(stats),
        "pages_with_rows": sum(1 for item in stats if item["rows"]),
        "pages": stats,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
