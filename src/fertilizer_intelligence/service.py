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
from . import policy as policy_engine
from . import supply as supply_engine
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

    def _policy_markers(self) -> dict[str, list[dict]]:
        """The board's policy markers, from the current registry
        heads: real events whose window covers the reference
        month, by series item."""
        heads = policy_engine.heads_by_event(
            self.store.list_policy_registrations()
        )
        return policy_engine.board_markers(self.store, list(heads.values()))

    def series_watch(self, series_kind, item) -> dict:
        """One series' watch read, computed from its artefacts:
        the latest movement, its open alerts, and the band those
        open alerts put it in — plus any policy markers the
        registry currently lays on the series (typed separately
        from alerts, never counted as alerts)."""
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
            "policy_markers": self._policy_markers().get(item, []),
        }

    def watch_board(self) -> list[dict]:
        """Every tracked series by band — the board a product or
        strategy team scans. Computed from artefacts, sorted so
        alert-band series come first. A row also carries the
        policy markers the registry lays on the series: current,
        real policy events whose window is open at the board's
        reference month. Markers are not alerts and never enter
        the alert counts."""
        markers = self._policy_markers()
        board = []
        for series_kind, item in self._price_series():
            watch = self.series_watch(series_kind, item)
            latest = watch["latest_movement"]
            row_markers = markers.get(item, [])
            board.append({
                "series_kind": series_kind, "item": item,
                "band": watch["band"],
                "open_alert_count": len(watch["open_alerts"]),
                "latest_month": latest["month"] if latest else None,
                "latest_mom_pct": latest["mom_pct"] if latest else None,
                "latest_baseline_pct": latest["baseline_pct"] if latest else None,
                "policy_markers": row_markers,
                "policy_marker_count": len(row_markers),
            })
        board.sort(key=lambda r: (-alert_pack.BAND_RANK[r["band"]], r["series_kind"], r["item"]))
        return board

    # -- supply tracker (R4) ---------------------------------------

    def _position_chain(self, product, as_of) -> dict:
        """Compute-or-return the stored position chain for one
        product, keyed by month. A month whose computed artefact
        is new is stored superseding that month's head by link —
        and, through the chain's opening link, every month after
        it follows."""
        by_month = {}
        for position in supply_engine.compute_position_chain(self.store, product, as_of):
            head = supply_engine.head_of(
                self.store.list_positions(product, position.month), "position_id"
            )
            if head is not None and head["fact_fingerprint"] == position.fact_fingerprint:
                by_month[position.month] = head
                continue
            position = position.model_copy(
                update={"supersedes": head["position_id"] if head else None}
            )
            dumped = position.model_dump()
            self.store.insert_supply_position(dumped, dumped["lines"])
            log.info("supply position stored: %s", position.position_id)
            by_month[position.month] = self.store.get_position(position.position_id)
        return by_month

    def supply_position(self, product, month, as_of) -> dict:
        by_month = self._position_chain(product, as_of)
        if month not in by_month:
            raise ValueError(
                f"{month} is outside the tracked period for {product}"
            )
        return by_month[month]

    def supply_positions(self, product, as_of) -> list[dict]:
        by_month = self._position_chain(product, as_of)
        return [by_month[month] for month in sorted(by_month)]

    def get_position(self, product, month) -> dict | None:
        return supply_engine.head_of(
            self.store.list_positions(product, month), "position_id"
        )

    def verify_position(self, product, month) -> list[str]:
        head = self.get_position(product, month)
        if head is None:
            return [f"no supply position stored for {product} {month}"]
        return supply_engine.verify_position(
            self.store, head, self.store.position_lines(head["position_id"])
        )

    def supply_gap(self, product, crop_year, season, as_of) -> dict:
        """Compute-or-return the season gap: the R2 outlook's
        demand rollup against the position chain and the import
        programme at this as-of. A new as-of (or changed facts)
        stores a new gap superseding the head by link."""
        outlook = self.demand_outlook(crop_year, season, as_of)
        demand_tonnes = outlook["product_rollups"].get(product)
        if demand_tonnes is None:
            raise ValueError(f"the outlook carries no rollup for {product}")
        self._position_chain(product, as_of)
        chain = supply_engine.compute_position_chain(self.store, product, as_of)
        artefact = supply_engine.compute_gap(
            self.store, product, crop_year, season, as_of,
            demand_tonnes, outlook["outlook_id"], chain,
        )
        head = supply_engine.head_of(
            self.store.list_gaps(product, crop_year, season), "gap_id"
        )
        if head is not None and head["fact_fingerprint"] == artefact.fact_fingerprint:
            return head
        artefact = artefact.model_copy(
            update={"supersedes": head["gap_id"] if head else None}
        )
        self.store.insert_supply_gap(artefact.model_dump())
        log.info("supply gap stored: %s", artefact.gap_id)
        return self.store.get_gap(artefact.gap_id)

    def get_gap(self, product, crop_year, season) -> dict | None:
        return supply_engine.head_of(
            self.store.list_gaps(product, crop_year, season), "gap_id"
        )

    def verify_gap(self, product, crop_year, season) -> list[str]:
        head = self.get_gap(product, crop_year, season)
        if head is None:
            return [f"no supply gap stored for {product} {crop_year} {season}"]
        return supply_engine.verify_gap(self.store, head)

    def supply_projection(self, product, crop_year, season, as_of) -> dict:
        """Compute-or-return the projected position for a season,
        struck at the end of the as-of month. Recomputing over a
        moved assumption set (a slip, a landing, a later basis)
        stores a new projection whose assumption changes are
        named against the version it supersedes."""
        self._position_chain(product, as_of)
        chain = supply_engine.compute_position_chain(self.store, product, as_of)
        artefact = supply_engine.compute_projection(
            self.store, product, crop_year, season, as_of, chain
        )
        head = supply_engine.head_of(
            self.store.list_projections(product, crop_year, season), "projection_id"
        )
        if head is not None and head["fact_fingerprint"] == artefact.fact_fingerprint:
            return head
        changes = (
            supply_engine.diff_assumptions(head["assumption_set"], artefact.assumption_set)
            if head is not None else []
        )
        artefact = artefact.model_copy(update={
            "supersedes": head["projection_id"] if head else None,
            "assumption_changes": changes,
        })
        self.store.insert_supply_projection(artefact.model_dump())
        log.info("supply projection stored: %s", artefact.projection_id)
        return self.store.get_projection(artefact.projection_id)

    def get_projection(self, product, crop_year, season) -> dict | None:
        return supply_engine.head_of(
            self.store.list_projections(product, crop_year, season), "projection_id"
        )

    def verify_projection(self, product, crop_year, season) -> list[str]:
        head = self.get_projection(product, crop_year, season)
        if head is None:
            return [f"no supply projection stored for {product} {crop_year} {season}"]
        return supply_engine.verify_projection(self.store, head)

    # -- policy registry (R5) ------------------------------------

    def register_policy_events(self, as_of) -> dict:
        """The registration pass over the recorded policy facts:
        each fact becomes a registry artefact under the pack's
        mapping. Idempotent — a fact whose registration is
        already the head is left exactly as it is; a changed
        mapping would store a new registration superseding the
        head by link."""
        registered = already = 0
        for fact in self.store.policy_events():
            artefact = policy_engine.registration_from_fact(fact, as_of)
            head = policy_engine.head_of(
                self.store.list_policy_registrations(fact["event_id"]),
                "registry_id",
            )
            if head is not None and head["fact_fingerprint"] == artefact.fact_fingerprint:
                already += 1
                continue
            artefact = artefact.model_copy(
                update={"supersedes": head["registry_id"] if head else None}
            )
            self.store.insert_policy_registration(artefact.model_dump())
            log.info("policy event registered: %s", artefact.registry_id)
            registered += 1
        heads = policy_engine.heads_by_event(self.store.list_policy_registrations())
        return {
            "as_of": as_of,
            "registered": registered,
            "already_registered": already,
            "events_total": len(heads),
        }

    def register_policy_event(self, spec: dict, as_of) -> dict:
        """Register one event stated at the desk (a new event, a
        correction, or a hypothetical proposal), validated
        against the pack. Same content as the current head is a
        no-op returning the head; different content stores a new
        registration superseding the head by link — the only way
        a hypothetical becomes real, or a scope gets corrected."""
        district_ids = {d["district_id"] for d in self.store.list_districts()}
        artefact = policy_engine.build_registration(spec, district_ids, as_of)
        head = policy_engine.head_of(
            self.store.list_policy_registrations(artefact.event_id), "registry_id"
        )
        if head is not None and head["fact_fingerprint"] == artefact.fact_fingerprint:
            return head
        artefact = artefact.model_copy(
            update={"supersedes": head["registry_id"] if head else None}
        )
        self.store.insert_policy_registration(artefact.model_dump())
        log.info("policy event registered at the desk: %s", artefact.registry_id)
        return self.store.get_policy_registration(artefact.registry_id)

    def get_policy_event(self, registry_id) -> dict | None:
        return self.store.get_policy_registration(registry_id)

    def list_policy_events(self, hypothetical=None, event_class=None) -> list[dict]:
        """The current registration per event id (chain heads),
        optionally filtered — hypothetical proposals and real
        events list separately when the flag filter is given."""
        heads = policy_engine.heads_by_event(
            self.store.list_policy_registrations()
        )
        out = [heads[event_id] for event_id in sorted(heads)]
        if hypothetical is not None:
            out = [e for e in out if e["hypothetical"] == hypothetical]
        if event_class is not None:
            out = [e for e in out if e["event_class"] == event_class]
        return out

    def policy_event_versions(self, event_id) -> list[dict]:
        """Every recorded version of one event id, oldest link
        first — the chain a supersession walked."""
        return self.store.list_policy_registrations(event_id)

    def verify_policy_event(self, registry_id) -> list[str]:
        row = self.store.get_policy_registration(registry_id)
        if row is None:
            return [f"no such policy registration: {registry_id}"]
        return policy_engine.verify_policy_event(self.store, row)

    def policy_impact(self, registry_id, as_of) -> dict:
        """Compute-or-return the impact note for one registry
        event: the demand outlooks and position chains the note
        can name are ensured first, then the scope query runs
        over the stored heads. A hypothetical is refused — a
        proposed policy earns no note."""
        event = self.store.get_policy_registration(registry_id)
        if event is None:
            raise ValueError(f"no such policy registration: {registry_id}")
        if event["hypothetical"]:
            raise ValueError(
                f"policy event {event['event_id']} is hypothetical: a "
                "proposed policy earns no impact note — it is listed "
                "with its stated effect only"
            )
        for crop_year, season in policy_engine.overlapping_seasons(event):
            self.demand_outlook(crop_year, season, as_of)
        positionable = supply_engine.positionable_products(self.store)
        for product in event["products"]:
            if product in positionable:
                self._position_chain(product, as_of)
        artefact = policy_engine.compute_impact_note(self.store, event, as_of)
        head = policy_engine.head_of(
            self.store.list_policy_impact_notes(registry_id), "note_id"
        )
        if head is not None and head["fact_fingerprint"] == artefact.fact_fingerprint:
            return head
        artefact = artefact.model_copy(
            update={"supersedes": head["note_id"] if head else None}
        )
        self.store.insert_policy_impact_note(artefact.model_dump())
        log.info("policy impact note stored: %s", artefact.note_id)
        return self.store.get_policy_impact_note(artefact.note_id)

    def get_policy_impact(self, registry_id) -> dict | None:
        return policy_engine.head_of(
            self.store.list_policy_impact_notes(registry_id), "note_id"
        )

    def verify_policy_impact(self, registry_id) -> list[str]:
        head = self.get_policy_impact(registry_id)
        if head is None:
            return [f"no impact note stored for registration {registry_id}"]
        return policy_engine.verify_impact_note(self.store, head)

    def ready(self) -> bool:
        return self.store.get_manifest() is not None and all(
            n > 0 for n in self.store.fact_counts().values()
        )
