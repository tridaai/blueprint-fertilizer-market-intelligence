"""Weekly brief, report packs & the publication gate
(R10, roadmap F21-DR2 + F21-CA1).

The design brief's agent layer ends here: *the agent
drafts the brief; every figure is verified against
artefacts before the brief can be marked ready; a named
human publishes.* Management runs on the brief, so the
brief must be defensible — this round builds that
discipline as artefacts:

- A **weekly brief** is assembled for a stated week from
  the system's artefacts only: the head season outlook
  for the pack's season scope, the price-watch alerts
  fired on the latest tracked month, the head supply
  gaps (a head that moved against its predecessor is
  badged changed), the registered policy events whose
  window covers the week, the head share movements with
  Kaveri's headline share (stale exclusions badged and
  named), and the planning state where an option has
  been adopted. Every figure carries its lineage —
  artefact id and source as-of, the R8 discipline — and
  the drafted summary's every number is checked against
  the brief's own figure set, the R2 narrative
  discipline.
- The **figure verifier** is independent and the refusal
  is wholesale: before a brief is stored, every figure
  is re-performed from its pinned artefact and every
  pinned artefact is re-verified under its own family's
  verifier. One wrong figure — a tampered brief figure,
  a corrupted source artefact, a drafted number that is
  not in the figure set — refuses the whole brief. No
  partial brief is stored and no brief is corrected in
  place: the refusal is recorded as its own artefact,
  with its reasons, and a later clean assembly for the
  same week supersedes the refusal by link.
- A **report pack** exports one product's or one
  region's figures as files rendered from artefacts,
  with a provenance appendix and a checksum manifest: a
  byte flipped in an exported file is detected and
  named, and the pack's figures re-perform against the
  store's reads exactly.
- The **publication gate**: nothing renders as published
  without a named publication act binding the exact
  artefact version by fingerprint. Acts are insert-only
  and form one supersedes chain per family; the
  **decision log** — who published what, when,
  superseding which version — re-derives from the acts
  alone, and its verifier checks the chains are
  gapless and every act still binds the artefact it
  published. Publication state is a fold of acts, never
  a field on the artefact: a draft carries the draft
  mark on every surface.
"""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
from typing import Any

from pydantic import BaseModel, Field

from . import alert_rules as alert_pack
from . import brief_rules as pack
from . import demand as demand_engine
from . import movements as movement_engine
from . import policy as policy_engine
from . import scenario as scenario_engine
from . import share as share_engine
from . import supply as supply_engine
from .dashboard import _CSS, _esc, _fmt
from .generator import CROP_YEARS, PRODUCTS


def _fingerprint(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


class BriefRefused(RuntimeError):
    """A brief failed figure verification and was refused
    wholesale — the refusal artefact is on record and
    nothing of the brief is stored."""

    def __init__(self, problems: list[str], refusal_id: str | None = None):
        self.problems = problems
        self.refusal_id = refusal_id
        super().__init__("brief refused: " + "; ".join(problems))


# ---------------------------------------------------------------------------
# Artefacts
# ---------------------------------------------------------------------------


class WeeklyBrief(BaseModel):
    brief_id: str
    fingerprint: str
    week_start: str
    week_ending: str
    as_of: str
    season_scope: dict[str, Any]
    assembled_by: str
    sections: list[dict[str, Any]] = Field(default_factory=list)
    narrative: dict[str, Any] = Field(default_factory=dict)
    supersedes_refusal: str | None = None
    rules_version: str


class BriefRefusal(BaseModel):
    refusal_id: str
    fingerprint: str
    week_start: str
    week_ending: str
    as_of: str
    assembled_by: str
    problems: list[str] = Field(default_factory=list)
    rules_version: str


class ExportPack(BaseModel):
    pack_id: str
    fingerprint: str
    pack_kind: str  # product | region
    pack_key: str
    as_of: str
    exported_by: str
    tables: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    appendix: list[dict[str, Any]] = Field(default_factory=list)
    manifest: dict[str, str] = Field(default_factory=dict)
    rules_version: str


class PublicationAct(BaseModel):
    act_id: str
    fingerprint: str
    artefact_kind: str  # weekly_brief | season_outlook
    artefact_id: str
    artefact_fingerprint: str
    family_key: str
    published_by: str
    published_at: str
    note: str | None = None
    supersedes: str | None = None
    rules_version: str


# ---------------------------------------------------------------------------
# Figures: the R8 lineage shape
# ---------------------------------------------------------------------------


def _fig(label: str, value: Any, unit: str, artefact_id: str,
         source_as_of: str, badges: list[str] | None = None) -> dict:
    return {
        "label": label, "value": value, "unit": unit,
        "artefact_id": artefact_id, "source_as_of": source_as_of,
        "badges": list(badges or []),
    }


def _section(key: str, artefact_ids: list[str], figures: list[dict],
             notes: list[str]) -> dict:
    return {
        "key": key,
        "title": pack.SECTION_TITLES[key],
        "basis": pack.SECTION_BASIS[key],
        "artefact_ids": artefact_ids,
        "figures": figures,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Section figure builders: pure functions of the pinned artefacts.
# Assembly builds figures from the heads it struck; verification
# rebuilds them from the same artefacts fetched by id — the two
# paths share exactly this code, so a figure that does not
# re-perform is a defect on one side or the other.
# ---------------------------------------------------------------------------


def outlook_figures(outlook: dict) -> list[dict]:
    scope = f"{outlook['season']} {outlook['crop_year']}"
    figures = [
        _fig(f"Total estimated demand — {scope}",
             outlook["total_tonnes"], "t", outlook["outlook_id"],
             outlook["as_of"],
             ["partial"] if outlook["status"] == "partial" else []),
        _fig(f"Demand estimates in the outlook — {scope}",
             outlook["estimate_count"], "count", outlook["outlook_id"],
             outlook["as_of"]),
        _fig(f"Partial estimates — {scope}",
             outlook["partial_count"], "count", outlook["outlook_id"],
             outlook["as_of"]),
        _fig(f"Outlook status — {scope}",
             outlook["status"], "status", outlook["outlook_id"],
             outlook["as_of"]),
    ]
    for product in PRODUCTS:
        if product in outlook["product_rollups"]:
            figures.append(_fig(
                f"{product} demand — {scope}",
                outlook["product_rollups"][product], "t",
                outlook["outlook_id"], outlook["as_of"]))
    return figures


def alert_figure(alert: dict) -> dict:
    headline = next(
        (k for k in pack.ALERT_HEADLINE_KEYS if k in alert["figures"]),
        None)
    value = alert["figures"].get(headline) if headline else None
    return _fig(
        f"{alert['series_kind']} {alert['item']} — {alert['rule_id']} "
        f"({alert['period_month']})",
        value, "%", alert["alert_id"], alert["as_of"],
        [alert["band"]])


def gap_figures(gap: dict, predecessor: dict | None) -> list[dict]:
    scope = f"{gap['product']} {gap['season']} {gap['crop_year']}"
    badges: list[str] = []
    if predecessor is None:
        badges.append("first struck")
    elif (predecessor["band"] != gap["band"]
            or predecessor["gap_tonnes"] != gap["gap_tonnes"]):
        badges.append("changed")
    return [
        _fig(f"Supply gap — {scope}", gap["gap_tonnes"], "t",
             gap["gap_id"], gap["as_of"], badges),
        _fig(f"Gap band — {scope}", gap["band"], "band",
             gap["gap_id"], gap["as_of"], badges),
        _fig(f"Import programme cover — {scope}",
             gap["programme_cover_pct"], "%",
             gap["gap_id"], gap["as_of"], badges),
        _fig(f"Slipped tonnage — {scope}", gap["slipped_tonnes"],
             "t", gap["gap_id"], gap["as_of"], badges),
    ]


def policy_figure(event: dict, week_month: str) -> dict:
    badges = [event["event_class"]]
    if event["effective_from_month"] == week_month:
        badges.append("new this month")
    return _fig(
        f"{event['title']} ({event['event_id']})",
        event["stated_effect"]["direction"], "direction",
        event["registry_id"], event["as_of"], badges)


def share_figures(movement: dict, share: dict,
                  district_name: str) -> list[dict]:
    scope = f"{district_name} {movement['product']} {movement['season']}"
    mover = movement["biggest_mover"]
    # A movement compares full-season readings, whose basis
    # includes stale months and is labelled as such on the
    # artefact; the figure carries the dashboard's stale
    # badge for that basis — never presented as current.
    mover_badges = ["stale"] if "stale" in movement["basis"] else []
    figures = [
        _fig(f"Biggest mover ({mover['seller']}) — {scope}",
             mover["change_pp"], "pp", movement["movement_id"],
             movement["as_of"], mover_badges),
    ]
    headline = share.get("headline")
    badges = [share["status"]]
    if share.get("headline_note"):
        badges.append("stale observations excluded")
    figures.append(_fig(
        f"Kaveri headline share of the observed market — {scope}",
        headline["kaveri"]["share_of_observed_market_pct"]
        if headline else None,
        "%", share["share_id"], share["as_of"], badges))
    return figures


def planning_figure(options: dict, adoption: dict) -> dict:
    label = options.get("name") or options["options_id"]
    return _fig(
        f"Adopted plan — {label}",
        adoption["fork_id"] or "base view", "adoption",
        adoption["adoption_id"], adoption["as_of"],
        [options["kind"]])


# ---------------------------------------------------------------------------
# Collectors: strike or fetch the heads a section reports on.
# Each returns the section dict; the artefact ids it pins are
# the lineage the verifier re-performs from.
# ---------------------------------------------------------------------------


def _collect_demand(service, scope: dict, as_of: str) -> dict:
    outlook = service.demand_outlook(
        scope["crop_year"], scope["season"], as_of)
    return _section(
        pack.SECTION_DEMAND, [outlook["outlook_id"]],
        outlook_figures(outlook), [])


def _collect_prices(service, week_month: str, as_of: str) -> dict:
    service.run_price_watch(as_of)
    months = sorted({
        p["month"] for p in service.store.price_points()
        if p["month"] <= week_month
    })
    latest = months[-1] if months else None
    alerts = [
        a for a in service.list_alerts()
        if latest is not None and a["period_month"] == latest
    ]
    alerts.sort(key=lambda a: a["alert_id"])
    notes = []
    if latest is None:
        notes.append("no price month is tracked at the week's end")
    elif not alerts:
        notes.append(f"no alerts fired on {latest} movements")
    else:
        notes.append(
            f"{len(alerts)} alert(s) fired on {latest} movements; "
            "each figure is the alert's own recorded headline figure")
    return _section(
        pack.SECTION_PRICES, [a["alert_id"] for a in alerts],
        [alert_figure(a) for a in alerts], notes)


def _collect_supply(service, scope: dict, as_of: str) -> dict:
    store = service.store
    figures: list[dict] = []
    artefact_ids: list[str] = []
    notes: list[str] = []
    for product in PRODUCTS:
        if product not in supply_engine.positionable_products(store):
            continue
        gap = service.supply_gap(
            product, scope["crop_year"], scope["season"], as_of)
        predecessor = (
            store.get_gap(gap["supersedes"]) if gap.get("supersedes")
            else None)
        cell_figures = gap_figures(gap, predecessor)
        figures.extend(cell_figures)
        artefact_ids.append(gap["gap_id"])
        if predecessor is not None and "changed" in (
                cell_figures[0]["badges"]):
            notes.append(
                f"{product}: the head gap moved against "
                f"{predecessor['gap_id']} — band "
                f"{predecessor['band']} -> {gap['band']}, gap "
                f"{predecessor['gap_tonnes']} -> "
                f"{gap['gap_tonnes']} t")
    return _section(pack.SECTION_SUPPLY, artefact_ids, figures, notes)


def _collect_policy(service, week_month: str, as_of: str) -> dict:
    service.register_policy_events(as_of)
    events = [
        e for e in service.list_policy_events(hypothetical=False)
        if e["effective_from_month"] <= week_month
        <= e["effective_to_month"]
    ]
    events.sort(key=lambda e: e["registry_id"])
    notes = []
    if not events:
        notes.append(
            "no registered event's window covers the week's month")
    return _section(
        pack.SECTION_POLICY, [e["registry_id"] for e in events],
        [policy_figure(e, week_month) for e in events], notes)


def _collect_shares(service, scope: dict, as_of: str) -> dict:
    store = service.store
    tracked = sorted({
        p["product"] for p in store.competitor_points()
    })
    district_names = {
        d["district_id"]: d["name"] for d in store.list_districts()
    }
    figures: list[dict] = []
    artefact_ids: list[str] = []
    notes: list[str] = []
    for district_id in sorted(district_names):
        for product in tracked:
            movement = service.share_movement(
                district_id, product, scope["season"], as_of)
            share = service.market_share(
                district_id, product, CROP_YEARS[-1],
                scope["season"], as_of)
            figures.extend(share_figures(
                movement, share, district_names[district_id]))
            artefact_ids.extend(
                [movement["movement_id"], share["share_id"]])
            if share.get("headline_note"):
                notes.append(
                    f"{district_names[district_id]} {product}: "
                    f"{share['headline_note']}")
    if any("stale" in f["badges"]
           for f in figures if f["unit"] == "pp"):
        notes.insert(0, (
            "share movements compare full-season readings, which "
            "include stale months and are labelled as such on the "
            "share artefacts; movement figures are badged stale "
            "and are never presented as current"))
    return _section(pack.SECTION_SHARES, artefact_ids, figures, notes)


def _collect_planning(service) -> dict:
    figures: list[dict] = []
    artefact_ids: list[str] = []
    unadopted = 0
    for options in service.store.list_planning_options():
        adoption = service.current_adoption(options["options_id"])
        if adoption is None:
            unadopted += 1
            continue
        figures.append(planning_figure(options, adoption))
        artefact_ids.append(adoption["adoption_id"])
    notes = []
    if unadopted:
        notes.append(
            f"{unadopted} comparison(s) carry no adoption — "
            "no plan follows them yet")
    if not figures:
        notes.append("no planning option has been adopted")
    return _section(pack.SECTION_PLANNING, artefact_ids, figures, notes)


def collect_sections(service, scope: dict, week_month: str,
                     as_of: str) -> list[dict]:
    """Every section of the brief, in pack order, struck
    from the heads of record at the brief's as-of."""
    return [
        _collect_demand(service, scope, as_of),
        _collect_prices(service, week_month, as_of),
        _collect_supply(service, scope, as_of),
        _collect_policy(service, week_month, as_of),
        _collect_shares(service, scope, as_of),
        _collect_planning(service),
    ]


# ---------------------------------------------------------------------------
# The drafted summary: the model drafts words over the brief's
# figures; every number it states must be one of them (R2's
# figure-verifier discipline, at brief scale).
# ---------------------------------------------------------------------------


def narrative_payload(brief_week: dict, sections: list[dict]) -> str:
    """The drafting payload, built only from the brief's
    figures: every number in it is a figure value, so the
    offline composer's echo is verifiable by construction
    and a hosted draft is held to the same set."""
    lines = [
        f"Weekly market brief — week ending {brief_week['week_ending']}, "
        f"covering {brief_week['season_scope']['season']} "
        f"{brief_week['season_scope']['crop_year']}.",
    ]
    for section in sections:
        for figure in section["figures"]:
            if isinstance(figure["value"], (int, float)) \
                    and not isinstance(figure["value"], bool):
                lines.append(
                    f"{section['title']}: {figure['label']} is "
                    f"{figure['value']:.2f} {figure['unit']}.")
    return "\n".join(lines)


def figure_universe(sections: list[dict]) -> list[float]:
    """Every number a brief narrative may state: the
    brief's own numeric figure values."""
    universe = {0.0}
    for section in sections:
        for figure in section["figures"]:
            if isinstance(figure["value"], (int, float)) \
                    and not isinstance(figure["value"], bool):
                universe.add(float(figure["value"]))
    return sorted(universe)


def draft_narrative(model, brief_week: dict,
                    sections: list[dict]) -> dict:
    """Draft the brief's summary through the model port
    and figure-check it. A wrong figure raises
    BriefRefused — the refusal the assembly records."""
    payload = narrative_payload(brief_week, sections)
    reply = model.complete(
        "You draft weekly market briefs from computed figures. "
        "State only the figures you are given; never invent one.",
        payload,
    )
    problems = demand_engine.verify_figures(
        reply.text, figure_universe(sections), strip_tokens=PRODUCTS)
    if problems:
        raise BriefRefused(problems)
    return {
        "text": reply.text,
        "model_profile": reply.profile,
        "model_name": reply.model,
        "figures": demand_engine.extract_figures(
            reply.text, strip_tokens=PRODUCTS),
    }


# ---------------------------------------------------------------------------
# Assembly: candidate first, verified, only then an artefact.
# ---------------------------------------------------------------------------


def build_brief(week_ending: str, as_of: str, assembled_by: str,
                scope: dict, sections: list[dict], narrative: dict,
                supersedes_refusal: str | None) -> WeeklyBrief:
    """Assemble the brief artefact from its verified
    content. Identity is content: week, as-of, scope, the
    sections' figures and the narrative text."""
    fingerprint = _fingerprint({
        "week_ending": week_ending, "as_of": as_of,
        "scope": {k: scope[k] for k in ("crop_year", "season")},
        "sections": [
            {"key": s["key"], "figures": s["figures"],
             "artefact_ids": s["artefact_ids"]}
            for s in sections
        ],
        "narrative": narrative["text"],
        "pack": pack.RULES_VERSION,
    })
    return WeeklyBrief(
        brief_id=f"BRF-{fingerprint[:10]}", fingerprint=fingerprint,
        week_start=pack.week_start_for(week_ending),
        week_ending=week_ending, as_of=as_of,
        season_scope=scope, assembled_by=assembled_by,
        sections=sections, narrative=narrative,
        supersedes_refusal=supersedes_refusal,
        rules_version=pack.RULES_VERSION,
    )


def build_refusal(week_ending: str, as_of: str, assembled_by: str,
                  problems: list[str]) -> BriefRefusal:
    """The refusal artefact: the week's failed assembly,
    on record with its reasons. A later clean assembly
    for the same week supersedes it by link."""
    fingerprint = _fingerprint({
        "week_ending": week_ending, "as_of": as_of,
        "assembled_by": assembled_by, "problems": problems,
        "pack": pack.RULES_VERSION,
    })
    return BriefRefusal(
        refusal_id=f"BRX-{fingerprint[:10]}",
        fingerprint=fingerprint,
        week_start=pack.week_start_for(week_ending),
        week_ending=week_ending, as_of=as_of,
        assembled_by=assembled_by, problems=problems,
        rules_version=pack.RULES_VERSION,
    )


def assemble_candidate(service, week_ending: str, as_of: str,
                       assembled_by: str, model) -> WeeklyBrief:
    """Collect the sections, draft the summary, and build
    the candidate brief. Raises BriefRefused when the
    draft itself fails figure verification; the caller
    verifies the candidate's figures before storing it."""
    scope = pack.season_scope_for_month(week_ending[:7])
    sections = collect_sections(service, scope, week_ending[:7], as_of)
    week = {"week_ending": week_ending, "season_scope": scope}
    narrative = draft_narrative(model, week, sections)
    prior = service.store.list_brief_refusals(week_ending=week_ending)
    latest_refusal = max(
        prior, key=lambda r: (r["as_of"], r["refusal_id"]),
        default=None)
    return build_brief(
        week_ending, as_of, assembled_by, scope, sections, narrative,
        latest_refusal["refusal_id"] if latest_refusal else None)


# ---------------------------------------------------------------------------
# The verifier: every figure re-performed from its pinned
# artefact, every pinned artefact re-verified under its own
# family's verifier. One problem refuses the brief wholesale.
# ---------------------------------------------------------------------------


def _verify_section_figures(store, section: dict,
                            week_month: str) -> list[str]:
    """Rebuild one section's figures from its pinned
    artefacts and compare, then re-verify each pinned
    artefact under its family's verifier."""
    problems: list[str] = []
    key = section["key"]
    ids = section["artefact_ids"]
    rebuilt: list[dict] = []
    if key == pack.SECTION_DEMAND:
        for artefact_id in ids:
            outlook = store.get_outlook(artefact_id)
            if outlook is None:
                problems.append(f"outlook {artefact_id} is not in the store")
                continue
            rebuilt.extend(outlook_figures(outlook))
            problems.extend(
                f"outlook {artefact_id}: {p}"
                for p in demand_engine.verify_outlook(store, outlook))
    elif key == pack.SECTION_PRICES:
        for artefact_id in ids:
            alert = store.get_alert(artefact_id)
            if alert is None:
                problems.append(f"alert {artefact_id} is not in the store")
                continue
            rebuilt.append(alert_figure(alert))
            problems.extend(
                f"alert {artefact_id}: {p}"
                for p in movement_engine.verify_alert(store, alert))
    elif key == pack.SECTION_SUPPLY:
        for artefact_id in ids:
            gap = store.get_gap(artefact_id)
            if gap is None:
                problems.append(f"gap {artefact_id} is not in the store")
                continue
            predecessor = (
                store.get_gap(gap["supersedes"])
                if gap.get("supersedes") else None)
            rebuilt.extend(gap_figures(gap, predecessor))
            problems.extend(
                f"gap {artefact_id}: {p}"
                for p in supply_engine.verify_gap(store, gap))
    elif key == pack.SECTION_POLICY:
        for artefact_id in ids:
            event = store.get_policy_registration(artefact_id)
            if event is None:
                problems.append(
                    f"policy registration {artefact_id} is not in the store")
                continue
            rebuilt.append(policy_figure(event, week_month))
            problems.extend(
                f"policy event {artefact_id}: {p}"
                for p in policy_engine.verify_policy_event(store, event))
    elif key == pack.SECTION_SHARES:
        district_names = {
            d["district_id"]: d["name"] for d in store.list_districts()
        }
        by_id = {a: None for a in ids}
        for artefact_id in ids:
            movement = store.get_share_movement(artefact_id)
            if movement is not None:
                by_id[artefact_id] = ("movement", movement)
                problems.extend(
                    f"share movement {artefact_id}: {p}"
                    for p in share_engine.verify_movement(store, movement))
                continue
            share = store.get_share(artefact_id)
            if share is not None:
                by_id[artefact_id] = ("share", share)
                problems.extend(
                    f"share {artefact_id}: {p}"
                    for p in share_engine.verify_share(store, share))
                continue
            problems.append(
                f"share artefact {artefact_id} is not in the store")
        for i in range(0, len(ids) - 1, 2):
            first, second = by_id.get(ids[i]), by_id.get(ids[i + 1])
            if first is None or second is None:
                continue
            movement = first[1] if first[0] == "movement" else second[1]
            share = first[1] if first[0] == "share" else second[1]
            rebuilt.extend(share_figures(
                movement, share,
                district_names.get(movement["district_id"],
                                   movement["district_id"])))
    elif key == pack.SECTION_PLANNING:
        for artefact_id in ids:
            adoption = store.get_planning_adoption(artefact_id)
            if adoption is None:
                problems.append(
                    f"planning adoption {artefact_id} is not in the store")
                continue
            options = store.get_planning_options(adoption["options_id"])
            if options is None:
                problems.append(
                    f"planning options {adoption['options_id']} are not "
                    "in the store")
                continue
            rebuilt.append(planning_figure(options, adoption))
            problems.extend(
                f"adoption {artefact_id}: {p}"
                for p in scenario_engine.verify_adoption(store, adoption))
    if json.dumps(rebuilt, sort_keys=True) != \
            json.dumps(section["figures"], sort_keys=True):
        problems.append(
            f"section {key}: figures do not re-perform from their "
            "pinned artefacts")
    return problems


def verify_brief(store, brief: dict) -> list[str]:
    """Re-perform a brief end to end: its week arithmetic,
    its season scope against the pack rule, every figure
    from its pinned artefact, every pinned artefact under
    its family verifier, the narrative against the brief's
    figure set, and the brief's identity against its
    content. Any problem refuses the brief wholesale."""
    problems: list[str] = []
    if brief["rules_version"] != pack.RULES_VERSION:
        return [f"brief names unknown brief pack {brief['rules_version']}"]
    if brief["week_start"] != pack.week_start_for(brief["week_ending"]):
        problems.append(
            f"week start {brief['week_start']} is not six days before "
            f"the week ending {brief['week_ending']}")
    scope = pack.season_scope_for_month(brief["week_ending"][:7])
    if {k: brief["season_scope"][k] for k in ("crop_year", "season")} \
            != {k: scope[k] for k in ("crop_year", "season")}:
        problems.append(
            "the brief's season scope does not match the pack's "
            f"scope rule for {brief['week_ending'][:7]} "
            f"({scope['season']} {scope['crop_year']})")
    keys = [s["key"] for s in brief["sections"]]
    if keys != pack.SECTION_ORDER:
        problems.append(
            f"the brief's sections are {keys}, not the pack order "
            f"{pack.SECTION_ORDER}")
    week_month = brief["week_ending"][:7]
    for section in brief["sections"]:
        for figure in section["figures"]:
            if not figure.get("artefact_id"):
                problems.append(
                    f"section {section['key']}: figure "
                    f"{figure.get('label')!r} carries no artefact lineage")
        problems.extend(
            _verify_section_figures(store, section, week_month))
    narrative = brief["narrative"]
    problems.extend(
        f"narrative: {p}" for p in demand_engine.verify_figures(
            narrative["text"], figure_universe(brief["sections"]),
            strip_tokens=PRODUCTS))
    extracted = demand_engine.extract_figures(
        narrative["text"], strip_tokens=PRODUCTS)
    if extracted != narrative["figures"]:
        problems.append(
            "the narrative's recorded figures do not match its text")
    rebuilt = build_brief(
        brief["week_ending"], brief["as_of"], brief["assembled_by"],
        brief["season_scope"], brief["sections"], brief["narrative"],
        brief["supersedes_refusal"])
    if rebuilt.brief_id != brief["brief_id"] \
            or rebuilt.fingerprint != brief["fingerprint"]:
        problems.append("the brief's id does not match its content")
    if brief["supersedes_refusal"] is not None:
        refusal = store.get_brief_refusal(brief["supersedes_refusal"])
        if refusal is None:
            problems.append(
                f"superseded refusal {brief['supersedes_refusal']} is "
                "not in the store")
        elif refusal["week_ending"] != brief["week_ending"]:
            problems.append(
                "the brief supersedes a refusal for a different week")
    return problems


# ---------------------------------------------------------------------------
# Report packs: files rendered from artefacts, with a provenance
# appendix and a checksum manifest.
# ---------------------------------------------------------------------------


def _appendix_entry(table: str, label: str, artefact_id: str,
                    source_as_of: str, note: str = "") -> dict:
    return {"table": table, "label": label,
            "artefact_id": artefact_id, "source_as_of": source_as_of,
            "note": note}


def collect_product_pack(service, product: str, as_of: str):
    """One product's pack tables: demand per district for
    both seasons of the latest tracked crop year, the
    season supply gaps, and the latest price movement
    with its open-alert position."""
    store = service.store
    crop_year = CROP_YEARS[-1]
    district_names = {
        d["district_id"]: d["name"] for d in store.list_districts()
    }
    tables: dict[str, list[dict]] = {name: [] for name
                                     in pack.PACK_TABLES[pack.PACK_PRODUCT]}
    appendix: list[dict] = []
    for season in ("kharif", "rabi"):
        service.demand_outlook(crop_year, season, as_of)
        for district_id in sorted(district_names):
            estimate = service.estimate_demand(
                district_id, product, crop_year, season, as_of)
            tables["demand"].append({
                "district_id": district_id,
                "district_name": district_names[district_id],
                "crop_year": crop_year, "season": season,
                "estimate_id": estimate["estimate_id"],
                "status": estimate["status"],
                "total_tonnes": estimate["total_tonnes"],
                "as_of": estimate["as_of"],
            })
            appendix.append(_appendix_entry(
                "demand",
                f"{district_names[district_id]} {product} {season} "
                f"{crop_year} demand",
                estimate["estimate_id"], estimate["as_of"],
                "head demand estimate for the cell"))
        if product in supply_engine.positionable_products(store):
            gap = service.supply_gap(product, crop_year, season, as_of)
            tables["supply"].append({
                "product": product, "crop_year": crop_year,
                "season": season, "gap_id": gap["gap_id"],
                "band": gap["band"],
                "gap_tonnes": gap["gap_tonnes"],
                "programme_cover_pct": gap["programme_cover_pct"],
                "slipped_tonnes": gap["slipped_tonnes"],
                "as_of": gap["as_of"],
            })
            appendix.append(_appendix_entry(
                "supply", f"{product} {season} {crop_year} supply gap",
                gap["gap_id"], gap["as_of"],
                "head supply gap for the season"))
    service.run_price_watch(as_of)
    movements = store.list_movements("product", product)
    if movements:
        latest = movements[-1]
        open_alerts = [
            a for a in service.list_alerts("product", product)
            if a["state"] != "closed"
        ]
        band = "none"
        for alert in open_alerts:
            if alert_pack.BAND_RANK[alert["band"]] \
                    > alert_pack.BAND_RANK[band]:
                band = alert["band"]
        tables["prices"].append({
            "series_kind": "product", "item": product,
            "month": latest["month"],
            "movement_id": latest["movement_id"],
            "mom_pct": latest["mom_pct"],
            "baseline_pct": latest["baseline_pct"],
            "open_alerts": len(open_alerts), "band": band,
        })
        appendix.append(_appendix_entry(
            "prices", f"{product} latest price movement",
            latest["movement_id"], latest["as_of"],
            "latest computed movement for the product series"))
    return tables, appendix


def collect_region_pack(service, region: str, as_of: str):
    """One region's pack tables: demand per district and
    product for the season in scope at the pack's as-of,
    and the headline shares for the tracked products."""
    store = service.store
    crop_year = CROP_YEARS[-1]
    scope = pack.season_scope_for_month(as_of[:7])
    season = scope["season"]
    districts = [d for d in store.list_districts()
                 if d["region"] == region]
    if not districts:
        raise ValueError(
            f"no tracked district sits in region {region!r} — the "
            f"tracked regions are "
            f"{sorted({d['region'] for d in store.list_districts()})}")
    tracked = sorted({p["product"] for p in store.competitor_points()})
    tables: dict[str, list[dict]] = {name: [] for name
                                     in pack.PACK_TABLES[pack.PACK_REGION]}
    appendix: list[dict] = []
    for district in sorted(districts, key=lambda d: d["district_id"]):
        for product in PRODUCTS:
            estimate = service.estimate_demand(
                district["district_id"], product, crop_year, season,
                as_of)
            tables["demand"].append({
                "district_id": district["district_id"],
                "district_name": district["name"],
                "product": product,
                "estimate_id": estimate["estimate_id"],
                "status": estimate["status"],
                "total_tonnes": estimate["total_tonnes"],
                "as_of": estimate["as_of"],
            })
            appendix.append(_appendix_entry(
                "demand",
                f"{district['name']} {product} {season} {crop_year} "
                "demand",
                estimate["estimate_id"], estimate["as_of"],
                "head demand estimate for the cell"))
        for product in tracked:
            share = service.market_share(
                district["district_id"], product, crop_year, season,
                as_of)
            headline = share.get("headline")
            tables["shares"].append({
                "district_id": district["district_id"],
                "district_name": district["name"],
                "product": product,
                "share_id": share["share_id"],
                "status": share["status"],
                "kaveri_headline_pct": (
                    headline["kaveri"]["share_of_observed_market_pct"]
                    if headline else None),
                "headline_note": share["headline_note"],
                "as_of": share["as_of"],
            })
            appendix.append(_appendix_entry(
                "shares",
                f"{district['name']} {product} headline share",
                share["share_id"], share["as_of"],
                share["headline_note"] or
                "headline share of the observed market"))
    return tables, appendix


def build_pack(pack_kind: str, pack_key: str, as_of: str,
               exported_by: str, tables: dict,
               appendix: list[dict]) -> ExportPack:
    """Assemble the pack artefact: its identity is its
    content (kind, key, as-of, tables, appendix), and its
    manifest is computed over the rendered files, so the
    stored checksums are the export's own."""
    fingerprint = _fingerprint({
        "kind": pack_kind, "key": pack_key, "as_of": as_of,
        "tables": tables, "appendix": appendix,
        "pack": pack.RULES_VERSION,
    })
    artefact = ExportPack(
        pack_id=f"PCK-{fingerprint[:10]}", fingerprint=fingerprint,
        pack_kind=pack_kind, pack_key=pack_key, as_of=as_of,
        exported_by=exported_by, tables=tables, appendix=appendix,
        manifest={}, rules_version=pack.RULES_VERSION,
    )
    artefact.manifest = {
        name: hashlib.sha256(data).hexdigest()
        for name, data in render_pack_files(artefact.model_dump()).items()
        if name != pack.MANIFEST_NAME
    }
    return artefact


def _csv_bytes(columns: list[str], rows: list[dict]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([row.get(c) for c in columns])
    return buffer.getvalue().encode()


def _appendix_bytes(pack_dict: dict) -> bytes:
    lines = [
        f"# Provenance appendix — {pack_dict['pack_kind']} pack "
        f"{pack_dict['pack_key']} (as of {pack_dict['as_of']})",
        "",
        "Every exported figure traces to the artefact it was read "
        "from; the pack verifier re-performs each one against the "
        "store.",
        "",
    ]
    for entry in pack_dict["appendix"]:
        lines.append(
            f"- [{entry['table']}] {entry['label']} — "
            f"artefact {entry['artefact_id']}, as of "
            f"{entry['source_as_of']}"
            + (f" — {entry['note']}" if entry["note"] else ""))
    return ("\n".join(lines) + "\n").encode()


def render_pack_files(pack_dict: dict) -> dict[str, bytes]:
    """The pack's files, rendered purely from the stored
    artefact: the table CSVs in the pack's stated column
    order, the provenance appendix, and the manifest that
    names every other file's checksum."""
    files: dict[str, bytes] = {}
    for table, columns in pack.PACK_TABLES[pack_dict["pack_kind"]].items():
        files[f"{table}.csv"] = _csv_bytes(
            columns, pack_dict["tables"].get(table, []))
    files[pack.APPENDIX_NAME] = _appendix_bytes(pack_dict)
    manifest = {
        "pack_id": pack_dict["pack_id"],
        "fingerprint": pack_dict["fingerprint"],
        "files": pack_dict["manifest"],
    }
    files[pack.MANIFEST_NAME] = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    return files


def verify_pack_files(pack_dict: dict,
                      files: dict[str, bytes]) -> list[str]:
    """Check a set of exported files against the pack's
    manifest: every manifested file present and byte-exact
    under its checksum, no unmanifested file riding along,
    and the manifest file itself naming this pack. A
    flipped byte in any figure is a named problem."""
    problems: list[str] = []
    manifest = pack_dict["manifest"]
    for name, digest in sorted(manifest.items()):
        if name not in files:
            problems.append(f"exported file {name} is missing")
        elif hashlib.sha256(files[name]).hexdigest() != digest:
            problems.append(
                f"exported file {name} fails its manifest checksum — "
                "its content is not the pack artefact's content")
    for name in sorted(files):
        if name != pack.MANIFEST_NAME and name not in manifest:
            problems.append(
                f"exported file {name} is not in the pack's manifest")
    if pack.MANIFEST_NAME in files:
        try:
            stated = json.loads(files[pack.MANIFEST_NAME])
        except (ValueError, UnicodeDecodeError):
            problems.append("the manifest file does not parse")
        else:
            if stated.get("pack_id") != pack_dict["pack_id"] \
                    or stated.get("fingerprint") \
                    != pack_dict["fingerprint"]:
                problems.append(
                    "the manifest file names a different pack")
            elif stated.get("files") != manifest:
                problems.append(
                    "the manifest file's checksums do not match the "
                    "pack artefact's manifest")
    else:
        problems.append(f"exported file {pack.MANIFEST_NAME} is missing")
    return problems


def verify_pack(store, pack_dict: dict,
                fresh_tables: dict) -> list[str]:
    """Re-perform a stored pack: its rendered files match
    its manifest, its tables match a fresh collection from
    the store at its as-of exactly (export figures match
    reads), and its identity matches its content."""
    problems: list[str] = []
    if pack_dict["rules_version"] != pack.RULES_VERSION:
        return [f"pack names unknown brief pack "
                f"{pack_dict['rules_version']}"]
    problems.extend(verify_pack_files(
        pack_dict, render_pack_files(pack_dict)))
    if json.dumps(fresh_tables, sort_keys=True) != \
            json.dumps(pack_dict["tables"], sort_keys=True):
        problems.append(
            "the pack's tables do not re-perform from the store at "
            f"its as-of {pack_dict['as_of']} — an export figure "
            "differs from the read")
    rebuilt = build_pack(
        pack_dict["pack_kind"], pack_dict["pack_key"],
        pack_dict["as_of"], pack_dict["exported_by"],
        pack_dict["tables"], pack_dict["appendix"])
    if rebuilt.pack_id != pack_dict["pack_id"] \
            or rebuilt.fingerprint != pack_dict["fingerprint"]:
        problems.append("the pack's id does not match its content")
    if rebuilt.manifest != pack_dict["manifest"]:
        problems.append("the pack's manifest does not match its files")
    return problems


# ---------------------------------------------------------------------------
# Publication acts & the decision log.
# ---------------------------------------------------------------------------


def family_key_for(artefact_kind: str, artefact: dict) -> str:
    """The family a published artefact belongs to: a
    week's briefs are one family, a season's outlooks
    another — the acts inside a family chain together."""
    if artefact_kind == pack.KIND_BRIEF:
        return f"weekly_brief:{artefact['week_ending']}"
    if artefact_kind == pack.KIND_OUTLOOK:
        return (f"season_outlook:{artefact['crop_year']}:"
                f"{artefact['season']}")
    raise ValueError(
        f"artefact kind {artefact_kind!r} cannot be published — the "
        f"brief pack names {pack.PUBLICATION_KINDS}")


def artefact_fingerprint_for(artefact_kind: str,
                             artefact: dict) -> str:
    """The content fingerprint an act binds: the brief's
    own fingerprint, the outlook's fact fingerprint."""
    if artefact_kind == pack.KIND_BRIEF:
        return artefact["fingerprint"]
    return artefact["fact_fingerprint"]


def build_publication_act(artefact_kind: str, artefact: dict,
                          published_by: str, published_at: str,
                          note: str | None,
                          supersedes: str | None) -> PublicationAct:
    """One publication act, binding the exact artefact
    version by its fingerprint. Nothing renders as
    published without this act existing."""
    family = family_key_for(artefact_kind, artefact)
    bound = artefact_fingerprint_for(artefact_kind, artefact)
    fingerprint = _fingerprint({
        "kind": artefact_kind, "artefact": artefact[
            "brief_id" if artefact_kind == pack.KIND_BRIEF
            else "outlook_id"],
        "bound": bound, "family": family,
        "published_by": published_by, "published_at": published_at,
        "note": note, "supersedes": supersedes,
        "pack": pack.RULES_VERSION,
    })
    artefact_id = artefact[
        "brief_id" if artefact_kind == pack.KIND_BRIEF
        else "outlook_id"]
    return PublicationAct(
        act_id=f"PUB-{fingerprint[:10]}", fingerprint=fingerprint,
        artefact_kind=artefact_kind, artefact_id=artefact_id,
        artefact_fingerprint=bound, family_key=family,
        published_by=published_by, published_at=published_at,
        note=note, supersedes=supersedes,
        rules_version=pack.RULES_VERSION,
    )


def head_act(acts: list[dict]) -> dict | None:
    """The current act in a family's chain: the act no
    other act supersedes from."""
    superseded = {a["supersedes"] for a in acts if a.get("supersedes")}
    heads = [a for a in acts if a["act_id"] not in superseded]
    return heads[0] if heads else None


def publication_state(acts: list[dict], artefact_kind: str,
                      artefact_id: str) -> dict:
    """One artefact's publication position, folded from
    the acts: draft until an act names this exact
    artefact; published with its act; a published artefact
    whose family's head act has moved on to a newer
    version reads published but no longer current."""
    mine = [a for a in acts
            if a["artefact_kind"] == artefact_kind
            and a["artefact_id"] == artefact_id]
    if not mine:
        return {"status": "draft"}
    act = mine[-1]
    family = [a for a in acts if a["family_key"] == act["family_key"]]
    head = head_act(family)
    state = {
        "status": "published",
        "act_id": act["act_id"],
        "published_by": act["published_by"],
        "published_at": act["published_at"],
        "is_current": head is not None
        and head["act_id"] == act["act_id"],
    }
    if not state["is_current"] and head is not None:
        state["superseded_by_act"] = head["act_id"]
        state["current_artefact_id"] = head["artefact_id"]
    return state


def derive_decision_log(acts: list[dict]) -> list[dict]:
    """The decision log, re-derived from the acts alone:
    every act in publication order with its sequence
    number, its family, and the artefact version its act
    superseded (read off the superseded act)."""
    ordered = sorted(
        acts, key=lambda a: (a["published_at"], a["act_id"]))
    by_id = {a["act_id"]: a for a in acts}
    entries = []
    for seq, act in enumerate(ordered, start=1):
        prior = by_id.get(act["supersedes"]) if act["supersedes"] \
            else None
        entries.append({
            "seq": seq,
            "act_id": act["act_id"],
            "artefact_kind": act["artefact_kind"],
            "artefact_id": act["artefact_id"],
            "family_key": act["family_key"],
            "published_by": act["published_by"],
            "published_at": act["published_at"],
            "note": act["note"],
            "supersedes_act": act["supersedes"],
            "supersedes_artefact_id": prior["artefact_id"]
            if prior else None,
        })
    return entries


def verify_decision_log(store, acts: list[dict]) -> list[str]:
    """Re-derive the log and check it is gapless: the
    sequence runs 1..N without a gap; inside each family
    the acts form exactly one chain — every supersedes
    link resolves inside the family, no act is superseded
    twice, exactly one head — and every act still binds
    the artefact it published, by fingerprint, against
    the artefact as stored now."""
    problems: list[str] = []
    entries = derive_decision_log(acts)
    if [e["seq"] for e in entries] != list(range(1, len(entries) + 1)):
        problems.append("the decision log's sequence has gaps")
    by_family: dict[str, list[dict]] = {}
    for act in acts:
        by_family.setdefault(act["family_key"], []).append(act)
    by_id = {a["act_id"]: a for a in acts}
    for family, members in sorted(by_family.items()):
        superseded_by: dict[str, str] = {}
        for act in members:
            prior_id = act["supersedes"]
            if prior_id is None:
                continue
            prior = by_id.get(prior_id)
            if prior is None:
                problems.append(
                    f"family {family}: act {act['act_id']} supersedes "
                    f"{prior_id}, which is not in the store")
            elif prior["family_key"] != family:
                problems.append(
                    f"family {family}: act {act['act_id']} supersedes "
                    f"an act of family {prior['family_key']}")
            if prior_id in superseded_by:
                problems.append(
                    f"family {family}: act {prior_id} is superseded "
                    f"by both {superseded_by[prior_id]} and "
                    f"{act['act_id']} — the chain forks")
            superseded_by[prior_id] = act["act_id"]
        heads = [a for a in members
                 if a["act_id"] not in superseded_by]
        if len(heads) != 1:
            problems.append(
                f"family {family}: {len(heads)} chain heads for "
                f"{len(members)} acts — the chain is broken")
            continue
        # Walk the chain from the head: every member must
        # be reachable, exactly once.
        seen: list[str] = []
        current = heads[0]
        while current is not None:
            if current["act_id"] in seen:
                problems.append(
                    f"family {family}: the chain cycles at "
                    f"{current['act_id']}")
                break
            seen.append(current["act_id"])
            current = by_id.get(current["supersedes"]) \
                if current["supersedes"] else None
        if len(seen) != len(members):
            problems.append(
                f"family {family}: the chain reaches {len(seen)} of "
                f"{len(members)} acts — an act is orphaned")
    for act in acts:
        if act["artefact_kind"] == pack.KIND_BRIEF:
            target = store.get_weekly_brief(act["artefact_id"])
        else:
            target = store.get_outlook(act["artefact_id"])
        if target is None:
            problems.append(
                f"act {act['act_id']}: published artefact "
                f"{act['artefact_id']} is not in the store")
            continue
        bound = artefact_fingerprint_for(act["artefact_kind"], target)
        if bound != act["artefact_fingerprint"]:
            problems.append(
                f"act {act['act_id']}: the act binds fingerprint "
                f"{act['artefact_fingerprint']}, but "
                f"{act['artefact_id']} as stored carries {bound} — "
                "the published version is not the stored version")
        if act["family_key"] != family_key_for(
                act["artefact_kind"], target):
            problems.append(
                f"act {act['act_id']}: the act's family "
                f"{act['family_key']} is not the artefact's family")
    return problems


# ---------------------------------------------------------------------------
# Rendering: the brief as a page. Draft and published are
# distinct on its face; a draft never carries the published mark.
# ---------------------------------------------------------------------------


def render_brief_html(brief: dict, publication: dict) -> str:
    """The brief's page — a pure function of the brief and
    its publication state, so a page can be re-rendered and
    compared. The publication badge is the state's: the
    published mark appears only when an act names this
    exact brief."""
    scope = brief["season_scope"]
    if publication["status"] == "published":
        current = publication.get("is_current", False)
        badge = (
            f'<span class="badge">{pack.BADGE_PUBLISHED}</span> '
            f'<span class="lineage">by '
            f'{_esc(publication["published_by"])} on '
            f'{_esc(publication["published_at"])}'
            + ("" if current else " — a newer version of this "
               "week's brief has since been published")
            + "</span>")
    else:
        badge = f'<span class="badge stale">{pack.BADGE_DRAFT}</span>'
    out = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        f"<title>Weekly market brief — week ending "
        f"{_esc(brief['week_ending'])} — Kaveri Agro Inputs</title>",
        f"<style>{_CSS}</style>",
        "</head>",
        "<body>",
        "<header>",
        '<p class="lineage">Kaveri Agro Inputs · market intelligence</p>',
        f"<h1>Weekly market brief — week ending "
        f"{_esc(brief['week_ending'])}</h1>",
        f"<p>{badge}</p>",
        f'<p class="muted">Week {brief["week_start"]} to '
        f'{brief["week_ending"]} · season scope: {scope["season"]} '
        f'{scope["crop_year"]} — {_esc(scope["note"])} · assembled '
        f'by {_esc(brief["assembled_by"])} · brief '
        f'{brief["brief_id"]}</p>',
        "</header>",
        "<main>",
        '<section class="panel">',
        "<h2>Summary</h2>",
        f"<p>{_esc(brief['narrative']['text']).replace(chr(10), '<br>')}</p>",
        f'<p class="lineage">Drafted by '
        f'{_esc(brief["narrative"]["model_profile"])} / '
        f'{_esc(brief["narrative"]["model_name"])}; every figure '
        "figure-checked against the brief's artefacts.</p>",
        "</section>",
    ]
    for section in brief["sections"]:
        out.append('<section class="panel">')
        out.append(f"<h2>{_esc(section['title'])}</h2>")
        out.append(f'<p class="note">{_esc(section["basis"])}</p>')
        if section["figures"]:
            out.append(
                "<table><thead><tr><th>Figure</th><th>Value</th>"
                "<th>Source artefact</th><th></th></tr></thead>"
                "<tbody>")
            for figure in section["figures"]:
                badges = "".join(
                    f'<span class="badge'
                    f'{" stale" if b in ("stale exclusions", "changed") else ""}">'
                    f"{_esc(b)}</span>" for b in figure["badges"])
                out.append(
                    f"<tr><td>{_esc(figure['label'])}</td>"
                    f"<td>{_esc(_fmt(figure['value']))} "
                    f"{_esc(figure['unit'])}</td>"
                    f'<td class="lineage">'
                    f"{_esc(figure['artefact_id'])} · as of "
                    f"{_esc(figure['source_as_of'])}</td>"
                    f"<td>{badges}</td></tr>")
            out.append("</tbody></table>")
        for note in section["notes"]:
            out.append(f'<p class="note">{_esc(note)}</p>')
        out.append(
            f'<p class="lineage">Section sources: '
            f'{_esc(", ".join(section["artefact_ids"]) or "—")}</p>')
        out.append("</section>")
    out.extend([
        "</main>",
        "<footer>",
        '<div class="footer-brand">'
        '<img src="https://trida.ai/logos-rounded/trida-rounded.png" '
        'alt="Trida AI">'
        "<span>Trida AI blueprint — Fertilizer &amp; Agrochemical "
        "Market Intelligence</span></div>",
        '<div><a href="https://trida.ai">Visit Trida AI →</a>'
        '<a href="https://github.com/tridaai">View all blueprints →</a>'
        "</div>",
        "</footer>",
        "</body>",
        "</html>",
    ])
    return "\n".join(out)
