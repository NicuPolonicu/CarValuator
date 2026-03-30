from __future__ import annotations

import re
from typing import Any

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


class MobileDeBlockedError(RuntimeError):
    """Raised when mobile.de blocks automated access."""


class MobileDeScraper:
    source = "mobilede"

    def __init__(
        self,
        headless: bool = True,
        timeout_ms: int = 60_000,
        channel: str = "msedge",
    ) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.channel = channel

    def scrape_search(self, url: str, pages: int = 1, delay_seconds: float = 2.0) -> list[CarListing]:
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

    def _open_browser(self, playwright: Any) -> tuple[Any, Any, Any]:
        browser = playwright.chromium.launch(
            channel=self.channel,
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled"],
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
            power_hp=int(spec_match.group(5)) if spec_match else None,
            engine_capacity_cm3=None,
            body_type=None,
            description=None,
            raw=card,
        )

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
