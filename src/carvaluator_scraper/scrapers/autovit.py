from __future__ import annotations

import json
import re
from time import sleep
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from carvaluator_scraper.models import CarListing
from carvaluator_scraper.utils import (
    clean_whitespace,
    parse_float,
    parse_int,
    polite_sleep,
    set_query_param,
    strip_html_tags,
)


NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json"[^>]*>(.*?)</script>',
    re.DOTALL,
)


class AutovitFetchError(RuntimeError):
    pass


class AutovitScraper:
    source = "autovit"

    def __init__(self, user_agent: str | None = None, timeout: int = 30) -> None:
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        )
        self.timeout = timeout

    def _fetch_html(self, url: str) -> str:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7",
            "Connection": "close",
        }
        last_error: Exception | None = None
        for attempt in range(3):
            request = Request(url, headers=headers)
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    return response.read().decode("utf-8", errors="replace")
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt < 2:
                    sleep(0.75 * (attempt + 1))
        raise AutovitFetchError(f"Autovit could not be reached for this listing: {last_error}") from last_error

    def _extract_next_data(self, html: str) -> dict[str, Any]:
        match = NEXT_DATA_RE.search(html)
        if not match:
            raise ValueError("Could not find __NEXT_DATA__ in Autovit page.")
        return json.loads(match.group(1))

    @staticmethod
    def _parameter_map(parameters: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for item in parameters or []:
            key = item.get("key")
            if key:
                result[key] = item
        return result

    @staticmethod
    def _param_display(param_map: dict[str, dict[str, Any]], key: str) -> str | None:
        item = param_map.get(key)
        if not item:
            return None
        return item.get("displayValue") or item.get("value")

    def scrape_search(self, url: str, pages: int = 1, delay_seconds: float = 1.0) -> list[CarListing]:
        rows: list[CarListing] = []
        for page_number in range(1, pages + 1):
            page_url = set_query_param(url, "page", page_number) if page_number > 1 else url
            rows.extend(self.scrape_search_page(page_url))
            if page_number < pages:
                polite_sleep(delay_seconds)
        return rows

    def scrape_search_page(self, url: str) -> list[CarListing]:
        html = self._fetch_html(url)
        next_data = self._extract_next_data(html)

        advert_search: dict[str, Any] | None = None
        for state in next_data["props"]["pageProps"]["urqlState"].values():
            state_data = json.loads(state["data"])
            if "advertSearch" in state_data:
                advert_search = state_data["advertSearch"]
                break

        if not advert_search:
            raise ValueError("Could not find Autovit search payload.")

        listings: list[CarListing] = []
        for edge in advert_search.get("edges", []):
            node = edge["node"]
            param_map = self._parameter_map(node.get("parameters"))
            price = node.get("price") or {}
            amount = (price.get("amount") or {}).get("value")
            location = node.get("location") or {}
            city = (location.get("city") or {}).get("name")
            region = (location.get("region") or {}).get("name")
            seller_link = node.get("sellerLink") or {}
            price_eval = node.get("priceEvaluation") or {}

            listings.append(
                CarListing(
                    source=self.source,
                    listing_id=node.get("id"),
                    url=node["url"],
                    title=node.get("title") or "",
                    make=self._param_display(param_map, "make"),
                    model=self._param_display(param_map, "model"),
                    version=self._param_display(param_map, "version"),
                    price_value=parse_float(str(amount)) if amount is not None else None,
                    currency=((price.get("amount") or {}).get("currencyCode")),
                    price_indicator=price_eval.get("indicator"),
                    seller_name=seller_link.get("name"),
                    seller_type=(node.get("seller") or {}).get("__typename"),
                    location_city=city,
                    location_region=region,
                    year=parse_int(self._param_display(param_map, "year")),
                    mileage_km=parse_int(self._param_display(param_map, "mileage")),
                    fuel_type=self._param_display(param_map, "fuel_type"),
                    transmission=self._param_display(param_map, "gearbox"),
                    power_hp=parse_int(self._param_display(param_map, "engine_power")),
                    engine_capacity_cm3=parse_int(self._param_display(param_map, "engine_capacity")),
                    body_type=self._param_display(param_map, "body_type"),
                    description=node.get("shortDescription"),
                    raw=node,
                )
            )

        return listings

    def scrape_detail(self, url: str) -> CarListing:
        html = self._fetch_html(url)
        next_data = self._extract_next_data(html)
        advert = next_data["props"]["pageProps"]["advert"]
        seller = advert.get("seller") or {}
        seller_location = seller.get("location") or {}
        param_dict = advert.get("parametersDict") or {}
        price = advert.get("price") or {}

        def param_label(key: str) -> str | None:
            item = param_dict.get(key)
            if not item:
                return None
            values = item.get("values") or []
            if not values:
                return None
            return values[0].get("label") or values[0].get("value")

        def param_value(key: str) -> str | None:
            item = param_dict.get(key)
            if not item:
                return None
            values = item.get("values") or []
            if not values:
                return None
            return values[0].get("value") or values[0].get("label")

        first_registration = param_label("date_registration")
        if first_registration and not re.fullmatch(r"\d{2}/\d{4}", first_registration):
            first_registration = None

        return CarListing(
            source=self.source,
            listing_id=advert.get("id"),
            url=advert.get("url") or url,
            title=advert.get("title") or "",
            make=param_label("make"),
            model=param_label("model"),
            version=param_label("version"),
            price_value=parse_float(str(price.get("value"))) if price.get("value") is not None else None,
            currency=price.get("currency"),
            price_indicator=None,
            seller_name=seller.get("name"),
            seller_type=seller.get("type"),
            location_city=seller_location.get("city"),
            location_region=seller_location.get("region"),
            year=parse_int(param_value("year")),
            first_registration=first_registration,
            mileage_km=parse_int(param_value("mileage") or param_label("mileage")),
            fuel_type=param_label("fuel_type"),
            transmission=param_label("gearbox"),
            power_hp=parse_int(param_value("engine_power") or param_label("engine_power")),
            engine_capacity_cm3=parse_int(param_value("engine_capacity") or param_label("engine_capacity")),
            body_type=param_label("body_type"),
            description=strip_html_tags(advert.get("description")),
            raw=advert,
        )
