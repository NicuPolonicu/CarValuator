from __future__ import annotations

import html as html_lib
import json
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from carvaluator_scraper.models import CarListing
from carvaluator_scraper.utils import clean_whitespace, parse_float, parse_int, polite_sleep


PRICE_LABELS = (
    "Sehr guter Preis",
    "Guter Preis",
    "Fairer Preis",
    "Hoher Preis",
    "Erhöhter Preis",
    "Ohne Bewertung",
)

MOBILEDE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 "
    "Edg/125.0.0.0"
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


class MobileDeBlockedError(RuntimeError):
    """Raised when mobile.de blocks automated access."""


class MobileDeScraper:
    source = "mobilede"

    def __init__(
        self,
        headless: bool = True,
        timeout_ms: int = 60_000,
        channel: str | None = None,
    ) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.channel = channel

    def scrape_search(self, url: str, pages: int = 1, delay_seconds: float = 2.0) -> list[CarListing]:
        try:
            return self._scrape_search_api(url, pages=pages, delay_seconds=delay_seconds)
        except MobileDeBlockedError:
            pass
        except (json.JSONDecodeError, OSError, URLError):
            pass

        return self._scrape_search_browser(url, pages=pages, delay_seconds=delay_seconds)

    def scrape_detail(self, url: str) -> CarListing:
        detail_url = self._detail_url_for(url)
        html_text = self._fetch_detail_html(detail_url)
        return self._parse_detail_page(html_text, original_url=url, detail_url=detail_url)

    def _scrape_search_api(self, url: str, pages: int = 1, delay_seconds: float = 2.0) -> list[CarListing]:
        rows: list[CarListing] = []
        seen_keys: set[str] = set()

        for page_number in range(1, pages + 1):
            search_url = url if page_number == 1 else self._set_page_number(url, page_number)
            data = self._fetch_search_json(search_url)
            for row in self._extract_api_items(data):
                dedupe_key = row.listing_id or row.url
                if dedupe_key in seen_keys:
                    continue
                seen_keys.add(dedupe_key)
                rows.append(row)
            if page_number < pages:
                polite_sleep(delay_seconds)

        return rows

    def _scrape_search_browser(self, url: str, pages: int = 1, delay_seconds: float = 2.0) -> list[CarListing]:
        rows: list[CarListing] = []
        with sync_playwright() as playwright:
            browser, context, page = self._open_browser(playwright)

            for page_number in range(1, pages + 1):
                target_url = url if page_number == 1 else self._set_page_number(url, page_number)
                self._navigate(page, target_url)
                self._raise_if_blocked(page)
                self._try_accept_cookies(page)
                page.wait_for_timeout(1_500)
                rows.extend(self._extract_search_cards(page))
                if page_number < pages:
                    polite_sleep(delay_seconds)

            context.close()
            browser.close()

        return rows

    def _fetch_search_json(self, search_url: str) -> dict[str, Any]:
        api_url = self._to_consumer_api_url(search_url)
        request = Request(
            api_url,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
                "Referer": search_url,
                "User-Agent": MOBILEDE_USER_AGENT,
                "sec-ch-ua": '"Microsoft Edge";v="125", "Chromium";v="125", "Not.A/Brand";v="24"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_ms / 1000) as response:
                content_type = response.headers.get("Content-Type", "")
                body = response.read()
        except HTTPError as exc:
            if exc.code in {401, 403, 429}:
                raise MobileDeBlockedError(
                    "mobile.de refused the search API request from this environment. "
                    "Try again later, reduce page count, or run with `--headful` to attempt the browser fallback."
                ) from exc
            raise

        if "json" not in content_type.lower():
            text = body[:1000].decode("utf-8", errors="ignore").lower()
            if "access denied" in text or "zugriff verweigert" in text:
                raise MobileDeBlockedError("mobile.de returned an access denied page instead of listing JSON.")

        return json.loads(body.decode("utf-8"))

    def _fetch_detail_html(self, detail_url: str) -> str:
        request = Request(
            detail_url,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ro-RO,ro;q=0.9,de-DE;q=0.8,de;q=0.7,en-US;q=0.6,en;q=0.5",
                "User-Agent": MOBILEDE_USER_AGENT,
                "Upgrade-Insecure-Requests": "1",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_ms / 1000) as response:
                content_type = response.headers.get("Content-Type", "")
                body = response.read()
        except HTTPError as exc:
            if exc.code in {401, 403, 429}:
                raise MobileDeBlockedError("mobile.de refused the detail page request from this environment.") from exc
            raise

        text = body.decode("utf-8", errors="ignore")
        if "html" not in content_type.lower():
            lowered = text[:1000].lower()
            if "access denied" in lowered or "zugriff verweigert" in lowered:
                raise MobileDeBlockedError("mobile.de returned an access denied page instead of listing HTML.")
        return text

    @staticmethod
    def _to_consumer_api_url(url: str) -> str:
        parsed = urlsplit(url)
        if parsed.path == "/consumer/api/search/srp":
            return url
        query = parsed.query or "dam=false&isSearchRequest=true&s=Car&vc=Car"
        return urlunsplit(("https", "www.mobile.de", "/consumer/api/search/srp", query, ""))

    @staticmethod
    def _detail_url_for(url: str) -> str:
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        listing_id = query.get("id", [""])[0]
        if not listing_id:
            match = re.search(r"(\d{6,})", url)
            listing_id = match.group(1) if match else ""
        if parsed.netloc.endswith("mobile.de") and parsed.path.endswith("/detalii.html") and listing_id:
            return url
        if listing_id:
            return f"https://www.mobile.de/ro/vehicule/detalii.html?id={listing_id}"
        return url

    def _open_browser(self, playwright: Any) -> tuple[Any, Any, Any]:
        launch_options: dict[str, Any] = {
            "headless": self.headless,
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        if self.channel and self.channel.casefold() not in {"chromium", "default"}:
            launch_options["channel"] = self.channel

        browser = playwright.chromium.launch(
            **launch_options,
        )
        context = browser.new_context(
            locale="de-DE",
            viewport={"width": 1440, "height": 1200},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36 "
                "Edg/145.0.0.0"
            ),
            extra_http_headers={
                "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
                "Upgrade-Insecure-Requests": "1",
                "Sec-CH-UA": '"Microsoft Edge";v="145", "Not=A?Brand";v="24", "Chromium";v="145"',
                "Sec-CH-UA-Mobile": "?0",
                "Sec-CH-UA-Platform": '"Windows"',
            },
        )
        context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'languages', {get: () => ['de-DE', 'de', 'en-US', 'en']});
            Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});
            """
        )
        page = context.new_page()
        return browser, context, page

    def _navigate(self, page: Any, target_url: str) -> None:
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                page.goto(target_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                page.wait_for_timeout(2_000 + (attempt * 1_000))
                return
            except Exception as exc:
                last_error = exc
                page.wait_for_timeout(1_000 * attempt)
        if last_error is not None:
            raise last_error

    @staticmethod
    def _set_page_number(url: str, page_number: int) -> str:
        separator = "&" if "?" in url else "?"
        if "pageNumber=" in url:
            return re.sub(r"pageNumber=\d+", f"pageNumber={page_number}", url)
        return f"{url}{separator}pageNumber={page_number}"

    @staticmethod
    def _raise_if_blocked(page: Any) -> None:
        title = page.title().lower()
        body = page.locator("body").inner_text(timeout=5_000).lower()
        if "access denied" in title or "zugriff verweigert" in body:
            raise MobileDeBlockedError(
                "mobile.de blocked automated access from this environment. "
                "The scraper now uses a more realistic Edge browser profile, but the site still applies "
                "active bot protection. Try again on your own machine with `--headful`, a normal residential "
                "connection, and a fresh browser session."
            )

    @staticmethod
    def _try_accept_cookies(page: Any) -> None:
        labels = [
            "Akzeptieren",
            "Alle akzeptieren",
            "Accept",
            "Accept all",
        ]
        for label in labels:
            locator = page.get_by_role("button", name=label)
            if locator.count():
                try:
                    locator.first.click(timeout=2_000)
                    return
                except PlaywrightTimeoutError:
                    continue

    def _extract_api_items(self, data: dict[str, Any]) -> list[CarListing]:
        items = data.get("searchResults", {}).get("items", [])
        if not isinstance(items, list):
            return []
        return [self._parse_api_item(item) for item in items if self._is_listing_item(item)]

    @staticmethod
    def _is_listing_item(item: Any) -> bool:
        return isinstance(item, dict) and item.get("id") and item.get("type") in {"ad", "topAd", "eyecatcherAd"}

    def _parse_api_item(self, item: dict[str, Any]) -> CarListing:
        attr = item.get("attr") if isinstance(item.get("attr"), dict) else {}
        price = item.get("price") if isinstance(item.get("price"), dict) else {}
        price_rating = item.get("priceRating") if isinstance(item.get("priceRating"), dict) else {}
        contact = item.get("contactInfo") if isinstance(item.get("contactInfo"), dict) else {}
        image = item.get("previewImage") if isinstance(item.get("previewImage"), dict) else {}

        title = clean_whitespace(item.get("title")) or ""
        make = clean_whitespace(item.get("make"))
        model = clean_whitespace(item.get("model"))
        version = clean_whitespace(item.get("subTitle"))
        if not make or not model:
            inferred_make, inferred_model, inferred_version = self._infer_make_model_version(title)
            make = make or inferred_make
            model = model or inferred_model
            version = version or inferred_version

        first_registration = clean_whitespace(attr.get("fr"))
        raw = {
            "api_item": item,
            "image_url": image.get("src"),
            "image_srcset": image.get("srcSet"),
        }
        title_and_version = f"{title} {version or ''}"
        power_hp = self._parse_power_hp(attr.get("pw")) or self._parse_power_hp(title_and_version)
        engine_capacity_cm3 = parse_int(attr.get("cc")) or self._infer_engine_capacity_cm3(title_and_version)

        return CarListing(
            source=self.source,
            listing_id=str(item.get("id")) if item.get("id") is not None else None,
            url=self._absolute_listing_url(item.get("relativeUrl")),
            title=title,
            make=make,
            model=model,
            version=version,
            price_value=parse_float(str(price.get("grossAmount") or price.get("gross") or "")),
            currency=price.get("grossCurrency") or ("EUR" if price.get("gross") else None),
            price_indicator=price_rating.get("ratingLabel") or price_rating.get("rating"),
            seller_name=clean_whitespace(contact.get("name")),
            seller_type=contact.get("sellerType") or contact.get("typeLocalized"),
            location_city=clean_whitespace(attr.get("loc")) or self._parse_location_city(contact.get("location")),
            location_region=None,
            year=self._year_from_registration(first_registration) or parse_int(attr.get("yc")),
            first_registration=first_registration,
            mileage_km=parse_int(attr.get("ml")),
            fuel_type=clean_whitespace(attr.get("ft")),
            transmission=clean_whitespace(attr.get("tr")),
            power_hp=power_hp,
            engine_capacity_cm3=engine_capacity_cm3,
            body_type=clean_whitespace(item.get("category")) or clean_whitespace(attr.get("c")),
            description=None,
            raw=raw,
        )

    def _parse_detail_page(self, html_text: str, *, original_url: str, detail_url: str) -> CarListing:
        listing_id = self._extract_listing_id(detail_url) or self._extract_listing_id(original_url)
        title = self._extract_class_text(html_text, "MainCtaBox_title") or self._extract_title_fallback(html_text)
        version = self._extract_class_text(html_text, "MainCtaBox_subTitle")
        image_url = self._extract_image_url(html_text)
        if not title and image_url:
            title = self._extract_image_alt(html_text) or ""
        make, model, inferred_version = self._infer_make_model_version(title)
        version = version or inferred_version

        price_text = self._extract_testid_text(html_text, "vip-price-label")
        price_match = re.search(r"(\d{1,3}(?:[.\s]\d{3})*(?:,\d+)?)\s*(EUR|€)", price_text or "")
        price_label = self._extract_price_rating_label(html_text)
        seller_name, location_city = self._extract_seller_info(html_text)
        first_registration = self._extract_detail_feature(html_text, "vip-key-features-list-item-firstRegistration")
        mileage = self._extract_detail_feature(html_text, "vip-key-features-list-item-mileage")
        power = self._extract_detail_feature(html_text, "vip-key-features-list-item-power")
        fuel = self._extract_detail_feature(html_text, "vip-key-features-list-item-fuel")
        transmission = self._extract_detail_feature(html_text, "vip-key-features-list-item-transmission")
        body_type = self._extract_data_list_item(html_text, "category-item")
        engine_capacity = self._extract_data_list_item(html_text, "cubicCapacity-item")
        title_and_version = f"{title} {version or ''}"
        power_hp = self._parse_power_hp(power) or self._parse_power_hp(title_and_version)
        engine_capacity_cm3 = parse_int(engine_capacity) or self._infer_engine_capacity_cm3(title_and_version)

        return CarListing(
            source=self.source,
            listing_id=listing_id,
            url=original_url,
            title=title,
            make=make,
            model=model,
            version=version,
            price_value=parse_float(price_match.group(1)) if price_match else None,
            currency="EUR" if price_match else None,
            price_indicator=price_label,
            seller_name=seller_name,
            seller_type="dealer" if seller_name else None,
            location_city=location_city,
            location_region=None,
            year=self._year_from_registration(first_registration),
            first_registration=first_registration,
            mileage_km=parse_int(mileage),
            fuel_type=fuel,
            transmission=transmission,
            power_hp=power_hp,
            engine_capacity_cm3=engine_capacity_cm3,
            body_type=body_type,
            description=None,
            raw={
                "detail_source": "mobilede_detail_page",
                "detail_url": detail_url,
                "image_url": image_url,
                "price_label": price_label,
                "key_features": {
                    "first_registration": first_registration,
                    "mileage": mileage,
                    "power": power,
                    "fuel": fuel,
                    "transmission": transmission,
                    "body_type": body_type,
                    "engine_capacity": engine_capacity,
                },
            },
        )

    def _extract_search_cards(self, page: Any) -> list[CarListing]:
        cards: list[dict[str, Any]] = page.evaluate(
            """
            () => {
              const headings = Array.from(document.querySelectorAll('main h2'));
              return headings.map((heading) => {
                let node = heading;
                let best = heading.parentElement;
                for (let i = 0; i < 7 && node; i += 1) {
                  const text = (node.innerText || '').trim();
                  const hasPrice = /\\d{1,3}(?:[\\.\\s]\\d{3})*(?:,\\d+)?\\s*€/.test(text);
                  const hasContact = /Kontakt|Parken/.test(text);
                  if (hasPrice && hasContact && text.length < 2500) {
                    best = node;
                    break;
                  }
                  node = node.parentElement;
                }

                const anchor =
                  best?.querySelector('a[href*="/fahrzeuge/details.html"]') ||
                  best?.querySelector('a[href*="/auto/"]') ||
                  heading.closest('a');

                return {
                  title: (heading.innerText || '').trim(),
                  text: (best?.innerText || heading.innerText || '').trim(),
                  url: anchor ? anchor.href : null,
                };
              }).filter(item => item.title);
            }
            """
        )
        return [self._parse_card(card) for card in cards if card.get("title")]

    def _parse_card(self, card: dict[str, Any]) -> CarListing:
        text = clean_whitespace(card.get("text")) or ""
        title = clean_whitespace(card.get("title")) or ""
        lines = [line.strip() for line in card.get("text", "").splitlines() if line.strip()]
        price_label = next((label for label in PRICE_LABELS if label in text), None)
        price_line = next(
            (
                line
                for line in lines
                if line != title
                and "EZ " not in line
                and re.search(r"\d{1,3}(?:[.\s]\d{3})+(?:,\d+)?", line)
            ),
            "",
        )
        spec_line = next((line for line in lines if "EZ " in line), "")
        location_line = next((line for line in lines if re.match(r"^\d{5}\s+.+", line)), "")

        price_match = re.search(r"(\d{1,3}(?:[.\s]\d{3})*(?:,\d+)?)", price_line)
        spec_match = re.search(
            r"(?:(Unfallfrei|Reparierter Unfallschaden)\s*(?:•|·|\?)\s*)?"
            r"EZ\s+(\d{2}/\d{4})\s*(?:•|·|\?)\s*"
            r"([\d.]+)\s*km\s*(?:•|·|\?)\s*"
            r"(\d+)\s*kW\s*\((\d+)\s*PS\)\s*(?:•|·|\?)\s*"
            r"(.+)",
            spec_line,
        )
        location_match = re.match(r"^\d{5}\s+(.+)$", location_line)
        seller_name = self._infer_seller_name(lines, title, location_line)
        make, model, version = self._infer_make_model_version(title)
        power_hp = int(spec_match.group(5)) if spec_match else self._parse_power_hp(title) or self._parse_power_hp(text)
        engine_capacity_cm3 = self._infer_engine_capacity_cm3(title)

        return CarListing(
            source=self.source,
            listing_id=self._extract_listing_id(card.get("url")),
            url=card.get("url") or "",
            title=title,
            make=make,
            model=model,
            version=version,
            price_value=parse_float(price_match.group(1)) if price_match else None,
            currency="EUR" if price_match else None,
            price_indicator=price_label,
            seller_name=seller_name,
            seller_type="PRIVATE" if "Privatanbieter" in location_line or "Privatanbieter" in text else None,
            location_city=clean_whitespace(location_match.group(1).replace(", Privatanbieter", "")) if location_match else None,
            location_region=None,
            year=int(spec_match.group(2)[-4:]) if spec_match else None,
            first_registration=spec_match.group(2) if spec_match else None,
            mileage_km=parse_int(spec_match.group(3)) if spec_match else None,
            fuel_type=clean_whitespace(spec_match.group(6)) if spec_match else None,
            transmission=None,
            power_hp=power_hp,
            engine_capacity_cm3=engine_capacity_cm3,
            body_type=None,
            description=None,
            raw=card,
        )

    @staticmethod
    def _absolute_listing_url(relative_url: str | None) -> str:
        if not relative_url:
            return ""
        if relative_url.startswith("http://") or relative_url.startswith("https://"):
            return relative_url
        return f"https://suchen.mobile.de{relative_url}"

    @staticmethod
    def _parse_location_city(location: str | None) -> str | None:
        cleaned = clean_whitespace(location)
        if not cleaned:
            return None
        match = re.match(r"^\d{5}\s+(.+)$", cleaned)
        return clean_whitespace(match.group(1)) if match else cleaned

    @staticmethod
    def _year_from_registration(first_registration: str | None) -> int | None:
        if not first_registration:
            return None
        match = re.search(r"(\d{4})", first_registration)
        return int(match.group(1)) if match else None

    @staticmethod
    def _parse_power_hp(power: str | None) -> int | None:
        cleaned = clean_whitespace(power)
        if not cleaned:
            return None
        match = re.search(r"\((\d+)\s*(?:PS|CP|HP|CV)\)", cleaned, flags=re.IGNORECASE)
        if match:
            return MobileDeScraper._valid_power_hp(int(match.group(1)))
        explicit_match = EXPLICIT_POWER_RE.search(cleaned)
        if explicit_match:
            return MobileDeScraper._valid_power_hp(int(explicit_match.group(1)))
        kw_match = KW_POWER_RE.search(cleaned)
        if kw_match:
            return MobileDeScraper._valid_power_hp(round(int(kw_match.group(1)) * POWER_TO_HP))
        if re.fullmatch(r"\d{2,3}", cleaned):
            return MobileDeScraper._valid_power_hp(int(cleaned))
        return None

    @staticmethod
    def _valid_power_hp(value: int | None) -> int | None:
        if value is None:
            return None
        return value if 30 <= value <= 900 else None

    @staticmethod
    def _valid_engine_capacity_cm3(value: int | None) -> int | None:
        if value is None:
            return None
        return value if 600 <= value <= 8000 else None

    @staticmethod
    def _infer_engine_capacity_cm3(text: str | None) -> int | None:
        if not text:
            return None
        explicit_match = EXPLICIT_CAPACITY_RE.search(text)
        if explicit_match:
            return MobileDeScraper._valid_engine_capacity_cm3(int(explicit_match.group(1)))
        for engine_match in ENGINE_LABELS_RE.finditer(text):
            label = engine_match.group("label").casefold()
            tail = text[engine_match.end() : engine_match.end() + 12]
            if label.startswith("l") and re.match(r"\s*/\s*100", tail):
                continue
            if label == "d" and engine_match.group(2) != "0":
                continue
            return MobileDeScraper._valid_engine_capacity_cm3(
                int(engine_match.group(1)) * 1000 + int(engine_match.group(2)) * 100
            )
        return None

    @staticmethod
    def _extract_listing_id(url: str | None) -> str | None:
        if not url:
            return None
        match = re.search(r"id=(\d+)", url)
        return match.group(1) if match else None

    @staticmethod
    def _infer_seller_name(lines: list[str], title: str, location_line: str) -> str | None:
        skip = {
            title,
            "Versicherung vergleichen",
            "Kontakt",
            "Parken",
            *PRICE_LABELS,
        }
        if "Privatanbieter" in location_line:
            return "Privatanbieter"
        if not location_line or location_line not in lines:
            return None
        location_index = lines.index(location_line)
        for index in range(location_index - 1, -1, -1):
            line = lines[index]
            if line in skip:
                continue
            if re.search(r"^\(?\d+\)?$", line):
                continue
            if "Sterne" in line:
                continue
            if re.search(r"\d{1,3}(?:[.\s]\d{3})*(?:,\d+)?", line):
                continue
            if re.search(r"EZ\s+\d{2}/\d{4}", line):
                continue
            return clean_whitespace(line)
        return None

    @staticmethod
    def _infer_make_model_version(title: str) -> tuple[str | None, str | None, str | None]:
        cleaned = clean_whitespace(title) or ""
        parts = cleaned.split()
        if not parts:
            return None, None, None
        make = parts[0]
        if len(parts) == 1:
            return make, None, None
        model = parts[1]
        version = " ".join(parts[2:]) or None
        return make, model, version

    @staticmethod
    def _strip_tags(value: str | None) -> str | None:
        if not value:
            return None
        without_tags = re.sub(r"<[^>]+>", " ", value)
        return clean_whitespace(html_lib.unescape(without_tags))

    @classmethod
    def _extract_class_text(cls, html_text: str, class_marker: str) -> str | None:
        pattern = (
            rf'<(?P<tag>h[1-6]|span|p|div)[^>]*class="[^"]*'
            rf'{re.escape(class_marker)}(?:__|\s|")[^"]*"[^>]*>(.*?)</(?P=tag)>'
        )
        match = re.search(pattern, html_text, flags=re.IGNORECASE | re.DOTALL)
        return cls._strip_tags(match.group(2)) if match else None

    @classmethod
    def _extract_testid_text(cls, html_text: str, test_id: str, *, window: int = 1800) -> str | None:
        match = re.search(rf'data-testid="{re.escape(test_id)}"', html_text)
        if not match:
            return None
        tag_start = html_text.rfind("<", 0, match.start())
        start = tag_start if tag_start != -1 else match.start()
        return cls._strip_tags(html_text[start : start + window])

    @classmethod
    def _extract_detail_feature(cls, html_text: str, test_id: str) -> str | None:
        match = re.search(rf'data-testid="{re.escape(test_id)}"', html_text)
        if not match:
            return None
        tag_start = html_text.rfind("<", 0, match.start())
        start = tag_start if tag_start != -1 else match.start()
        next_match = re.search(r'data-testid="vip-key-features-list-item-', html_text[match.end() :])
        end = match.end() + next_match.start() if next_match else start + 2500
        section = html_text[start:end]
        headings = re.findall(r"<h4\b[^>]*>(.*?)</h4>", section, flags=re.IGNORECASE | re.DOTALL)
        for candidate in reversed(headings):
            cleaned = cls._strip_tags(candidate)
            if cleaned:
                return cleaned
        return cls._strip_tags(section)

    @classmethod
    def _extract_price_rating_label(cls, html_text: str) -> str | None:
        match = re.search(r'priceRatingBadge[^"]*label[^"]*"', html_text, flags=re.IGNORECASE)
        if not match:
            return None
        section = html_text[match.start() : match.start() + 700]
        text = cls._strip_tags(section)
        if not text:
            return None
        labels = [
            "Pret foarte bun",
            "Pret bun",
            "Pret corect",
            "Pret ridicat",
            "Pret mare",
            "Preț foarte bun",
            "Preț bun",
            "Preț corect",
            "Preț ridicat",
            "Preț mare",
            *PRICE_LABELS,
        ]
        normalized_text = text.casefold()
        return next((label for label in labels if label.casefold() in normalized_text), text)

    @classmethod
    def _extract_data_list_item(cls, html_text: str, test_id: str) -> str | None:
        pattern = rf'data-testid="{re.escape(test_id)}"[^>]*>.*?</dt>\s*<dd\b[^>]*>(.*?)</dd>'
        match = re.search(pattern, html_text, flags=re.IGNORECASE | re.DOTALL)
        return cls._strip_tags(match.group(1)) if match else None

    @classmethod
    def _extract_seller_info(cls, html_text: str) -> tuple[str | None, str | None]:
        match = re.search(r'data-testid="seller-title-address"', html_text)
        if not match:
            return None, None
        tag_start = html_text.rfind("<", 0, match.start())
        start = tag_start if tag_start != -1 else match.start()
        section = html_text[start : start + 8000]
        section_text = cls._strip_tags(section)
        if not section_text:
            return None, None
        seller_name = None
        location_city = None
        seller_match = re.search(r'DealerScrollLink[^"]*"[^>]*>(.*?)</a>', section, flags=re.IGNORECASE | re.DOTALL)
        if not seller_match:
            seller_match = re.search(r'MainSellerInfo_title[^"]*"[^>]*>(.*?)</div>', section, flags=re.IGNORECASE | re.DOTALL)
        seller_name = cls._strip_tags(seller_match.group(1)) if seller_match else None
        address_match = re.search(r'MainSellerInfo_address[^"]*"[^>]*>(.*?)</div>', section, flags=re.IGNORECASE | re.DOTALL)
        address_text = cls._strip_tags(address_match.group(1)) if address_match else section_text
        location_match = re.search(r"\b[A-Z]{2}-\d{5}\s+(.+)$", address_text or "")
        if location_match:
            location_city = clean_whitespace(location_match.group(1))
        return seller_name, location_city

    @classmethod
    def _extract_title_fallback(cls, html_text: str) -> str:
        match = re.search(r"<title>(.*?)</title>", html_text, flags=re.IGNORECASE | re.DOTALL)
        title = cls._strip_tags(match.group(1)) if match else None
        if not title:
            return ""
        return re.sub(r"\s+pentru\s+\d.*$", "", title, flags=re.IGNORECASE).strip()

    @staticmethod
    def _extract_image_url(html_text: str) -> str | None:
        candidates: list[tuple[int, str]] = []
        for match in re.finditer(r"<img\b[^>]*>", html_text, flags=re.IGNORECASE):
            tag = match.group(0)
            src_match = re.search(r'src="([^"]*img\.classistatic\.de[^"]*)"', tag, flags=re.IGNORECASE)
            if not src_match:
                continue
            src = html_lib.unescape(src_match.group(1))
            class_match = re.search(r'class="([^"]*)"', tag, flags=re.IGNORECASE)
            alt_match = re.search(r'alt="([^"]*)"', tag, flags=re.IGNORECASE)
            class_name = class_match.group(1) if class_match else ""
            alt = html_lib.unescape(alt_match.group(1)).strip() if alt_match else ""

            score = 0
            if "ImageSlide_inline" in class_name:
                score += 100
            if alt and alt.casefold() != "alt":
                score += 30
            if "mo-1600" in src:
                score += 10
            if "HeroBanner" in class_name:
                score -= 100
            if "Thumbnail" in class_name:
                score -= 40
            if not alt:
                score -= 20

            candidates.append((score, src))

        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    @classmethod
    def _extract_image_alt(cls, html_text: str) -> str | None:
        match = re.search(r'<img\b[^>]*alt="([^"]+)"[^>]*src="[^"]*img\.classistatic\.de', html_text, flags=re.IGNORECASE)
        return cls._strip_tags(match.group(1)) if match else None
