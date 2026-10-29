"""Service wiring: the one workflow every surface shares.

On first use the service generates the dataset and loads it into
the store (insert-only — a store that already holds a manifest is
left exactly as it is). All reads go through the store port; all
model calls go through the model port.
"""

from __future__ import annotations

import json
import logging

from . import alert_rules as alert_pack
from . import brief as brief_engine
from . import brief_rules as brief_pack
from . import dashboard as dashboard_engine
from . import demand as demand_engine
from . import field as field_engine
from . import field_rules as field_pack
from . import ingest as ingest_engine
from . import ingest_rules as ingest_pack
from . import movements as movement_engine
from . import policy as policy_engine
from . import scenario as scenario_engine
from . import share as share_engine
from . import supply as supply_engine
from .config import Settings, load_settings
from .generator import CROP_YEARS, PRODUCTS, load_dataset
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
        if self.store.get_estimate(artefact.estimate_id) is not None:
            # Already on record (struck earlier, since
            # superseded as head): compute-or-return means
            # return it — re-inserting would violate the
            # insert-only store's uniqueness.
            return self.get_estimate(artefact.estimate_id)
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
        if self.store.get_outlook(outlook.outlook_id) is not None:
            return self.store.get_outlook(outlook.outlook_id)
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
            existing = self.store.get_position(position.position_id)
            if existing is not None:
                by_month[position.month] = existing
                continue
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
        if self.store.get_gap(artefact.gap_id) is not None:
            return self.store.get_gap(artefact.gap_id)
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
        existing = self.store.get_projection(artefact.projection_id)
        if existing is not None:
            # Already on record (struck earlier at this
            # basis, since superseded as head by a later
            # basis): compute-or-return means return it —
            # re-inserting would violate the insert-only
            # store's uniqueness.
            return existing
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
        head = policy_engine.head_of(
            self.store.list_policy_registrations(spec.get("event_id")), "registry_id"
        )
        if head is not None and not spec.get("recorded_on"):
            # The recorded date is a property of the event, not
            # of this registration act: a re-registration that
            # does not restate it inherits the head's, so the
            # same content stated again is the same artefact.
            spec = {**spec, "recorded_on": head["recorded_on"]}
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
        """Every recorded version of one event id, in chain
        order — the first registration first, each successor
        after the version it supersedes."""
        rows = self.store.list_policy_registrations(event_id)
        by_id = {r["registry_id"]: r for r in rows}
        head = policy_engine.head_of(rows, "registry_id")
        chain = []
        current = head
        while current is not None:
            chain.append(current)
            current = by_id.get(current["supersedes"])
        chain.reverse()
        return chain

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
        if self.store.get_policy_impact_note(artefact.note_id) is not None:
            return self.store.get_policy_impact_note(artefact.note_id)
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

    # -- competitor & share intelligence (R6) ------------------

    def build_competitor_observations(self) -> dict:
        """The observation pass over the tracked competitor
        points: each point becomes a CompetitorObservation
        artefact with its provenance on its face. Idempotent —
        a point whose observation is already stored is left
        exactly as it is."""
        districts = self.store.list_districts()
        stored = already = 0
        for point in self.store.competitor_points():
            artefact = share_engine.observation_from_point(point, districts)
            if self.store.get_competitor_observation(artefact.observation_id) is not None:
                already += 1
                continue
            self.store.insert_competitor_observation(artefact.model_dump())
            stored += 1
        return {
            "observations_stored": stored,
            "already_present": already,
            "observations_total": len(self.store.list_competitor_observations()),
        }

    def get_competitor_observation(self, observation_id) -> dict | None:
        return self.store.get_competitor_observation(observation_id)

    def list_competitor_observations(
        self, competitor=None, region=None, product=None, season=None
    ) -> list[dict]:
        return self.store.list_competitor_observations(
            competitor, region, product, season
        )

    def verify_competitor_observation(self, observation_id) -> list[str]:
        row = self.store.get_competitor_observation(observation_id)
        if row is None:
            return [f"no such competitor observation: {observation_id}"]
        return share_engine.verify_observation(self.store, row)

    def market_share(self, district_id, product, crop_year, season, as_of=None) -> dict:
        """Compute-or-return the head share for one
        district x product x season at a read date (default:
        the season's close). The season outlook is ensured
        first — the region structure anchor and the demand
        denominator read the head R2 estimates. A recomputation over
        changed inputs stores a new share superseding the head
        for the same read date by link."""
        self.build_competitor_observations()
        self.demand_outlook(crop_year, season, as_of or share_engine.season_close(crop_year, season))
        read_date = as_of or share_engine.season_close(crop_year, season)
        artefact = share_engine.compute_share(
            self.store, district_id, product, crop_year, season, read_date
        )
        if self.store.get_share(artefact.share_id) is not None:
            return self.store.get_share(artefact.share_id)
        head = share_engine.head_of(
            self.store.list_shares(district_id, product, crop_year, season, read_date),
            "share_id",
        )
        if head is not None and head["fact_fingerprint"] == artefact.fact_fingerprint:
            return head
        artefact = artefact.model_copy(
            update={"supersedes": head["share_id"] if head else None}
        )
        self.store.insert_share(artefact.model_dump())
        log.info("market share stored: %s", artefact.share_id)
        return self.store.get_share(artefact.share_id)

    def get_share(self, district_id, product, crop_year, season, as_of=None) -> dict | None:
        read_date = as_of or share_engine.season_close(crop_year, season)
        return share_engine.head_of(
            self.store.list_shares(district_id, product, crop_year, season, read_date),
            "share_id",
        )

    def verify_share(self, share_id) -> list[str]:
        row = self.store.get_share(share_id)
        if row is None:
            return [f"no such market share: {share_id}"]
        return share_engine.verify_share(self.store, row)

    def share_stale_exclusions(self, district_id, product, crop_year, season, as_of=None) -> dict:
        """The stale-exclusion read for one share: exactly
        which observations the headline excluded, and why —
        the named exclusion the share artefact carries, served
        on its own. Compute-or-return first, like the share
        read itself, so the exclusion read stands on its own."""
        self.market_share(district_id, product, crop_year, season, as_of)
        share = self.get_share(district_id, product, crop_year, season, as_of)
        if share is None:
            raise ValueError(
                f"no market share computed for {district_id} {product} "
                f"{crop_year} {season}"
            )
        headline = share["headline"]
        return {
            "share_id": share["share_id"],
            "district_id": district_id,
            "product": product,
            "crop_year": crop_year,
            "season": season,
            "as_of": share["as_of"],
            "status": share["status"],
            "headline_note": share["headline_note"],
            "excluded_observations": (
                headline["excluded_observations"] if headline else []
            ),
            "stale_count": (
                len([e for e in headline["excluded_observations"]
                      if e["reason"] == "stale"]) if headline else 0
            ),
        }

    def share_movement(self, district_id, product, season, as_of) -> dict:
        """Compute-or-return the share movement between the two
        tracked crop years for one district x product x season:
        each year's share is struck at its own season close
        (the like-for-like read), and the movement compares
        their full-season readings."""
        from_year, to_year = CROP_YEARS[0], CROP_YEARS[-1]
        from_share = self.market_share(district_id, product, from_year, season)
        to_share = self.market_share(district_id, product, to_year, season)
        artefact = share_engine.compute_movement(
            self.store, from_share, to_share, as_of
        )
        if self.store.get_share_movement(artefact.movement_id) is not None:
            return self.store.get_share_movement(artefact.movement_id)
        head = share_engine.head_of(
            self.store.list_share_movements(district_id, product, season),
            "movement_id",
        )
        if head is not None and head["fact_fingerprint"] == artefact.fact_fingerprint:
            return head
        artefact = artefact.model_copy(
            update={"supersedes": head["movement_id"] if head else None}
        )
        self.store.insert_share_movement(artefact.model_dump())
        log.info("share movement stored: %s", artefact.movement_id)
        return self.store.get_share_movement(artefact.movement_id)

    def get_share_movement(self, district_id, product, season) -> dict | None:
        return share_engine.head_of(
            self.store.list_share_movements(district_id, product, season),
            "movement_id",
        )

    def verify_share_movement(self, movement_id) -> list[str]:
        row = self.store.get_share_movement(movement_id)
        if row is None:
            return [f"no such share movement: {movement_id}"]
        return share_engine.verify_movement(self.store, row)

    # -- field signals & mobile intake (R7) -------------------

    def sync_field_reports(self, submissions, as_of) -> dict:
        """Land one outbox batch: each submission validated at
        the port, then landed exactly once. A submission the
        port refuses stops the batch with its reason — the
        submissions before it stay landed (that is the
        killed-mid-sync shape), and re-sending the whole batch
        is always safe: what already landed answers duplicate."""
        receipt = []
        for sub in submissions:
            field_engine.validate_submission(self.store, sub)
            result = field_engine.land_submission(self.store, sub, as_of)
            receipt.append({
                "submission_id": sub["submission_id"],
                "outcome": result["outcome"],
                "report_id": result["report"]["report_id"],
            })
        return {
            "as_of": as_of,
            "received": len(submissions),
            "landed": sum(1 for r in receipt if r["outcome"] == "landed"),
            "duplicates": sum(1 for r in receipt if r["outcome"] == "duplicate"),
            "conflicts": sum(1 for r in receipt if r["outcome"] == "conflict"),
            "receipt": receipt,
            "reports_total": len(self.store.list_field_report_artefacts()),
        }

    def promote_planted_field_reports(self, as_of) -> dict:
        """Promote the twelve planted R1 field reports through
        the same landing machinery the mobile intake uses, so
        one lifecycle — review, weighting, conflict — covers
        every field signal. Idempotent: a second promotion
        lands nothing."""
        submissions = [
            field_engine.planted_submission(fact)
            for fact in self.store.field_reports()
        ]
        return self.sync_field_reports(submissions, as_of)

    def list_field_reports(self, state=None, district_id=None, product=None) -> list[dict]:
        """Every landed report with its acts, derived review
        state and conflict standing — optionally filtered to
        one state (the verification queue is the unreviewed
        filter), district or product."""
        views = [
            field_engine.report_view(self.store, report)
            for report in self.store.list_field_report_artefacts(
                district_id=district_id, product=product
            )
        ]
        if state is not None:
            views = [v for v in views if v["review_state"] == state]
        return views

    def get_field_report(self, report_id) -> dict | None:
        row = self.store.get_field_report_artefact(report_id)
        return field_engine.report_view(self.store, row) if row is not None else None

    def verify_field_report(self, report_id) -> list[str]:
        row = self.store.get_field_report_artefact(report_id)
        if row is None:
            return [f"no such field report: {report_id}"]
        return field_engine.verify_report(self.store, row)

    def review_field_report(self, report_id, act, actor, reason, as_of, note=None) -> dict:
        """Record one reviewer act against a report. The act,
        its reason vocabulary and the transitions the current
        state allows are the pack's; the state itself is never
        written — it stays the fold of the acts."""
        report = self.store.get_field_report_artefact(report_id)
        if report is None:
            raise ValueError(f"no such field report: {report_id}")
        if not actor or not actor.strip():
            raise ValueError("a review act needs a named reviewer")
        if act not in field_pack.ACTS:
            raise ValueError(
                f"review act must be one of {sorted(field_pack.ACTS)}"
            )
        if reason not in field_pack.ACT_REASONS[act]:
            raise ValueError(
                f"a {act} act's reason must be one of "
                f"{sorted(field_pack.ACT_REASONS[act])}"
            )
        acts = self.store.list_field_review_acts(report_id)
        state = field_engine.derive_review_state(acts)
        if state == field_pack.STATE_REJECTED:
            raise field_engine.FieldReviewError(
                f"report {report_id} is rejected: rejection is terminal — "
                "a corrected observation must arrive as a new report"
            )
        if act == field_pack.ACT_CONFIRM and state == field_pack.STATE_CONFIRMED:
            raise field_engine.FieldReviewError(
                f"report {report_id} is already confirmed"
            )
        if act == field_pack.ACT_QUERY and state == field_pack.STATE_QUERIED:
            raise field_engine.FieldReviewError(
                f"report {report_id} is already queried — "
                "confirm it or reject it"
            )
        act_row = {
            "act_id": f"FRA-{report_id}-{len(acts) + 1:03d}",
            "report_id": report_id, "act": act, "actor": actor.strip(),
            "reason": reason, "note": note, "as_of": as_of,
        }
        self.store.insert_field_review_act(act_row)
        log.info("field review act recorded: %s", act_row)
        return self.get_field_report(report_id)

    def field_signal_assessment(self, district_id, product, crop_year, season, as_of) -> dict:
        """Compute-or-return the weighting assessment for one
        cell: the head R2 estimate is ensured first (it is
        read, never mutated), then the cell's reports fold
        against it under the field pack. Changed inputs — a
        new report, a new act, a superseding estimate — store
        a new assessment superseding the head by link."""
        self.estimate_demand(district_id, product, crop_year, season, as_of)
        artefact = field_engine.compute_assessment(
            self.store, district_id, product, crop_year, season, as_of
        )
        if self.store.get_field_assessment(artefact.assessment_id) is not None:
            return self.store.get_field_assessment(artefact.assessment_id)
        head = field_engine.head_of(
            self.store.list_field_assessments(
                district_id, product, crop_year, season, as_of
            ),
            "assessment_id",
        )
        if head is not None and head["fact_fingerprint"] == artefact.fact_fingerprint:
            return head
        artefact = artefact.model_copy(
            update={"supersedes": head["assessment_id"] if head else None}
        )
        self.store.insert_field_assessment(artefact.model_dump())
        log.info("field assessment stored: %s", artefact.assessment_id)
        return self.store.get_field_assessment(artefact.assessment_id)

    def get_field_assessment(self, district_id, product, crop_year, season, as_of=None) -> dict | None:
        return field_engine.head_of(
            self.store.list_field_assessments(
                district_id, product, crop_year, season, as_of
            ),
            "assessment_id",
        )

    def verify_field_assessment(self, assessment_id) -> list[str]:
        row = self.store.get_field_assessment(assessment_id)
        if row is None:
            return [f"no such field assessment: {assessment_id}"]
        return field_engine.verify_assessment(self.store, row)

    # -- plain-language dashboards (R8) ---------------------------------

    def ask_question(self, question, asked_by, as_of, role=None,
                     name=None, port=None) -> dict:
        """Ask a plain-language business question. The
        question parses into a dashboard spec under the
        dashboard pack — the offline profile's deterministic
        grammar by default; a hosted profile's proposals are
        validated against the governed schema, and a proposal
        that does not fit is refused, recorded, and rendered
        as a gap. The spec is stored insert-only with its
        artefact bindings resolved at ask time
        (compute-or-return). asked_by is required: a question
        in this system is attributed, never anonymous."""
        if not asked_by:
            raise ValueError(
                "asked_by is required — a dashboard question is "
                "attributed, never anonymous")
        if port is not None or self.settings.model_profile != "offline":
            model_port = port or get_model_port(self.settings.model_profile)
            panels, parse = dashboard_engine.parse_question_model(
                self.store, model_port, question)
        else:
            panels, parse = dashboard_engine.parse_question_grammar(
                self.store, question)
        return self._store_spec(
            question, asked_by, as_of, panels, parse,
            role=role, name=name,
            saved_by=asked_by if name else None)

    def role_default_dashboard(self, role, asked_by, as_of) -> dict:
        """A role's default dashboard, built from the pack's
        stated panel list through the same spec machinery as
        an asked question. An unknown role is refused by the
        pack lookup."""
        if not asked_by:
            raise ValueError(
                "asked_by is required — a dashboard is attributed, "
                "never anonymous")
        label, panels = dashboard_engine.role_default_panels(
            self.store, role)
        parse = {"profile": "pack", "model": "role_default",
                 "rules": [f"role_default:{role}"], "refusals": [],
                 "notes": []}
        return self._store_spec(
            label, asked_by, as_of, panels, parse, role=role,
            name=f"default:{role}", saved_by=asked_by)

    def _store_spec(self, question, asked_by, as_of, panels, parse,
                    role=None, name=None, saved_by=None) -> dict:
        for panel in panels:
            if panel.kind != "gap":
                resolved = dashboard_engine.resolve_panel(
                    self, panel.model_dump(), as_of)
                panel.binding_artefact_ids = resolved["artefact_ids"]
        spec = dashboard_engine.build_spec(
            question, asked_by, as_of, panels, parse,
            role=role, name=name, saved_by=saved_by)
        existing = self.store.dashboard_spec_by_fingerprint(spec.fingerprint)
        if existing is not None:
            return existing
        self.store.insert_dashboard_spec(spec.model_dump())
        return spec.model_dump()

    def get_dashboard_spec(self, spec_id) -> dict | None:
        return self.store.get_dashboard_spec(spec_id)

    def list_dashboard_specs(self, name=None, saved_by=None) -> list[dict]:
        return self.store.dashboard_specs(name=name, saved_by=saved_by)

    def assemble_dashboard(self, spec_id, assembled_on) -> dict:
        """Assemble (or return) the dashboard for a spec at a
        date. Assembly re-resolves every panel to the current
        head, verifies every figure against its artefact
        before storing, and diffs against the previous
        assembly. A figure mismatch refuses the whole
        dashboard — nothing partial is stored."""
        spec = self.store.get_dashboard_spec(spec_id)
        if spec is None:
            raise ValueError(f"no such dashboard spec: {spec_id}")
        assembly = dashboard_engine.assemble(self, spec, assembled_on)
        existing = self.store.get_dashboard_assembly(assembly.assembly_id)
        if existing is not None:
            return existing
        self.store.insert_dashboard_assembly(assembly.model_dump())
        return assembly.model_dump()

    def get_dashboard_assembly(self, assembly_id) -> dict | None:
        return self.store.get_dashboard_assembly(assembly_id)

    def list_dashboard_assemblies(self, spec_id) -> list[dict]:
        return self.store.dashboard_assemblies(spec_id)

    def dashboard_html(self, spec_id) -> str | None:
        """The current head assembly's rendered page for a
        spec, assembling at the spec's as-of when the spec
        has never been assembled."""
        spec = self.store.get_dashboard_spec(spec_id)
        if spec is None:
            return None
        head = dashboard_engine.head_of(
            self.store.dashboard_assemblies(spec_id), "assembly_id")
        if head is not None:
            return head["html"]
        return self.assemble_dashboard(spec_id, spec["as_of"])["html"]

    def verify_dashboard(self, assembly_id) -> dict:
        assembly = self.store.get_dashboard_assembly(assembly_id)
        if assembly is None:
            raise ValueError(f"no such dashboard assembly: {assembly_id}")
        problems = dashboard_engine.verify_assembly(self.store, assembly)
        return {"assembly_id": assembly_id,
                "verified": not problems, "problems": problems}

    def verify_dashboard_spec(self, spec_id) -> dict:
        """Re-perform a spec: a grammar-parsed spec must
        re-parse to the same panels, and every recorded parse
        refusal must be carried by a gap panel on the spec —
        a refusal that exists only in the provenance, with no
        gap rendered for it, is a defect."""
        spec = self.store.get_dashboard_spec(spec_id)
        if spec is None:
            raise ValueError(f"no such dashboard spec: {spec_id}")
        problems: list[str] = []
        if spec["parse"].get("profile") == "offline":
            panels, _ = dashboard_engine.parse_question_grammar(
                self.store, spec["question"])
            reparsed = [(p.kind, p.scope) for p in panels]
            stored = [(p["kind"], p["scope"]) for p in spec["panels"]]
            if reparsed != stored:
                problems.append(
                    "the spec's panels do not re-perform from its "
                    "question under the grammar")
        refusals = spec["parse"].get("refusals", [])
        gap_refusals = [
            p for p in spec["panels"]
            if p["origin"].get("rule") == "model:refused_proposal"
        ]
        if len(gap_refusals) < len(refusals):
            problems.append(
                f"{len(refusals)} parse refusals are recorded but only "
                f"{len(gap_refusals)} gap panels carry them")
        return {"spec_id": spec_id, "verified": not problems,
                "problems": problems}

    # -- Round 9: scenario forks & planning options --------------------
    # A fork is a pinned, hypothetical view of a head
    # artefact. Creating one never writes to a head table:
    # the engines run over a substituted fact view and only
    # the fork artefact itself is stored.

    def _scenario_base(self, kind: str, scope: dict,
                       as_of: str | None = None) -> dict:
        """The base artefact a fork pins: the head of record
        for the cell. A fork never silently strikes a new
        head at an invented date — with an explicit as_of it
        strikes (or returns) the head at that date through
        the ordinary surfaces; without one it takes the
        stored head, and a cell with no head on record is a
        refusal that says so."""
        if kind == "demand_estimate":
            if as_of is not None:
                estimate = self.estimate_demand(
                    scope["district_id"], scope["product"],
                    scope["crop_year"], scope["season"], as_of)
            else:
                estimate = supply_engine.head_of(
                    self.store.list_estimates(
                        scope["district_id"], scope["product"],
                        scope["crop_year"], scope["season"]),
                    "estimate_id")
                if estimate is None:
                    raise ValueError(
                        "no head estimate is on record for "
                        f"{scope['district_id']} {scope['product']} "
                        f"{scope['crop_year']} {scope['season']} — "
                        "strike one (or pass as_of) before forking it")
            return {**estimate,
                    "contributions": self.store.estimate_contributions(
                        estimate["estimate_id"])}
        if as_of is not None:
            return self.supply_projection(
                scope["product"], scope["crop_year"], scope["season"],
                as_of)
        projection = supply_engine.head_of(
            self.store.list_projections(
                scope["product"], scope["crop_year"], scope["season"]),
            "projection_id")
        if projection is None:
            raise ValueError(
                "no head projection is on record for "
                f"{scope['product']} {scope['crop_year']} "
                f"{scope['season']} — strike one (or pass as_of) "
                "before forking it")
        return projection

    def create_scenario(self, kind: str, scope: dict, levers: list[dict],
                        created_by: str, name: str | None = None,
                        as_of: str | None = None) -> dict:
        """Fork a head artefact with structured lever specs.
        Every spec is validated against the catalogue —
        an out-of-bounds or wrong-kind lever refuses the
        whole fork, naming the bound."""
        base = self._scenario_base(kind, scope, as_of)
        records = scenario_engine.resolve_levers(
            self.store, kind, scope, base, levers)
        return self._store_fork(kind, scope, base, records, [],
                                {"profile": "structured", "model": None,
                                 "rules": [], "refusals": [], "notes": []},
                                created_by, name)

    def ask_scenario(self, question: str, asked_by: str,
                     name: str | None = None) -> dict:
        """Fork from a plain-language request through the
        model port. The offline profile parses with the
        deterministic grammar and pins the fork to the
        question's date; parts that cannot be mapped become
        named gaps on the artefact — never dropped, never
        improvised."""
        kind0, scope0, _notes, unknown = scenario_engine.scan_scope(
            self.store, question)
        if unknown is not None:
            # The coverage refusal comes first: a request
            # about an untracked district is refused for
            # coverage, not for a missing head artefact.
            tracked = ", ".join(
                d["name"] for d in self.store.list_districts())
            raise ValueError(
                f"district coverage: {unknown} is not one of the "
                f"tracked districts ({tracked}) — a scenario "
                "cannot fork an estimate the system does not hold")
        base = self._scenario_base(kind0, scope0)
        if self.settings.model_profile == "offline":
            kind, scope, records, gaps, parse = \
                scenario_engine.parse_scenario_grammar(
                    self.store, question, base)
        else:
            kind, scope, records, gaps, parse = \
                scenario_engine.parse_scenario_model(
                    self.store, self.model, question, base)
        base = self._scenario_base(kind, scope)
        return self._store_fork(kind, scope, base, records, gaps, parse,
                                asked_by, name)

    def _store_fork(self, kind, scope, base, records, gaps, parse,
                    created_by, name) -> dict:
        if kind == "demand_estimate":
            result, reconciliation = scenario_engine.compute_demand_fork(
                self.store, base, records)
        else:
            result, reconciliation = \
                scenario_engine.compute_projection_fork(
                    self.store, base, records)
        fork = scenario_engine.build_fork(
            kind, scope, base, records, gaps, parse, created_by, name,
            result, reconciliation)
        existing = self.store.get_scenario_fork(fork.fork_id)
        if existing is not None:
            return existing
        self.store.insert_scenario_fork(fork.model_dump())
        return fork.model_dump()

    def get_scenario(self, fork_id) -> dict | None:
        return self.store.get_scenario_fork(fork_id)

    def list_scenarios(self, base_artefact_id=None) -> list[dict]:
        return self.store.list_scenario_forks(base_artefact_id=base_artefact_id)

    def verify_scenario(self, fork_id) -> dict:
        fork = self.store.get_scenario_fork(fork_id)
        if fork is None:
            raise ValueError(f"no such scenario fork: {fork_id}")
        problems = scenario_engine.verify_fork(self.store, fork)
        return {"fork_id": fork_id, "verified": not problems,
                "problems": problems}

    def build_planning_options(self, base_artefact_id: str,
                               fork_ids: list[str], created_by: str,
                               name: str | None = None) -> dict:
        """Compare a base artefact and its forks side by
        side. Every fork must fork THIS base; the comparison
        is struck at the base's date and ranked only by the
        pack's stated criteria."""
        forks = []
        for fork_id in fork_ids:
            fork = self.store.get_scenario_fork(fork_id)
            if fork is None:
                raise ValueError(f"no such scenario fork: {fork_id}")
            if fork["base_artefact_id"] != base_artefact_id:
                raise ValueError(
                    f"fork {fork_id} forks {fork['base_artefact_id']}, "
                    f"not {base_artefact_id} — a comparison holds "
                    "forks of one base only")
            forks.append(fork)
        if not forks:
            raise ValueError(
                "a comparison needs at least one fork — the base "
                "alone is the head artefact, not an option set")
        kind = forks[0]["kind"]
        if any(f["kind"] != kind for f in forks):
            raise ValueError("all forks in one comparison share one kind")
        if kind == "demand_estimate":
            base = self.store.get_estimate(base_artefact_id)
            if base is None:
                raise ValueError(
                    f"no such base estimate: {base_artefact_id}")
            base = {**base, "contributions":
                    self.store.estimate_contributions(base_artefact_id)}
        else:
            base = self.store.get_projection(base_artefact_id)
            if base is None:
                raise ValueError(
                    f"no such base projection: {base_artefact_id}")
            # The comparison's gap reading stands on the
            # season outlook's demand rollup — strike it
            # through the ordinary surface when none is on
            # record yet.
            if self.get_outlook(base["crop_year"], base["season"]) is None:
                self.demand_outlook(base["crop_year"], base["season"],
                                    base["as_of"])
        scope = forks[0]["scope"]
        options = scenario_engine.compute_options(
            self.store, kind, scope, base, forks, created_by,
            base["as_of"], name)
        existing = self.store.get_planning_options(options.options_id)
        if existing is not None:
            return existing
        self.store.insert_planning_options(options.model_dump())
        return options.model_dump()

    def get_planning_options(self, options_id) -> dict | None:
        return self.store.get_planning_options(options_id)

    def list_planning_options(self, base_artefact_id=None) -> list[dict]:
        return self.store.list_planning_options(base_artefact_id)

    def verify_planning_options(self, options_id) -> dict:
        options = self.store.get_planning_options(options_id)
        if options is None:
            raise ValueError(f"no such planning options: {options_id}")
        problems = scenario_engine.verify_options(self.store, options)
        return {"options_id": options_id, "verified": not problems,
                "problems": problems}

    def adopt_option(self, options_id: str, fork_id: str | None,
                     adopted_by: str, as_of: str,
                     note: str | None = None) -> dict:
        """Adopt one row of a comparison — the base view
        (fork_id None) or one of its forks — as the option
        the plan follows. The act is insert-only and
        supersedes the chain's previous head by link; it
        edits no artefact. An unnamed adoption is refused:
        a plan follows a fork because a named planner said
        so, or it does not follow it."""
        if not adopted_by or not adopted_by.strip():
            raise ValueError(
                "an adoption names its planner — an unnamed "
                "adoption is refused")
        options = self.store.get_planning_options(options_id)
        if options is None:
            raise ValueError(f"no such planning options: {options_id}")
        if fork_id is not None and fork_id not in options["fork_ids"]:
            raise ValueError(
                f"fork {fork_id} is not a row of {options_id} — only "
                "a compared option can be adopted")
        chain = self.store.list_planning_adoptions(options_id)
        head = scenario_engine.head_adoption(chain)
        adoption = scenario_engine.build_adoption(
            options, fork_id, adopted_by, note, as_of,
            head["adoption_id"] if head else None)
        existing = self.store.get_planning_adoption(adoption.adoption_id)
        if existing is not None:
            return existing
        self.store.insert_planning_adoption(adoption.model_dump())
        return adoption.model_dump()

    def current_adoption(self, options_id) -> dict | None:
        return scenario_engine.head_adoption(
            self.store.list_planning_adoptions(options_id))

    def list_adoptions(self, options_id) -> list[dict]:
        return self.store.list_planning_adoptions(options_id)

    def verify_adoption(self, adoption_id) -> dict:
        adoption = self.store.get_planning_adoption(adoption_id)
        if adoption is None:
            raise ValueError(f"no such planning adoption: {adoption_id}")
        problems = scenario_engine.verify_adoption(self.store, adoption)
        return {"adoption_id": adoption_id, "verified": not problems,
                "problems": problems}

    # -- Round 10: weekly brief, report packs, publication -------
    # The brief is assembled from artefacts, verified figure by
    # figure, and only then stored; a refusal is recorded as
    # its own artefact. Publication is a named act over an
    # exact artefact version — the brief itself carries no
    # published field, so the read surface folds the acts.

    def _record_brief_refusal(self, week_ending, as_of, assembled_by,
                              problems) -> dict:
        refusal = brief_engine.build_refusal(
            week_ending, as_of, assembled_by, problems)
        existing = self.store.get_brief_refusal(refusal.refusal_id)
        if existing is not None:
            return existing
        self.store.insert_brief_refusal(refusal.model_dump())
        log.info("brief refusal recorded: %s", refusal.refusal_id)
        return self.store.get_brief_refusal(refusal.refusal_id)

    def weekly_brief(self, week_ending, assembled_by, as_of=None,
                     port=None) -> dict:
        """Assemble the brief for the week ending on a date.

        The candidate is collected from the heads of record,
        its summary drafted through the model port, and every
        figure re-performed from its pinned artefact before
        anything is stored. One wrong figure refuses the
        brief wholesale: a refusal artefact is recorded with
        its reasons and BriefRefused is raised. A clean
        assembly for a week with a recorded refusal
        supersedes the refusal by link. Compute-or-return: the
        same week over the same heads returns the stored
        brief."""
        if not assembled_by or not assembled_by.strip():
            raise ValueError(
                "a brief names who assembled it — an unnamed "
                "assembly is refused")
        as_of = as_of or week_ending
        model = port or self.model
        try:
            candidate = brief_engine.assemble_candidate(
                self, week_ending, as_of, assembled_by, model)
        except brief_engine.BriefRefused as refused:
            refusal = self._record_brief_refusal(
                week_ending, as_of, assembled_by, refused.problems)
            raise brief_engine.BriefRefused(
                refused.problems, refusal["refusal_id"]) from refused
        problems = brief_engine.verify_brief(
            self.store, candidate.model_dump())
        if problems:
            refusal = self._record_brief_refusal(
                week_ending, as_of, assembled_by, problems)
            raise brief_engine.BriefRefused(
                problems, refusal["refusal_id"])
        existing = self.store.get_weekly_brief(candidate.brief_id)
        if existing is not None:
            return self._brief_with_publication(existing)
        self.store.insert_weekly_brief(candidate.model_dump())
        log.info("weekly brief stored: %s", candidate.brief_id)
        return self._brief_with_publication(
            self.store.get_weekly_brief(candidate.brief_id))

    def _brief_with_publication(self, brief: dict) -> dict:
        brief = dict(brief)
        brief["publication"] = brief_engine.publication_state(
            self.store.list_publication_acts(),
            brief_pack.KIND_BRIEF, brief["brief_id"])
        return brief

    def get_brief(self, brief_id) -> dict | None:
        row = self.store.get_weekly_brief(brief_id)
        return self._brief_with_publication(row) if row else None

    def list_briefs(self, week_ending=None) -> list[dict]:
        return [
            self._brief_with_publication(b)
            for b in self.store.list_weekly_briefs(week_ending)
        ]

    def verify_brief(self, brief_id) -> dict:
        brief = self.store.get_weekly_brief(brief_id)
        if brief is None:
            raise ValueError(f"no such weekly brief: {brief_id}")
        problems = brief_engine.verify_brief(self.store, brief)
        return {"brief_id": brief_id, "verified": not problems,
                "problems": problems}

    def brief_html(self, brief_id) -> str | None:
        brief = self.get_brief(brief_id)
        if brief is None:
            return None
        return brief_engine.render_brief_html(brief, brief["publication"])

    def list_brief_refusals(self, week_ending=None) -> list[dict]:
        return self.store.list_brief_refusals(week_ending)

    # -- report packs ---------------------------------------------

    def _collect_pack_tables(self, pack_kind, pack_key, as_of):
        if pack_kind == brief_pack.PACK_PRODUCT:
            return brief_engine.collect_product_pack(
                self, pack_key, as_of)
        if pack_kind == brief_pack.PACK_REGION:
            return brief_engine.collect_region_pack(
                self, pack_key, as_of)
        raise ValueError(
            f"pack kind {pack_kind!r} is not a pack kind — the "
            f"brief pack names {brief_pack.PACK_KINDS}")

    def export_pack(self, pack_kind, pack_key, exported_by,
                    as_of) -> dict:
        """Export one product's or one region's figures as a
        pack artefact: tables collected from the artefacts of
        record, a provenance appendix, and a checksum
        manifest over the rendered files. Compute-or-return:
        the same pack content returns the stored artefact."""
        if not exported_by or not exported_by.strip():
            raise ValueError(
                "a pack names who exported it — an unnamed "
                "export is refused")
        if pack_kind == brief_pack.PACK_PRODUCT \
                and pack_key not in PRODUCTS:
            raise ValueError(
                f"product {pack_key!r} is not tracked — the "
                f"tracked products are {PRODUCTS}")
        tables, appendix = self._collect_pack_tables(
            pack_kind, pack_key, as_of)
        artefact = brief_engine.build_pack(
            pack_kind, pack_key, as_of, exported_by, tables, appendix)
        existing = self.store.get_export_pack(artefact.pack_id)
        if existing is not None:
            return existing
        self.store.insert_export_pack(artefact.model_dump())
        log.info("export pack stored: %s", artefact.pack_id)
        return self.store.get_export_pack(artefact.pack_id)

    def get_pack(self, pack_id) -> dict | None:
        return self.store.get_export_pack(pack_id)

    def list_packs(self, pack_kind=None, pack_key=None) -> list[dict]:
        return self.store.list_export_packs(pack_kind, pack_key)

    def verify_pack(self, pack_id) -> dict:
        """Re-perform a stored pack: files against manifest,
        tables against a fresh collection from the store at
        the pack's as-of, identity against content."""
        pack_row = self.store.get_export_pack(pack_id)
        if pack_row is None:
            raise ValueError(f"no such export pack: {pack_id}")
        fresh_tables, _ = self._collect_pack_tables(
            pack_row["pack_kind"], pack_row["pack_key"],
            pack_row["as_of"])
        problems = brief_engine.verify_pack(
            self.store, pack_row, fresh_tables)
        return {"pack_id": pack_id, "verified": not problems,
                "problems": problems}

    def pack_files(self, pack_id) -> dict[str, str]:
        """The pack's rendered files as text — the bytes the
        manifest checksums were taken over."""
        pack_row = self.store.get_export_pack(pack_id)
        if pack_row is None:
            raise ValueError(f"no such export pack: {pack_id}")
        return {
            name: data.decode()
            for name, data in
            brief_engine.render_pack_files(pack_row).items()
        }

    def write_pack(self, pack_id, out_dir) -> dict:
        """Write the pack's files into a directory; returns
        the file names written."""
        from pathlib import Path

        pack_row = self.store.get_export_pack(pack_id)
        if pack_row is None:
            raise ValueError(f"no such export pack: {pack_id}")
        target = Path(out_dir)
        target.mkdir(parents=True, exist_ok=True)
        written = {}
        for name, data in brief_engine.render_pack_files(
                pack_row).items():
            (target / name).write_bytes(data)
            written[name] = str(target / name)
        return written

    def verify_pack_dir(self, pack_id, in_dir) -> dict:
        """Verify files as they sit in a directory against
        the pack's manifest and the store: a tampered export
        file is detected and named."""
        from pathlib import Path

        pack_row = self.store.get_export_pack(pack_id)
        if pack_row is None:
            raise ValueError(f"no such export pack: {pack_id}")
        source = Path(in_dir)
        files = {}
        if source.is_dir():
            for path in sorted(source.iterdir()):
                if path.is_file():
                    files[path.name] = path.read_bytes()
        problems = brief_engine.verify_pack_files(pack_row, files)
        fresh_tables, _ = self._collect_pack_tables(
            pack_row["pack_kind"], pack_row["pack_key"],
            pack_row["as_of"])
        if json.dumps(fresh_tables, sort_keys=True) != \
                json.dumps(pack_row["tables"], sort_keys=True):
            problems.append(
                "the pack's tables do not re-perform from the "
                "store at its as-of")
        return {"pack_id": pack_id, "verified": not problems,
                "problems": problems}

    # -- publication ------------------------------------------------

    def publish_artefact(self, artefact_kind, artefact_id,
                         published_by, published_at,
                         note=None) -> dict:
        """Publish one artefact version by a named act. The
        target must exist and must verify under its own
        family's verifier at publication time — an unverified
        artefact cannot be published. The act binds the
        artefact's fingerprint and supersedes the family's
        current head act by link; it edits no artefact."""
        if not published_by or not published_by.strip():
            raise ValueError(
                "a publication act names its publisher — an "
                "unnamed publication is refused")
        if not published_at:
            raise ValueError("a publication act names its date")
        if artefact_kind == brief_pack.KIND_BRIEF:
            target = self.store.get_weekly_brief(artefact_id)
            problems = (
                brief_engine.verify_brief(self.store, target)
                if target is not None
                else [f"no such weekly brief: {artefact_id}"])
        elif artefact_kind == brief_pack.KIND_OUTLOOK:
            target = self.store.get_outlook(artefact_id)
            problems = (
                demand_engine.verify_outlook(self.store, target)
                if target is not None
                else [f"no such season outlook: {artefact_id}"])
        else:
            raise ValueError(
                f"artefact kind {artefact_kind!r} cannot be "
                f"published — the brief pack names "
                f"{brief_pack.PUBLICATION_KINDS}")
        if problems:
            raise ValueError(
                f"{artefact_kind} {artefact_id} cannot be "
                f"published: " + "; ".join(problems))
        family = brief_engine.family_key_for(artefact_kind, target)
        head = brief_engine.head_act(
            self.store.list_publication_acts(family_key=family))
        act = brief_engine.build_publication_act(
            artefact_kind, target, published_by.strip(),
            published_at, note,
            head["act_id"] if head else None)
        existing = self.store.get_publication_act(act.act_id)
        if existing is not None:
            return existing
        self.store.insert_publication_act(act.model_dump())
        log.info("publication act recorded: %s", act.act_id)
        return self.store.get_publication_act(act.act_id)

    def publication_state(self, artefact_kind, artefact_id) -> dict:
        return brief_engine.publication_state(
            self.store.list_publication_acts(),
            artefact_kind, artefact_id)

    def decision_log(self) -> list[dict]:
        """The publication decision log, re-derived from the
        acts alone: who published what, when, superseding
        which version."""
        return brief_engine.derive_decision_log(
            self.store.list_publication_acts())

    def verify_decision_log(self) -> dict:
        acts = self.store.list_publication_acts()
        problems = brief_engine.verify_decision_log(self.store, acts)
        return {"acts": len(acts), "verified": not problems,
                "problems": problems}

    # -- the production data plane (R11) ----------------------

    def ingest_sources(self) -> list[dict]:
        """The source registry, as data: every admissible
        feed with its fact class, cadence, owner and
        freshness rule."""
        return [
            {"source_id": source_id, **entry}
            for source_id, entry in ingest_pack.SOURCES.items()
        ]

    def load_connector_batch(self, source_id, rows, loaded_by,
                             load_date) -> dict:
        """Land one connector batch from a registered
        source: valid rows insert-only, bad rows quarantine
        with named reasons, provenance-less rows are refused
        at the port, and a replay lands nothing twice."""
        batch = ingest_engine.load_batch(
            self.store, source_id, rows, loaded_by, load_date)
        log.info(
            "connector batch %s: %s received, %s inserted, "
            "%s duplicates, %s quarantined, %s refused",
            batch["batch_id"], batch["received"], batch["inserted"],
            batch["duplicates"], batch["quarantined"], batch["refused"])
        return batch

    def get_ingest_batch(self, batch_id) -> dict | None:
        return self.store.get_ingest_batch(batch_id)

    def list_ingest_batches(self, source_id=None, fact_class=None) -> list[dict]:
        return self.store.list_ingest_batches(source_id, fact_class)

    def verify_ingest_batch(self, batch_id) -> dict:
        return ingest_engine.verify_batch(self.store, batch_id)

    def list_quarantine(self, batch_id=None, reason=None,
                        fact_class=None) -> list[dict]:
        return self.store.list_quarantine_records(
            batch_id=batch_id, reason=reason, fact_class=fact_class)

    def submit_correction(self, fact_class, row, corrects,
                          corrected_by) -> dict:
        correction = ingest_engine.submit_correction(
            self.store, fact_class, row, corrects, corrected_by)
        log.info("correction recorded: %s", correction["correction_id"])
        return correction

    def list_corrections(self, fact_class=None, natural_key=None) -> list[dict]:
        return self.store.list_fact_corrections(fact_class, natural_key)

    def effective_fact(self, fact_class, key) -> dict | None:
        if fact_class not in ingest_pack.FACT_CLASSES:
            raise ValueError(f"unknown fact class: {fact_class}")
        return ingest_engine.effective_row(self.store, fact_class, key)

    def verify_correction_chain(self, fact_class, key) -> dict:
        if fact_class not in ingest_pack.FACT_CLASSES:
            raise ValueError(f"unknown fact class: {fact_class}")
        return ingest_engine.verify_correction_chain(
            self.store, fact_class, key)

    def actuals_report(self, crop_year, season) -> dict:
        """The season-close actuals for one season, joined
        to struck estimates by natural key — unmatched rows
        reported, never dropped."""
        return ingest_engine.actuals_report(self.store, crop_year, season)

    def ready(self) -> bool:
        # Season actuals (R11) are an import class that is
        # legitimately empty until a season closes, so they
        # are not part of the dataset-loaded check.
        counts = self.store.fact_counts()
        counts.pop("season_actuals", None)
        return self.store.get_manifest() is not None and all(
            n > 0 for n in counts.values()
        )
