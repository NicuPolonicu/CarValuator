from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from carvaluator_scraper.models import CarListing


INT_RE = re.compile(r"\d{1,3}(?:[.\s]\d{3})+|\d+")


def clean_whitespace(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(value.split())


def strip_html_tags(value: str | None) -> str | None:
    if value is None:
        return None
    text = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return clean_whitespace(text)


def parse_int(value: str | None) -> int | None:
    if not value:
        return None
    normalized = value.replace("\xa0", " ")
    match = INT_RE.search(normalized)
    if not match:
        return None
    digits = match.group(0).replace(" ", "").replace(".", "")
    return int(digits)


def parse_float(value: str | None) -> float | None:
    if not value:
        return None
    normalized = value.replace("\xa0", "").replace(" ", "")
    if "," in normalized and "." in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    elif "," in normalized:
        if normalized.count(",") == 1 and len(normalized.rsplit(",", 1)[-1]) in {1, 2}:
            normalized = normalized.replace(",", ".")
        else:
            normalized = normalized.replace(",", "")
    elif "." in normalized:
        if normalized.count(".") > 1:
            normalized = normalized.replace(".", "")
        else:
            fractional = normalized.rsplit(".", 1)[-1]
            if len(fractional) == 3:
                normalized = normalized.replace(".", "")
    match = re.search(r"\d+(?:\.\d+)?", normalized)
    return float(match.group(0)) if match else None


def set_query_param(url: str, key: str, value: str | int) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query[key] = str(value)
    return urlunparse(parsed._replace(query=urlencode(query)))


def polite_sleep(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_jsonl(path: Path, rows: Iterable[CarListing]) -> None:
    ensure_parent_dir(path)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row.to_dict(), ensure_ascii=False) + "\n")


def write_dict_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    ensure_parent_dir(path)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
