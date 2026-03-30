from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class CarListing:
    source: str
    listing_id: str | None
    url: str
    title: str
    make: str | None = None
    model: str | None = None
    version: str | None = None
    price_value: float | None = None
    currency: str | None = None
    price_indicator: str | None = None
    seller_name: str | None = None
    seller_type: str | None = None
    location_city: str | None = None
    location_region: str | None = None
    year: int | None = None
    first_registration: str | None = None
    mileage_km: int | None = None
    fuel_type: str | None = None
    transmission: str | None = None
    power_hp: int | None = None
    engine_capacity_cm3: int | None = None
    body_type: str | None = None
    description: str | None = None
    scraped_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
