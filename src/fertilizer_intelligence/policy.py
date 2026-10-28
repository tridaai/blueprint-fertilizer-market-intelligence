"""The policy & subsidy event registry (R5): registrations and
impact notes.

Two artefacts, both insert-only and superseding by link like
the rest of the store:

- A **registry event** promotes a policy record to a
  first-class artefact under the policy rule pack
  (:mod:`.policy_rules`): a class from the pack vocabulary, a
  structured stated effect (direction + driver + mechanism +
  the pack's linkage to the engine surface the effect would
  move), an effective window in whole months, product/district
  scope as recorded, and provenance — the source label and the
  date the event was recorded. The dataset's recorded events
  are registered from their facts by a deterministic mapping
  (kind -> class, date -> window by the pack's stated rule), so
  the same fact always registers the same artefact. Events
  registered at the desk state their own window and effect,
  validated against the pack.

- An **impact note** states, for one current registry event,
  exactly which stored artefacts fall inside its window and
  scope: the head demand estimates per district x season cell,
  the price series points (product and feedstock alike), and
  the head supply positions. The note is computed by query
  over stored artefacts — it lists artefact ids, never prose
  about impact. An event whose scope matches nothing stored
  earns a note with status `no_observed_scope` and empty
  lists: the absence is stated, not hidden.

A **hypothetical** event — a proposed policy — is registered
with the flag set. It is listed separately, it never earns an
impact note (asking for one is refused), and it never marks
the watch board. Registrations are insert-only, so the flag
cannot be flipped on a stored artefact: when a proposal
becomes real, the desk registers it again under the same
event id and the new registration supersedes the hypothetical
by link, which stays exactly as recorded.
"""

from __future__ import annotations

import hashlib
import json
import re

from pydantic import BaseModel

from . import demand_rules
from . import policy_rules as pack
from .generator import CROP_YEARS, FEEDSTOCKS, PRODUCTS, SEASONS

SCOPE_ITEMS = sorted(PRODUCTS + FEEDSTOCKS)
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class StatedEffect(BaseModel):
    direction: str  # up / down / none (pack vocabulary)
    driver: str  # demand_rate / price / supply
    mechanism: str  # the effect in words, as recorded
    linkage: dict  # the engine surface the effect would move (pack)


class RegisteredPolicyEvent(BaseModel):
    registry_id: str
    event_id: str
    fact_event_id: str | None = None
    event_class: str
    fact_kind: str | None = None
    title: str
    detail: str
    effective_from_month: str
    effective_to_month: str
    products: list[str]
    districts: list[str]  # empty = market-wide, as recorded
    stated_effect: StatedEffect
    hypothetical: bool = False
    source: str
    recorded_on: str  # ISO date the event was recorded (provenance)
    registered_by: str  # "dataset" for the fact pass; a named actor at the desk
    rules_version: str
    fact_fingerprint: str
    as_of: str
    supersedes: str | None = None


class PolicyImpactNote(BaseModel):
    note_id: str
    registry_id: str
    event_id: str
    status: str  # computed / no_observed_scope
    demand_estimate_ids: list[str]
    demand_cells: list[dict]  # district_id, product, crop_year, season, estimate_id
    price_series: list[dict]  # series_kind, item, months, point_count
    position_ids: list[str]
    positions: list[dict]  # product, month, position_id
    rules_version: str
    fact_fingerprint: str
    as_of: str
    supersedes: str | None = None


def _fingerprint(material) -> str:
    blob = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def head_of(rows: list[dict], id_key: str) -> dict | None:
    superseded = {r["supersedes"] for r in rows if r.get("supersedes")}
    heads = [r for r in rows if r[id_key] not in superseded]
    return heads[0] if heads else None


def heads_by_event(rows: list[dict]) -> dict[str, dict]:
    """The current registration per event id: the head of each
    supersedes chain."""
    out: dict[str, dict] = {}
    by_event: dict[str, list[dict]] = {}
    for row in rows:
        by_event.setdefault(row["event_id"], []).append(row)
    for event_id, versions in by_event.items():
        head = head_of(versions, "registry_id")
        if head is not None:
            out[event_id] = head
    return out


# -- the window rule ---------------------------------------------------------


def effective_window(event_date: str) -> tuple[str, str]:
    """The pack's stated derivation: the window opens at the
    event's month and closes at the end of the season price
    window containing it (the season opening at that month,
    when a month opens one); a month before every tracked
    season closes at the end of the next window to open; a
    month after every tracked season takes a single-month
    window — it speaks to no tracked season."""
    month = event_date[:7]
    windows = [
        demand_rules.season_price_window(crop_year, season)
        for crop_year in CROP_YEARS
        for season in SEASONS
    ]
    containing = [w for w in windows if w[0] <= month <= w[-1]]
    if containing:
        opening = [w for w in containing if w[0] == month]
        chosen = opening[0] if opening else containing[0]
        return month, chosen[-1]
    later = [w for w in windows if w[0] > month]
    if later:
        return month, later[0][-1]
    return month, month


def overlapping_seasons(event: dict) -> list[tuple[str, str]]:
    """The (crop_year, season) cells whose price window overlaps
    the event's effective window — the demand cells an impact
    note can name."""
    out = []
    for crop_year in CROP_YEARS:
        for season in SEASONS:
            window = demand_rules.season_price_window(crop_year, season)
            if window[0] <= event["effective_to_month"] \
                    and window[-1] >= event["effective_from_month"]:
                out.append((crop_year, season))
    return out


# -- registration --------------------------------------------------------------


def _registration_fingerprint(fields: dict) -> str:
    return _fingerprint({
        "registration": [
            fields["event_id"], fields["fact_event_id"],
            fields["event_class"], fields["fact_kind"], fields["title"],
            fields["detail"], fields["effective_from_month"],
            fields["effective_to_month"], fields["products"],
            fields["districts"],
        ],
        "effect": [
            fields["stated_effect"]["direction"],
            fields["stated_effect"]["driver"],
            fields["stated_effect"]["mechanism"],
            fields["stated_effect"]["linkage"],
        ],
        "hypothetical": fields["hypothetical"],
        "provenance": [
            fields["source"], fields["recorded_on"], fields["registered_by"],
        ],
        "rules": pack.RULES_VERSION,
    })


def _make_event(fields: dict, as_of: str) -> RegisteredPolicyEvent:
    fingerprint = _registration_fingerprint(fields)
    return RegisteredPolicyEvent(
        registry_id=f"POLREG-{fields['event_id']}-{fingerprint[:10]}",
        fact_fingerprint=fingerprint,
        rules_version=pack.RULES_VERSION,
        as_of=as_of,
        **fields,
    )


def registration_from_fact(fact: dict, as_of: str) -> RegisteredPolicyEvent:
    """Register one recorded policy fact. The mapping is the
    pack's alone: kind -> class, the pack's planted direction
    for the event, the window derived from the fact's date, the
    mechanism carried verbatim from the fact's recorded
    expected impact, the linkage from the class."""
    event_id = fact["event_id"]
    if fact["kind"] not in pack.CLASS_BY_FACT_KIND:
        raise ValueError(
            f"recorded policy kind {fact['kind']!r} has no registry class "
            f"in pack {pack.RULES_VERSION}"
        )
    if event_id not in pack.PLANTED_DIRECTIONS:
        raise ValueError(
            f"recorded policy event {event_id} has no stated direction "
            f"in pack {pack.RULES_VERSION}"
        )
    event_class = pack.CLASS_BY_FACT_KIND[fact["kind"]]
    from_month, to_month = effective_window(fact["date"])
    fields = {
        "event_id": event_id,
        "fact_event_id": event_id,
        "event_class": event_class,
        "fact_kind": fact["kind"],
        "title": fact["title"],
        "detail": fact["detail"],
        "effective_from_month": from_month,
        "effective_to_month": to_month,
        "products": list(fact["impacted_products"]),
        "districts": [],
        "stated_effect": {
            "direction": pack.PLANTED_DIRECTIONS[event_id],
            "driver": pack.class_driver(event_class),
            "mechanism": fact["expected_impact"],
            "linkage": pack.class_linkage(event_class),
        },
        "hypothetical": False,
        "source": fact["source"],
        "recorded_on": fact["as_of"],
        "registered_by": "dataset",
    }
    return _make_event(fields, as_of)


def build_registration(spec: dict, district_ids: set[str], as_of: str) -> RegisteredPolicyEvent:
    """Build a desk registration from a stated spec, validated
    against the pack. The registrar states the window and the
    effect; the pack supplies (and constrains) the class, the
    driver and the linkage."""
    event_class = spec.get("event_class")
    if event_class not in pack.EVENT_CLASSES:
        raise ValueError(
            f"unknown policy event class: {event_class!r} (pack "
            f"{pack.RULES_VERSION} knows: {', '.join(sorted(pack.EVENT_CLASSES))})"
        )
    direction = spec.get("direction")
    if direction not in pack.DIRECTIONS:
        raise ValueError(
            f"direction must be one of {sorted(pack.DIRECTIONS)}: got {direction!r}"
        )
    driver = spec.get("driver") or pack.class_driver(event_class)
    if driver != pack.class_driver(event_class):
        raise ValueError(
            f"driver {driver!r} disagrees with the stated driver of class "
            f"{event_class} ({pack.class_driver(event_class)}): the class is "
            "the claim about what kind of lever the policy is"
        )
    products = list(spec.get("products") or [])
    if not products:
        raise ValueError("a policy event must name at least one product in scope")
    unknown = [p for p in products if p not in SCOPE_ITEMS]
    if unknown:
        raise ValueError(f"unknown scope products: {unknown}")
    districts = list(spec.get("districts") or [])
    unknown_districts = [d for d in districts if d not in district_ids]
    if unknown_districts:
        raise ValueError(f"unknown districts in scope: {unknown_districts}")
    from_month, to_month = spec.get("effective_from_month"), spec.get("effective_to_month")
    for label, value in (("effective_from_month", from_month), ("effective_to_month", to_month)):
        if not value or not _MONTH_RE.match(value):
            raise ValueError(f"{label} must be a YYYY-MM month: got {value!r}")
    if from_month > to_month:
        raise ValueError(
            f"effective window {from_month}..{to_month} closes before it opens"
        )
    for label in ("event_id", "title", "detail", "mechanism", "source", "registered_by"):
        if not spec.get(label) or not str(spec[label]).strip():
            raise ValueError(f"a policy registration needs a stated {label}")
    fields = {
        "event_id": spec["event_id"],
        "fact_event_id": None,
        "event_class": event_class,
        "fact_kind": None,
        "title": spec["title"],
        "detail": spec["detail"],
        "effective_from_month": from_month,
        "effective_to_month": to_month,
        "products": products,
        "districts": districts,
        "stated_effect": {
            "direction": direction,
            "driver": driver,
            "mechanism": spec["mechanism"],
            "linkage": pack.class_linkage(event_class),
        },
        "hypothetical": bool(spec.get("hypothetical", False)),
        "source": spec["source"],
        "recorded_on": spec.get("recorded_on") or as_of,
        "registered_by": spec["registered_by"],
    }
    return _make_event(fields, as_of)


def verify_policy_event(store, event: dict) -> list[str]:
    """Re-perform a stored registration. A fact-backed event
    must equal the pack's registration of its fact, field for
    field; a desk event must satisfy the pack (class, driver,
    linkage, direction, window, scope vocabulary) — and both
    must carry the fingerprint their content hashes to."""
    problems: list[str] = []
    if event["rules_version"] != pack.RULES_VERSION:
        return [f"registration names unknown policy pack {event['rules_version']}"]
    fields = {
        "event_id": event["event_id"],
        "fact_event_id": event["fact_event_id"],
        "event_class": event["event_class"],
        "fact_kind": event["fact_kind"],
        "title": event["title"],
        "detail": event["detail"],
        "effective_from_month": event["effective_from_month"],
        "effective_to_month": event["effective_to_month"],
        "products": event["products"],
        "districts": event["districts"],
        "stated_effect": event["stated_effect"],
        "hypothetical": event["hypothetical"],
        "source": event["source"],
        "recorded_on": event["recorded_on"],
        "registered_by": event["registered_by"],
    }
    if _registration_fingerprint(fields) != event["fact_fingerprint"]:
        problems.append("registration fingerprint does not match its content")
    if event["registry_id"] != f"POLREG-{event['event_id']}-{event['fact_fingerprint'][:10]}":
        problems.append("registry id does not match its fingerprint")

    if event["fact_event_id"] is not None:
        fact = next(
            (f for f in store.policy_events()
             if f["event_id"] == event["fact_event_id"]),
            None,
        )
        if fact is None:
            problems.append(
                f"the recorded fact {event['fact_event_id']} is not in the store"
            )
        else:
            fresh = registration_from_fact(fact, event["as_of"])
            if fresh.registry_id != event["registry_id"]:
                problems.append(
                    "registration does not re-perform from its recorded fact"
                )
    else:
        if event["event_class"] not in pack.EVENT_CLASSES:
            problems.append(f"unknown event class {event['event_class']!r}")
        else:
            effect = event["stated_effect"]
            if effect["driver"] != pack.class_driver(event["event_class"]):
                problems.append("stated driver disagrees with the class's driver")
            if effect["linkage"] != pack.class_linkage(event["event_class"]):
                problems.append("stated linkage is not the class's pack linkage")
            if effect["direction"] not in pack.DIRECTIONS:
                problems.append(f"unknown direction {effect['direction']!r}")
        if not _MONTH_RE.match(event["effective_from_month"]) \
                or not _MONTH_RE.match(event["effective_to_month"]) \
                or event["effective_from_month"] > event["effective_to_month"]:
            problems.append("the effective window is not a sane month range")
        unknown = [p for p in event["products"] if p not in SCOPE_ITEMS]
        if unknown:
            problems.append(f"scope names unknown products: {unknown}")
        known_districts = {d["district_id"] for d in store.list_districts()}
        unknown = [d for d in event["districts"] if d not in known_districts]
        if unknown:
            problems.append(f"scope names unknown districts: {unknown}")
    return problems


# -- impact notes ----------------------------------------------------------------


def scope_members(store, event: dict) -> dict:
    """The scope query, stated once and used by both the note
    computation and its verifier: the head demand estimates in
    the event's product scope (and district scope, when the
    event was recorded with one) whose season window overlaps
    the event window; the price points for scoped items in the
    window, grouped by series; the head supply positions for
    scoped products in the window."""
    products = set(event["products"])
    districts = set(event["districts"])
    from_month, to_month = event["effective_from_month"], event["effective_to_month"]

    cells: dict[tuple, list[dict]] = {}
    for row in store.list_estimates():
        key = (row["district_id"], row["product"], row["crop_year"], row["season"])
        cells.setdefault(key, []).append(row)
    demand_cells = []
    for (district_id, product, crop_year, season), versions in cells.items():
        if product not in products:
            continue
        if districts and district_id not in districts:
            continue
        window = demand_rules.season_price_window(crop_year, season)
        if window[0] > to_month or window[-1] < from_month:
            continue
        head = head_of(versions, "estimate_id")
        if head is not None:
            demand_cells.append({
                "district_id": district_id, "product": product,
                "crop_year": crop_year, "season": season,
                "estimate_id": head["estimate_id"],
            })
    demand_cells.sort(key=lambda c: c["estimate_id"])

    series: dict[tuple[str, str], list[str]] = {}
    for point in store.price_points():
        if point["item"] in products and from_month <= point["month"] <= to_month:
            series.setdefault((point["series_kind"], point["item"]), []).append(
                point["month"]
            )
    price_series = [
        {
            "series_kind": kind, "item": item,
            "months": sorted(months), "point_count": len(months),
        }
        for (kind, item), months in sorted(series.items())
    ]

    position_rows = []
    for product in sorted(products):
        by_month: dict[str, list[dict]] = {}
        for row in store.list_positions(product):
            by_month.setdefault(row["month"], []).append(row)
        for month, versions in by_month.items():
            if from_month <= month <= to_month:
                head = head_of(versions, "position_id")
                if head is not None:
                    position_rows.append({
                        "product": product, "month": month,
                        "position_id": head["position_id"],
                    })
    position_rows.sort(key=lambda r: r["position_id"])

    return {
        "demand_cells": demand_cells,
        "price_series": price_series,
        "positions": position_rows,
    }


def compute_impact_note(store, event: dict, as_of: str) -> PolicyImpactNote:
    """Compute (but do not store) the impact note for one
    registry event from the artefacts currently in the store.
    Hypotheticals never reach here — the service refuses them
    first; the guard below keeps that true for any caller."""
    if event["hypothetical"]:
        raise ValueError(
            f"policy event {event['event_id']} is hypothetical: a proposed "
            "policy earns no impact note — it is listed with its stated "
            "effect only"
        )
    members = scope_members(store, event)
    demand_ids = [c["estimate_id"] for c in members["demand_cells"]]
    position_ids = [p["position_id"] for p in members["positions"]]
    status = (
        "computed"
        if (demand_ids or members["price_series"] or position_ids)
        else "no_observed_scope"
    )
    fingerprint = _fingerprint({
        "note": [event["registry_id"], event["fact_fingerprint"]],
        "rules": pack.RULES_VERSION,
        "demand": demand_ids,
        "price_series": [
            [s["series_kind"], s["item"], s["months"]] for s in members["price_series"]
        ],
        "positions": position_ids,
    })
    return PolicyImpactNote(
        note_id=f"NOTE-{event['event_id']}-{fingerprint[:10]}",
        registry_id=event["registry_id"],
        event_id=event["event_id"],
        status=status,
        demand_estimate_ids=demand_ids,
        demand_cells=members["demand_cells"],
        price_series=members["price_series"],
        position_ids=position_ids,
        positions=members["positions"],
        rules_version=pack.RULES_VERSION,
        fact_fingerprint=fingerprint,
        as_of=as_of,
    )


def verify_impact_note(store, note: dict) -> list[str]:
    """Re-perform a stored impact note: the registry event must
    exist and be real (a note attached to a hypothetical is
    itself a violation), and the scope query over the store
    today must name exactly the members the note names."""
    problems: list[str] = []
    if note["rules_version"] != pack.RULES_VERSION:
        return [f"impact note names unknown policy pack {note['rules_version']}"]
    event = store.get_policy_registration(note["registry_id"])
    if event is None:
        return ["the note's registry event is not in the store"]
    if event["hypothetical"]:
        problems.append("an impact note exists for a hypothetical event")
    members = scope_members(store, event)
    if [c["estimate_id"] for c in members["demand_cells"]] != note["demand_estimate_ids"]:
        problems.append("demand members do not match the re-performed scope query")
    if members["demand_cells"] != note["demand_cells"]:
        problems.append("demand cells do not match the re-performed scope query")
    if members["price_series"] != note["price_series"]:
        problems.append("price series do not match the re-performed scope query")
    if [p["position_id"] for p in members["positions"]] != note["position_ids"]:
        problems.append("position members do not match the re-performed scope query")
    if members["positions"] != note["positions"]:
        problems.append("position rows do not match the re-performed scope query")
    expected_status = (
        "computed"
        if (note["demand_estimate_ids"] or note["price_series"] or note["position_ids"])
        else "no_observed_scope"
    )
    if note["status"] != expected_status:
        problems.append(
            f"note status {note['status']!r} does not match its members "
            f"({expected_status!r})"
        )
    fresh = compute_impact_note(store, event, note["as_of"])
    if fresh.note_id != note["note_id"]:
        problems.append("note id does not match the re-performed fingerprint")
    return problems


# -- watch-board markers -----------------------------------------------------------


def board_reference_month(store) -> str | None:
    """The pack's stated reference month for board markers: the
    latest month any tracked price series holds."""
    months = [p["month"] for p in store.price_points()]
    return max(months) if months else None


def board_markers(store, heads: list[dict]) -> dict[str, list[dict]]:
    """Policy markers by series item: for each current, real
    (non-hypothetical) registry event whose window covers the
    reference month, a marker on every series item it scopes
    to. Markers are typed data on the board row — they are not
    alerts and are never counted as alerts."""
    reference = board_reference_month(store)
    markers: dict[str, list[dict]] = {}
    if reference is None:
        return markers
    for event in heads:
        if event["hypothetical"]:
            continue
        if not (event["effective_from_month"] <= reference <= event["effective_to_month"]):
            continue
        marker = {
            "registry_id": event["registry_id"],
            "event_id": event["event_id"],
            "event_class": event["event_class"],
            "effective_from_month": event["effective_from_month"],
            "effective_to_month": event["effective_to_month"],
        }
        for item in event["products"]:
            markers.setdefault(item, []).append(marker)
    for item_markers in markers.values():
        item_markers.sort(key=lambda m: m["event_id"])
    return markers
