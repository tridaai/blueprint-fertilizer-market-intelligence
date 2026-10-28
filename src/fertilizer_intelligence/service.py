"""Service wiring: the one workflow every surface shares.

On first use the service generates the dataset and loads it into
the store (insert-only — a store that already holds a manifest is
left exactly as it is). All reads go through the store port; all
model calls go through the model port.
"""

from __future__ import annotations

import logging

from .config import Settings, load_settings
from .generator import load_dataset
from .modelport import get_model_port
from .store import MarketStore

log = logging.getLogger("fertilizer_intelligence.service")


class MarketService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or load_settings()
        self.store = MarketStore(self.settings)
        self.model = get_model_port(self.settings.model_profile)
        self.manifest = self._ensure_dataset()

    def _ensure_dataset(self) -> dict:
        existing = self.store.get_manifest()
        if existing is not None:
            log.info("dataset already present (generator %s)", existing["generator_version"])
            return existing
        manifest = load_dataset(self.store)
        log.info("dataset generated and loaded: %s facts", manifest["counts"])
        return manifest

    # -- reads ---------------------------------------------------------

    def demand_inputs(self, district_id: str, crop_year: str, season: str) -> dict:
        """Everything the R2 demand engine will consume for one
        district-season: area/crop mix, monsoon, soil, and the
        historical consumption derived from them."""
        return {
            "district_id": district_id,
            "crop_year": crop_year,
            "season": season,
            "area": self.store.area_facts(district_id, crop_year, season),
            "monsoon": self.store.monsoon_facts(district_id, crop_year, season),
            "soil": self.store.soil_facts(district_id),
            "consumption": self.store.consumption_facts(district_id, crop_year, season),
        }

    def ready(self) -> bool:
        return self.store.get_manifest() is not None and all(
            n > 0 for n in self.store.fact_counts().values()
        )
