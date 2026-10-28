"""Service wiring: the one workflow every surface shares.

On first use the service generates the dataset and loads it into
the store (insert-only — a store that already holds a manifest is
left exactly as it is). All reads go through the store port; all
model calls go through the model port.
"""

from __future__ import annotations

import logging

from . import alert_rules as alert_pack
from . import demand as demand_engine
from . import movements as movement_engine
from .config import Settings, load_settings
from .generator import PRODUCTS, load_dataset
from .modelport import get_model_port
from .movements import AlertStateError
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

    # -- price watch (R3) --------------------------------------------

    def _price_series(self) -> list[tuple[str, str]]:
        seen = {(p["series_kind"], p["item"]) for p in self.store.price_points()}
        return sorted(seen)

    def run_price_watch(self, as_of) -> dict:
        """The firing pass: compute every series' movements, store
        the new ones, fire the rule pack over the stored movements,
        store the new alerts. Idempotent — a second pass over
        unchanged prices stores nothing and fires nothing new."""
        movements_stored = 0
        for series_kind, item in self._price_series():
            for movement in movement_engine.compute_movements(
                self.store, series_kind, item, as_of
            ):
                if self.store.get_movement(movement.movement_id) is None:
                    self.store.insert_movement(movement.model_dump())
                    movements_stored += 1
        alerts_fired = 0
        for series_kind, item in self._price_series():
            stored = self.store.list_movements(series_kind, item)
            for payload in movement_engine.evaluate_movements(stored):
                alert_id = movement_engine.alert_id_for(payload)
                if self.store.get_alert(alert_id) is not None:
                    continue
                alert = movement_engine.PriceAlert(
                    alert_id=alert_id, rules_version=alert_pack.RULES_VERSION,
                    as_of=as_of, **payload,
                )
                self.store.insert_alert(alert.model_dump())
                alerts_fired += 1
        summary = {
            "as_of": as_of,
            "rules_version": alert_pack.RULES_VERSION,
            "movements_stored": movements_stored,
            "movements_total": len(self.store.list_movements()),
            "alerts_fired": alerts_fired,
            "alerts_total": len(self.store.list_alerts()),
        }
        log.info("price watch: %s", summary)
        return summary

    def verify_movement(self, movement_id) -> list[str]:
        row = self.store.get_movement(movement_id)
        if row is None:
            return [f"no such movement: {movement_id}"]
        return movement_engine.verify_movement(self.store, row)

    def _alert_with_state(self, alert: dict) -> dict:
        acts = self.store.list_alert_acts(alert["alert_id"])
        alert = dict(alert)
        alert["acts"] = acts
        alert["state"] = movement_engine.derive_state(acts)
        return alert

    def get_alert(self, alert_id) -> dict | None:
        row = self.store.get_alert(alert_id)
        return self._alert_with_state(row) if row is not None else None

    def list_alerts(self, series_kind=None, item=None, rule_id=None, state=None) -> list[dict]:
        alerts = [
            self._alert_with_state(a)
            for a in self.store.list_alerts(series_kind, item, rule_id)
        ]
        if state is not None:
            alerts = [a for a in alerts if a["state"] == state]
        return alerts

    def verify_alert(self, alert_id) -> list[str]:
        row = self.store.get_alert(alert_id)
        if row is None:
            return [f"no such alert: {alert_id}"]
        return movement_engine.verify_alert(self.store, row)

    def _record_act(self, alert_id, act, actor, as_of, note=None, closing_reason=None) -> dict:
        alert = self.store.get_alert(alert_id)
        if alert is None:
            raise AlertStateError(f"no such alert: {alert_id}")
        if not actor or not actor.strip():
            raise ValueError("an alert act needs a named actor")
        acts = self.store.list_alert_acts(alert_id)
        state = movement_engine.derive_state(acts)
        if act == "acknowledge":
            if state != "open":
                raise AlertStateError(
                    f"alert {alert_id} is {state}: only an open alert can be acknowledged"
                )
            if not note or not note.strip():
                raise ValueError("an acknowledgement needs a note")
        elif act == "close":
            if state == "closed":
                raise AlertStateError(f"alert {alert_id} is already closed")
            if closing_reason not in alert_pack.CLOSING_REASONS:
                raise ValueError(
                    f"closing reason must be one of {sorted(alert_pack.CLOSING_REASONS)}"
                )
        act_row = {
            "act_id": f"ACT-{alert_id}-{len(acts) + 1:03d}",
            "alert_id": alert_id, "act": act, "actor": actor.strip(),
            "note": note, "closing_reason": closing_reason, "as_of": as_of,
        }
        self.store.insert_alert_act(act_row)
        log.info("alert act recorded: %s", act_row)
        return self.get_alert(alert_id)

    def acknowledge_alert(self, alert_id, actor, note, as_of) -> dict:
        return self._record_act(alert_id, "acknowledge", actor, as_of, note=note)

    def close_alert(self, alert_id, actor, closing_reason, as_of) -> dict:
        return self._record_act(
            alert_id, "close", actor, as_of, closing_reason=closing_reason
        )

    def series_watch(self, series_kind, item) -> dict:
        """One series' watch read, computed from its artefacts:
        the latest movement, its open alerts, and the band those
        open alerts put it in."""
        movements = self.store.list_movements(series_kind, item)
        alerts = self.list_alerts(series_kind, item)
        open_alerts = [a for a in alerts if a["state"] != "closed"]
        band = "none"
        for alert in open_alerts:
            if alert_pack.BAND_RANK[alert["band"]] > alert_pack.BAND_RANK[band]:
                band = alert["band"]
        return {
            "series_kind": series_kind, "item": item,
            "latest_movement": movements[-1] if movements else None,
            "open_alerts": open_alerts,
            "band": band,
        }

    def watch_board(self) -> list[dict]:
        """Every tracked series by band — the board a product or
        strategy team scans. Computed from artefacts, sorted so
        alert-band series come first."""
        board = []
        for series_kind, item in self._price_series():
            watch = self.series_watch(series_kind, item)
            latest = watch["latest_movement"]
            board.append({
                "series_kind": series_kind, "item": item,
                "band": watch["band"],
                "open_alert_count": len(watch["open_alerts"]),
                "latest_month": latest["month"] if latest else None,
                "latest_mom_pct": latest["mom_pct"] if latest else None,
                "latest_baseline_pct": latest["baseline_pct"] if latest else None,
            })
        board.sort(key=lambda r: (-alert_pack.BAND_RANK[r["band"]], r["series_kind"], r["item"]))
        return board

    def ready(self) -> bool:
        return self.store.get_manifest() is not None and all(
            n > 0 for n in self.store.fact_counts().values()
        )
