"""Service wiring: the one workflow every surface shares.

On first use the service generates the dataset and loads it into
the store (insert-only — a store that already holds a manifest is
left exactly as it is). All reads go through the store port; all
model calls go through the model port.
"""

from __future__ import annotations

import logging

from . import demand as demand_engine
from .config import Settings, load_settings
from .generator import PRODUCTS, load_dataset
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

    # -- demand engine (R2) ------------------------------------------

    def estimate_demand(self, district_id, product, crop_year, season, as_of) -> dict:
        """Compute-or-return the head estimate for one triple.

        Idempotent on the fact fingerprint: an unchanged fact set
        returns the stored artefact; changed facts store a new
        artefact superseding the old head by link."""
        artefact = demand_engine.compute_estimate(
            self.store, district_id, product, crop_year, season, as_of
        )
        rows = self.store.list_estimates(district_id, product, crop_year, season)
        head = demand_engine.head_of(rows, "estimate_id")
        if head is not None and head["fact_fingerprint"] == artefact.fact_fingerprint:
            return self.get_estimate(head["estimate_id"])
        artefact = artefact.model_copy(
            update={"supersedes": head["estimate_id"] if head else None}
        )
        self.store.insert_estimate(
            artefact.model_dump(exclude={"contributions"}),
            [line.model_dump() for line in artefact.contributions],
        )
        log.info("estimate stored: %s", artefact.estimate_id)
        return self.get_estimate(artefact.estimate_id)

    def get_estimate(self, estimate_id) -> dict | None:
        row = self.store.get_estimate(estimate_id)
        if row is None:
            return None
        row["contributions"] = self.store.estimate_contributions(estimate_id)
        return row

    def verify_estimate(self, estimate_id) -> list[str]:
        row = self.store.get_estimate(estimate_id)
        if row is None:
            return [f"no such estimate: {estimate_id}"]
        return demand_engine.verify_estimate(
            row, self.store.estimate_contributions(estimate_id)
        )

    def demand_outlook(self, crop_year, season, as_of) -> dict:
        """The full district x product grid for a season, as one
        outlook artefact (compute-or-return, superseding like the
        estimates it is built from)."""
        estimates = [
            self.estimate_demand(d["district_id"], product, crop_year, season, as_of)
            for d in self.store.list_districts()
            for product in PRODUCTS
        ]
        outlook = demand_engine.build_outlook(estimates, crop_year, season, as_of)
        rows = self.store.list_outlooks(crop_year, season)
        head = demand_engine.head_of(rows, "outlook_id")
        if head is not None and head["fact_fingerprint"] == outlook.fact_fingerprint:
            return head
        outlook = outlook.model_copy(
            update={"supersedes": head["outlook_id"] if head else None}
        )
        self.store.insert_outlook(outlook.model_dump())
        log.info("outlook stored: %s", outlook.outlook_id)
        return self.store.get_outlook(outlook.outlook_id)

    def get_outlook(self, crop_year, season) -> dict | None:
        return demand_engine.head_of(
            self.store.list_outlooks(crop_year, season), "outlook_id"
        )

    def verify_outlook(self, outlook_id) -> list[str]:
        row = self.store.get_outlook(outlook_id)
        if row is None:
            return [f"no such outlook: {outlook_id}"]
        return demand_engine.verify_outlook(self.store, row)

    def draft_outlook_narrative(self, crop_year, season, as_of) -> dict:
        outlook = self.demand_outlook(crop_year, season, as_of)
        narrator = demand_engine.OutlookNarrator(self.store, self.model)
        return narrator.draft(outlook, as_of)

    def verify_narrative(self, narrative_id) -> list[str]:
        row = self.store.get_narrative(narrative_id)
        if row is None:
            return [f"no such narrative: {narrative_id}"]
        narrator = demand_engine.OutlookNarrator(self.store, self.model)
        return narrator.verify_stored(row)

    def ready(self) -> bool:
        return self.store.get_manifest() is not None and all(
            n > 0 for n in self.store.fact_counts().values()
        )
