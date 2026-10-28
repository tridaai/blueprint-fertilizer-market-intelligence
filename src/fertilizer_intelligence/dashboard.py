"""The ask-in-plain-language dashboard assembler (R8,
roadmap F21-DR1).

Rounds 2–7 built the computed views: demand estimates and
outlooks, the price watch and its board, supply positions
and gaps, the policy registry, competitor shares and their
movements, field-signal assessments. This round builds the
layer a non-technical desk actually opens: a plain-language
business question goes in, a dashboard comes out — and the
dashboard is nothing but a governed selection of those
artefacts, every figure carrying its lineage.

The flow, and the discipline at each step:

1. **Parse.** The question parses into a dashboard SPEC
   under the dashboard pack (dashboard_rules). The default
   profile is the offline deterministic grammar, stated as
   grammar in code, following the portfolio convention. A
   hosted profile instead asks the model port for panel
   proposals and validates each against the governed schema
   (Pydantic only) — a proposal that does not fit is refused,
   and the refusal is recorded on the spec and rendered as a
   gap panel, never silently dropped and never improvised
   around. A question part that maps to no artefact family
   becomes a gap panel naming the data it would need.
2. **The spec is an artefact.** Insert-only, content-
   addressed, carrying the original question, the asked-by
   attribution, the panels with their artefact bindings
   resolved at ask time, and the parse provenance (which
   grammar rule or model output produced each panel, which
   proposals were refused and why, which pack defaults were
   applied).
3. **Assembly.** A saved or fresh spec assembles into a
   static dashboard rendered only from artefacts. Each
   panel re-resolves to the CURRENT head of its artefact
   family: a figure whose source superseded between spec
   and assembly renders from the current head, and the
   panel notes the supersession. Re-assembly computes a
   diff against the previous assembly — changed figures and
   superseded bindings, stated on the artefact.
4. **Verification before serving.** Before an assembly is
   stored, every figure is re-performed against its pinned
   artefact (the R2 figure-verifier discipline at dashboard
   scale): one mismatch refuses the WHOLE dashboard with
   the panel and figure named — no partial render is ever
   stored. A stored assembly re-verifies the same way, plus
   a byte-exact re-render of its HTML.

Role defaults (regional head, national planner, leadership)
are stated in the pack as panel lists and built through
this same machinery — specs, not code branches.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from typing import Any

from pydantic import BaseModel, Field

from . import alert_rules as alert_pack
from . import dashboard_rules as pack
from .generator import CROP_YEARS, FEEDSTOCKS, KHARIF_CROPS, PRODUCTS, RABI_CROPS
from .supply import head_of


class QuestionRefused(ValueError):
    """The question could not be parsed into a governed spec
    at all — a hosted profile returned nothing parseable.
    Fail-closed: no spec, no fallback guess."""


class DashboardRefused(RuntimeError):
    """A figure did not re-perform against its artefact at
    assembly time. The whole dashboard is refused; nothing
    partial is stored."""


# ---------------------------------------------------------------------------
# Artefacts
# ---------------------------------------------------------------------------


class PanelProposal(BaseModel):
    """One panel as proposed by a model profile — validated
    against the pack before it may enter a spec."""

    kind: str
    scope: dict[str, Any] = Field(default_factory=dict)
    title: str | None = None


class SpecPanel(BaseModel):
    panel_no: int
    kind: str
    title: str
    scope: dict[str, Any]
    origin: dict[str, Any]  # via: grammar | model | role_default; rule: name
    binding_artefact_ids: list[str] = Field(default_factory=list)


class DashboardSpec(BaseModel):
    spec_id: str
    fingerprint: str
    rules_version: str
    question: str
    asked_by: str
    role: str | None = None
    name: str | None = None
    saved_by: str | None = None
    as_of: str
    parse: dict[str, Any]
    panels: list[SpecPanel]


class DashboardAssembly(BaseModel):
    assembly_id: str
    fingerprint: str
    spec_id: str
    supersedes: str | None = None
    assembled_on: str
    rules_version: str
    panels: list[dict[str, Any]]
    diff: list[dict[str, Any]]
    html: str


def _fingerprint(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------------------
# The deterministic grammar (offline profile)
# ---------------------------------------------------------------------------

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
    "june": 6, "july": 7, "august": 8, "september": 9, "october": 10,
    "november": 11, "december": 12,
}
_CROPS = sorted(set(KHARIF_CROPS) | set(RABI_CROPS) | {"wheat"})
_NOT_PLACES = {
    "kharif", "rabi", "the", "our", "this", "that", "season", "india",
    "urea", "dap", "mop", "glyphosate", "chlorpyrifos", "npk",
    *_MONTHS,
}


def _split_clauses(question: str) -> list[str]:
    text = question.strip().rstrip("?").strip()
    clauses: list[str] = []
    for part in re.split(r";", text):
        clauses.extend(
            c.strip() for c in re.split(r",\s*", part) if c.strip()
        )
    out: list[str] = []
    for clause in clauses:
        out.extend(
            s.strip()
            for s in re.split(
                r"\s+and\s+(?=(?:what|how|which|show|give|list|is|are)\b)",
                clause, flags=re.I,
            )
            if s.strip()
        )
    return [re.sub(r"^and\s+", "", c, flags=re.I) for c in out]


def _find_district(store, clause: str) -> tuple[dict | None, str | None]:
    """(tracked district, unknown place name) — at most one
    is non-None."""
    low = clause.lower()
    for district in store.list_districts():
        if district["name"].lower() in low:
            return district, None
    match = re.search(r"\bin\s+([A-Z][a-zA-Z]+)", clause)
    if match and match.group(1).lower() not in _NOT_PLACES:
        return None, match.group(1)
    return None, None


def _find_product(low: str) -> str | None:
    if "npk" in low:
        return "NPK_10_26_26"
    for product in ("glyphosate", "chlorpyrifos", "urea", "dap", "mop"):
        if re.search(rf"\b{product}\b", low):
            return product.upper()
    return None


def _find_feedstock(low: str) -> str | None:
    for label, item in (
        ("natural gas", "NATURAL_GAS"), ("phosphoric acid", "PHOSPHORIC_ACID"),
        ("ammonia", "AMMONIA"), ("sulphur", "SULPHUR"), ("sulfur", "SULPHUR"),
    ):
        if label in low:
            return item
    return None


def _find_crop(low: str) -> str | None:
    for crop in _CROPS:
        if re.search(rf"\b{crop}\b", low):
            return crop
    return None


def _find_season(low: str) -> str | None:
    for season in ("kharif", "rabi"):
        if re.search(rf"\b{season}\b", low):
            return season
    return None


def _find_crop_year(clause: str) -> str | None:
    match = re.search(r"\b(20\d{2})[-–](\d{2})\b", clause)
    return f"{match.group(1)}-{match.group(2)}" if match else None


def _find_month(low: str, crop_year: str) -> str | None:
    for name, number in _MONTHS.items():
        if re.search(rf"\b{name}\b", low):
            base = int(crop_year[:4])
            year = base if number >= 4 else base + 1
            return f"{year}-{number:02d}"
    return None


def _gap_panel(panel_no: int, clause: str, needed: str, rule: str) -> SpecPanel:
    return SpecPanel(
        panel_no=panel_no, kind="gap",
        title=f"Gap — {clause[:72]}",
        scope={"subject": clause, "needed_data": needed},
        origin={"via": "grammar", "rule": rule},
    )


def _panel(panel_no: int, kind: str, scope: dict, store, rule: str,
           via: str = "grammar") -> SpecPanel:
    return SpecPanel(
        panel_no=panel_no, kind=kind,
        title=_panel_title(store, kind, scope),
        scope=scope, origin={"via": via, "rule": rule},
    )


def _panel_title(store, kind: str, scope: dict) -> str:
    def district_name() -> str:
        for d in store.list_districts():
            if d["district_id"] == scope.get("district_id"):
                return d["name"]
        return scope.get("district_id", "")

    if kind == "demand_estimate":
        return (f"{scope['product']} demand — {district_name()}, "
                f"{scope['season']} {scope['crop_year']}")
    if kind == "season_outlook":
        return f"Season outlook — {scope['season']} {scope['crop_year']}"
    if kind == "price_watch":
        return f"{scope['item']} price watch"
    if kind == "watch_board":
        return "Price watch board"
    if kind == "supply_position":
        return f"{scope['product']} supply position — {scope['month']}"
    if kind == "supply_gap":
        return (f"{scope['product']} supply gap — "
                f"{scope['season']} {scope['crop_year']}")
    if kind == "policy_events":
        suffix = f" ({scope['product']})" if scope.get("product") else ""
        return f"Policy events{suffix}"
    if kind == "market_share":
        return (f"Market share — {scope['product']} in {district_name()}, "
                f"{scope['season']} {scope['crop_year']}")
    if kind == "share_movement":
        return (f"Share movement — {scope['product']} in {district_name()}, "
                f"{scope['season']}")
    if kind == "field_signals":
        return (f"Field signals — {scope['product']} in {district_name()}, "
                f"{scope['season']} {scope['crop_year']}")
    return kind


def _needed_for_gap(store, clause: str, base: str,
                    district: dict | None, unknown: str | None,
                    crop: str | None) -> str:
    parts = [base]
    if unknown is not None:
        tracked = ", ".join(d["name"] for d in store.list_districts())
        parts.append(pack.GAP_UNKNOWN_DISTRICT.format(
            name=unknown, tracked=tracked))
    if crop is not None:
        parts.append(pack.GAP_CROP_NOT_PRODUCT.format(
            crop=crop, products=", ".join(PRODUCTS)))
    if district is not None and "monsoon" in clause.lower():
        parts.append(
            f"for {district['name']} the monsoon deviation is one of the "
            "drivers inside the demand estimate panel, with its source "
            "and as-of stated")
    return "; ".join(parts)


def parse_question_grammar(store, question: str) -> tuple[list[SpecPanel], dict]:
    """The offline profile's parse: a deterministic grammar
    over the question, stated in code. Returns the panels
    and the parse provenance (rules used, defaults applied).
    Scope is inherited across clauses per the pack."""
    clauses = _split_clauses(question)
    if not clauses:
        raise QuestionRefused("the question is empty — nothing to parse")
    panels: list[SpecPanel] = []
    rules_used: list[str] = []
    notes: list[str] = []
    context: dict[str, Any] = {}
    latest_year = CROP_YEARS[-1]

    for clause in clauses:
        low = clause.lower()
        panel_no = len(panels) + 1
        district, unknown_place = _find_district(store, clause)
        product = _find_product(low)
        feedstock = _find_feedstock(low)
        crop = _find_crop(low)
        season = _find_season(low)
        crop_year = _find_crop_year(clause)

        eff_district = district["district_id"] if district else context.get("district_id")
        eff_product = product or context.get("product")
        eff_season = season or context.get("season")
        eff_year = crop_year or context.get("crop_year")
        if eff_season is None:
            eff_season = pack.DEFAULT_SEASON
            note = (f"season defaulted to {pack.DEFAULT_SEASON} "
                    "(dashboard pack default — no clause names a season)")
            if note not in notes:
                notes.append(note)
        if eff_year is None:
            eff_year = latest_year
            note = (f"crop year defaulted to {latest_year} "
                    "(latest tracked — no clause names a crop year)")
            if note not in notes:
                notes.append(note)

        def missing(*names: str) -> SpecPanel:
            rules_used.append("grammar:gap_missing_scope")
            return _gap_panel(
                panel_no, clause,
                pack.GAP_MISSING_SCOPE.format(missing=" and ".join(names)),
                "grammar:gap_missing_scope")

        if "monsoon" in low:
            rules_used.append("grammar:gap_monsoon")
            panels.append(_gap_panel(
                panel_no, clause,
                _needed_for_gap(store, clause, pack.GAP_MONSOON_FAMILY,
                                district, unknown_place, crop),
                "grammar:gap_monsoon"))
        elif "share" in low and any(
            w in low for w in ("movement", "change", "moved", "shift")
        ):
            if eff_district is None or eff_product is None:
                panels.append(missing("a district", "a product"))
            else:
                rules_used.append("grammar:share_movement")
                panels.append(_panel(panel_no, "share_movement", {
                    "district_id": eff_district, "product": eff_product,
                    "season": eff_season}, store, "grammar:share_movement"))
        elif "share" in low:
            if eff_district is None or eff_product is None:
                panels.append(missing("a district", "a product"))
            else:
                rules_used.append("grammar:market_share")
                panels.append(_panel(panel_no, "market_share", {
                    "district_id": eff_district, "product": eff_product,
                    "crop_year": eff_year, "season": eff_season},
                    store, "grammar:market_share"))
        elif "field" in low:
            if eff_district is None or eff_product is None:
                panels.append(missing("a district", "a product"))
            else:
                rules_used.append("grammar:field_signals")
                panels.append(_panel(panel_no, "field_signals", {
                    "district_id": eff_district, "product": eff_product,
                    "crop_year": eff_year, "season": eff_season},
                    store, "grammar:field_signals"))
        elif "gap" in low or "short" in low:
            if eff_product is None:
                panels.append(missing("a product"))
            else:
                rules_used.append("grammar:supply_gap")
                panels.append(_panel(panel_no, "supply_gap", {
                    "product": eff_product, "crop_year": eff_year,
                    "season": eff_season}, store, "grammar:supply_gap"))
        elif any(w in low for w in ("position", "inventory", "closing stock")):
            month = _find_month(low, eff_year)
            if eff_product is None or month is None:
                panels.append(missing("a product", "a month"))
            else:
                rules_used.append("grammar:supply_position")
                panels.append(_panel(panel_no, "supply_position", {
                    "product": eff_product, "month": month},
                    store, "grammar:supply_position"))
        elif any(w in low for w in ("policy", "subsidy", "subsidies")):
            rules_used.append("grammar:policy_events")
            scope = {"product": eff_product} if eff_product else {}
            panels.append(_panel(panel_no, "policy_events", scope,
                                 store, "grammar:policy_events"))
        elif "price" in low:
            item = eff_product or feedstock
            if item is None:
                panels.append(missing("a product or feedstock"))
            else:
                rules_used.append("grammar:price_watch")
                kind = "product" if item in PRODUCTS else "feedstock"
                panels.append(_panel(panel_no, "price_watch", {
                    "series_kind": kind, "item": item},
                    store, "grammar:price_watch"))
        elif any(w in low for w in ("board", "alert")):
            rules_used.append("grammar:watch_board")
            panels.append(_panel(panel_no, "watch_board", {}, store,
                                 "grammar:watch_board"))
        elif "outlook" in low:
            rules_used.append("grammar:season_outlook")
            panels.append(_panel(panel_no, "season_outlook", {
                "crop_year": eff_year, "season": eff_season},
                store, "grammar:season_outlook"))
        elif eff_district is not None and eff_product is not None:
            rules_used.append("grammar:demand_estimate")
            panels.append(_panel(panel_no, "demand_estimate", {
                "district_id": eff_district, "product": eff_product,
                "crop_year": eff_year, "season": eff_season},
                store, "grammar:demand_estimate"))
        elif any(w in low for w in ("demand", "estimate", "looking")):
            panels.append(missing("a district", "a product"))
        else:
            rules_used.append("grammar:gap_no_family")
            panels.append(_gap_panel(
                panel_no, clause,
                _needed_for_gap(store, clause, pack.GAP_NO_FAMILY,
                                district, unknown_place, crop),
                "grammar:gap_no_family"))

        if district is not None:
            context["district_id"] = district["district_id"]
        if product is not None:
            context["product"] = product
        if season is not None:
            context["season"] = season
        if crop_year is not None:
            context["crop_year"] = crop_year

    parse = {
        "profile": "offline",
        "model": "offline",
        "rules": rules_used,
        "refusals": [],
        "notes": notes,
    }
    return panels, parse


# ---------------------------------------------------------------------------
# Hosted profiles: model proposals, governed validation
# ---------------------------------------------------------------------------

_PROPOSAL_PROMPT = """You assemble dashboards for a fertilizer \
market-intelligence system. Answer with ONLY a JSON array of panel \
proposals, no prose. Each proposal is an object {"kind": ..., \
"scope": {...}}. Governed panel kinds and their scope keys: \
demand_estimate{district_id, product, crop_year, season}; \
season_outlook{crop_year, season}; price_watch{series_kind, item}; \
watch_board{}; supply_position{product, month}; \
supply_gap{product, crop_year, season}; policy_events{product?}; \
market_share{district_id, product, crop_year, season}; \
share_movement{district_id, product, season}; \
field_signals{district_id, product, crop_year, season}. Products: \
UREA, DAP, NPK_10_26_26, MOP, GLYPHOSATE, CHLORPYRIFOS. Seasons: \
kharif, rabi. District ids look like DST-LUD. Never invent a panel \
kind outside this list.

Question: {question}"""


def _validate_proposal(store, proposal: PanelProposal,
                       panel_no: int) -> tuple[SpecPanel | None, str | None]:
    """A model proposal enters a spec only if it fits the
    governed schema exactly: kind in the vocabulary, scope
    keys exactly the kind's stated set, every entity real.
    Returns (panel, None) or (None, refusal reason)."""
    kind = proposal.kind
    if kind not in pack.PANEL_KINDS or kind == "gap":
        return None, f"panel kind {kind!r} is not in the governed vocabulary"
    scope = dict(proposal.scope)
    required = set(pack.PANEL_SCOPE[kind])
    optional = set(pack.OPTIONAL_SCOPE.get(kind, ()))
    missing = required - set(scope)
    extra = set(scope) - required - optional
    if missing:
        return None, f"{kind} scope is missing {sorted(missing)}"
    if extra:
        return None, f"{kind} scope carries ungoverned keys {sorted(extra)}"
    district_ids = {d["district_id"] for d in store.list_districts()}
    if "district_id" in scope and scope["district_id"] not in district_ids:
        return None, f"district {scope['district_id']!r} is not tracked"
    if "product" in scope and scope["product"] not in PRODUCTS:
        return None, f"product {scope['product']!r} is not tracked"
    if "season" in scope and scope["season"] not in ("kharif", "rabi"):
        return None, f"season {scope['season']!r} is not a tracked season"
    if "crop_year" in scope and scope["crop_year"] not in CROP_YEARS:
        return None, f"crop year {scope['crop_year']!r} is not tracked"
    if kind == "price_watch":
        items = PRODUCTS if scope["series_kind"] == "product" else FEEDSTOCKS
        if scope["series_kind"] not in ("product", "feedstock"):
            return None, "price_watch series_kind must be product or feedstock"
        if scope["item"] not in items:
            return None, f"price item {scope['item']!r} is not tracked"
    panel = SpecPanel(
        panel_no=panel_no, kind=kind,
        title=proposal.title or _panel_title(store, kind, scope),
        scope=scope,
        origin={"via": "model", "rule": f"model_proposal:{panel_no}"},
    )
    return panel, None


def parse_question_model(store, port, question: str) -> tuple[list[SpecPanel], dict]:
    """A hosted profile's parse: the port is asked for panel
    proposals as JSON; each proposal is validated against
    the governed schema. A refusal is recorded on the spec
    AND rendered as a gap panel naming the refusal. A reply
    that is not a JSON array at all refuses the question —
    fail-closed, no fallback to guessing."""
    # .replace, not .format: the prompt states literal JSON
    # braces for the proposal shape.
    reply = port.complete(_PROPOSAL_PROMPT.replace("{question}", question))
    text = reply.text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?|\n?```$", "", text).strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        raise QuestionRefused(
            "the model profile returned no parseable panel proposals — "
            "the question was refused rather than guessed at")
    if not isinstance(data, list) or not data:
        raise QuestionRefused(
            "the model profile returned no panel proposals — "
            "the question was refused rather than guessed at")
    panels: list[SpecPanel] = []
    refusals: list[dict] = []
    for item in data:
        panel_no = len(panels) + 1
        try:
            proposal = PanelProposal.model_validate(item)
        except Exception as exc:  # malformed proposal shape
            reason = f"proposal is not a governed panel object: {exc}"
            refusals.append({"proposal": item, "reason": reason})
            panels.append(_gap_panel(
                panel_no, str(item)[:72],
                pack.GAP_REFUSED_PROPOSAL.format(reason=reason),
                "model:refused_proposal"))
            continue
        panel, reason = _validate_proposal(store, proposal, panel_no)
        if panel is None:
            refusals.append({"proposal": proposal.model_dump(),
                             "reason": reason})
            panels.append(_gap_panel(
                panel_no, proposal.title or proposal.kind,
                pack.GAP_REFUSED_PROPOSAL.format(reason=reason),
                "model:refused_proposal"))
        else:
            panels.append(panel)
    parse = {
        "profile": getattr(port, "profile", "hosted"),
        "model": getattr(port, "model", "unknown"),
        "rules": [p.origin["rule"] for p in panels],
        "refusals": refusals,
        "notes": [],
    }
    return panels, parse


# ---------------------------------------------------------------------------
# Role defaults, stated in the pack, built through the same machinery
# ---------------------------------------------------------------------------


def role_default_panels(store, role: str) -> tuple[str, list[SpecPanel]]:
    """(question label, panels) for a role's default
    dashboard, from the pack's stated data. An unknown role
    is refused — roles are pack data, not code branches."""
    if role not in pack.ROLE_DEFAULTS:
        raise ValueError(
            f"unknown role: {role} (stated roles: {', '.join(pack.ROLES)})")
    label, entries = pack.ROLE_DEFAULTS[role]
    panels = []
    for index, (kind, scope_template) in enumerate(entries, start=1):
        scope = {
            key: (CROP_YEARS[-1] if value == "current" else value)
            for key, value in scope_template.items()
        }
        panels.append(SpecPanel(
            panel_no=index, kind=kind,
            title=_panel_title(store, kind, scope), scope=scope,
            origin={"via": "role_default", "rule": f"role_default:{role}"},
        ))
    return label, panels


def build_spec(question: str, asked_by: str, as_of: str,
               panels: list[SpecPanel], parse: dict,
               role: str | None = None, name: str | None = None,
               saved_by: str | None = None) -> DashboardSpec:
    fingerprint = _fingerprint({
        "question": question, "role": role, "name": name, "as_of": as_of,
        "panels": [p.model_dump() for p in panels],
        "rules_version": pack.RULES_VERSION,
    })
    return DashboardSpec(
        spec_id=f"SPEC-{fingerprint[:10]}", fingerprint=fingerprint,
        rules_version=pack.RULES_VERSION, question=question,
        asked_by=asked_by, role=role, name=name, saved_by=saved_by,
        as_of=as_of, parse=parse, panels=panels,
    )


# ---------------------------------------------------------------------------
# Resolution: a spec panel -> its current head artefacts
# ---------------------------------------------------------------------------


def _band_of(alerts: list[dict]) -> str:
    """A series' band, derived from its pinned open alerts
    exactly as the watch derives it — the highest alert band
    present, or "none". Pure from the artefacts, so assembly
    and verification derive the same band."""
    band = "none"
    for alert in alerts:
        if alert_pack.BAND_RANK[alert["band"]] > alert_pack.BAND_RANK[band]:
            band = alert["band"]
    return band


def _fig(label: str, value: Any, unit: str, artefact_id: str,
         source_as_of: str, badges: list[str] | None = None) -> dict:
    return {
        "label": label, "value": value, "unit": unit,
        "artefact_id": artefact_id, "source_as_of": source_as_of,
        "badges": list(badges or []),
    }


def resolve_panel(service, panel: dict, as_of: str) -> dict:
    """Resolve one spec panel to the CURRENT head artefacts
    of its family (compute-or-return through the service)
    and extract its figures and rows. Returns
    {artefact_ids, figures, rows, notes}."""
    store = service.store
    kind = panel["kind"]
    scope = panel["scope"]
    if kind == "gap":
        return {"artefact_ids": [], "figures": [], "rows": [],
                "notes": [scope["needed_data"]]}
    artefacts = _resolve_artefacts(service, kind, scope, as_of)
    figures, rows, notes = extract_panel(store, kind, scope, artefacts)
    return {"artefact_ids": _artefact_ids(kind, scope, artefacts),
            "figures": figures, "rows": rows, "notes": notes}


def _resolve_artefacts(service, kind: str, scope: dict, as_of: str) -> dict:
    store = service.store
    if kind == "demand_estimate":
        estimate = service.estimate_demand(
            scope["district_id"], scope["product"], scope["crop_year"],
            scope["season"], as_of)
        return {"estimate": estimate}
    if kind == "season_outlook":
        return {"outlook": service.demand_outlook(
            scope["crop_year"], scope["season"], as_of)}
    if kind == "price_watch":
        service.run_price_watch(as_of)
        movements = store.list_movements(scope["series_kind"], scope["item"])
        alerts = [a for a in service.list_alerts(
            scope["series_kind"], scope["item"]) if a["state"] != "closed"]
        points = store.price_points(scope["series_kind"], scope["item"])
        return {"movement": movements[-1] if movements else None,
                "alerts": alerts,
                "unit": points[0]["unit"] if points else ""}
    if kind == "watch_board":
        service.run_price_watch(as_of)
        series = sorted({(p["series_kind"], p["item"])
                         for p in store.price_points()})
        entries = []
        for series_kind, item in series:
            rows = store.list_movements(series_kind, item)
            if not rows:
                continue
            alerts = [a for a in service.list_alerts(series_kind, item)
                      if a["state"] != "closed"]
            entries.append({"movement": rows[-1], "alerts": alerts})
        return {"entries": entries}
    if kind == "supply_position":
        return {"position": service.supply_position(
            scope["product"], scope["month"], as_of)}
    if kind == "supply_gap":
        return {"gap": service.supply_gap(
            scope["product"], scope["crop_year"], scope["season"], as_of)}
    if kind == "policy_events":
        service.register_policy_events(as_of)
        events = service.list_policy_events(hypothetical=False)
        if scope.get("product"):
            events = [e for e in events
                      if scope["product"] in e.get("products", [])]
        return {"events": events}
    if kind == "market_share":
        return {"share": service.market_share(
            scope["district_id"], scope["product"], scope["crop_year"],
            scope["season"], as_of)}
    if kind == "share_movement":
        return {"movement": service.share_movement(
            scope["district_id"], scope["product"], scope["season"], as_of)}
    if kind == "field_signals":
        return {"assessment": service.field_signal_assessment(
            scope["district_id"], scope["product"], scope["crop_year"],
            scope["season"], as_of)}
    raise ValueError(f"no resolver for panel kind: {kind}")


def _artefact_ids(kind: str, scope: dict, artefacts: dict) -> list[str]:
    if kind == "demand_estimate":
        return [artefacts["estimate"]["estimate_id"]]
    if kind == "season_outlook":
        return [artefacts["outlook"]["outlook_id"]]
    if kind == "price_watch":
        ids = []
        if artefacts["movement"] is not None:
            ids.append(artefacts["movement"]["movement_id"])
        ids.extend(a["alert_id"] for a in artefacts["alerts"])
        return ids
    if kind == "watch_board":
        ids = []
        for entry in artefacts["entries"]:
            ids.append(entry["movement"]["movement_id"])
            ids.extend(a["alert_id"] for a in entry["alerts"])
        return ids
    if kind == "supply_position":
        position = artefacts["position"]
        return [f"supply-position:{position['product']}:{position['month']}"]
    if kind == "supply_gap":
        return [artefacts["gap"]["gap_id"]]
    if kind == "policy_events":
        return [e["registry_id"] for e in artefacts["events"]]
    if kind == "market_share":
        return [artefacts["share"]["share_id"]]
    if kind == "share_movement":
        return [artefacts["movement"]["movement_id"]]
    if kind == "field_signals":
        return [artefacts["assessment"]["assessment_id"]]
    return []


def _fetch_artefacts(store, kind: str, scope: dict,
                     ids: list[str]) -> tuple[dict | None, list[str]]:
    """The verifier's side of resolution: fetch the pinned
    artefacts BY ID from the store. Returns (artefacts,
    problems) — a missing artefact is a named problem, never
    a silent substitution of the current head."""
    problems: list[str] = []

    def need(value, what):
        if value is None:
            problems.append(f"{what} not found in the store")
        return value

    if kind == "demand_estimate":
        estimate = need(store.get_estimate(ids[0]), f"estimate {ids[0]}")
        if estimate is None:
            return None, problems
        estimate = {**estimate,
                    "contributions": store.estimate_contributions(ids[0])}
        return {"estimate": estimate}, problems
    if kind == "season_outlook":
        outlook = need(store.get_outlook(ids[0]), f"outlook {ids[0]}")
        return ({"outlook": outlook}, problems) if outlook else (None, problems)
    if kind == "price_watch":
        movement = need(store.get_movement(ids[0]), f"movement {ids[0]}")
        alerts = [a for a in (store.get_alert(i) for i in ids[1:])
                  if a is not None]
        points = store.price_points(scope["series_kind"], scope["item"])
        return {"movement": movement, "alerts": alerts,
                "unit": points[0]["unit"] if points else ""}, problems
    if kind == "watch_board":
        movements, alerts = [], []
        for artefact_id in ids:
            if artefact_id.startswith("MOV-"):
                movements.append(store.get_movement(artefact_id))
            else:
                alerts.append(store.get_alert(artefact_id))
        if any(m is None for m in movements) or \
                any(a is None for a in alerts):
            problems.append("a watch-board artefact is missing from the store")
            return None, problems
        by_series: dict[tuple, list] = {}
        for alert in alerts:
            by_series.setdefault(
                (alert["series_kind"], alert["item"]), []).append(alert)
        entries = [{
            "movement": movement,
            "alerts": by_series.get(
                (movement["series_kind"], movement["item"]), []),
        } for movement in sorted(
            movements, key=lambda m: (m["series_kind"], m["item"]))]
        return {"entries": entries}, problems
    if kind == "supply_position":
        position = store.get_position(scope["product"], scope["month"])
        if position is None:
            problems.append(
                f"supply position {scope['product']} {scope['month']} "
                "not found in the store")
            return None, problems
        return {"position": position}, problems
    if kind == "supply_gap":
        gap = need(store.get_gap(ids[0]), f"supply gap {ids[0]}")
        return ({"gap": gap}, problems) if gap else (None, problems)
    if kind == "policy_events":
        events = []
        for registry_id in ids:
            event = store.get_policy_registration(registry_id)
            if event is None:
                problems.append(
                    f"policy registration {registry_id} not found in "
                    "the store")
            else:
                events.append(event)
        if problems:
            return None, problems
        events.sort(key=lambda e: e["event_id"])
        return {"events": events}, problems
    if kind == "market_share":
        share = need(store.get_share(ids[0]), f"market share {ids[0]}")
        return ({"share": share}, problems) if share else (None, problems)
    if kind == "share_movement":
        movement = need(store.get_share_movement(ids[0]),
                        f"share movement {ids[0]}")
        return ({"movement": movement}, problems) if movement else (None, problems)
    if kind == "field_signals":
        assessment = need(store.get_field_assessment(ids[0]),
                          f"field assessment {ids[0]}")
        return ({"assessment": assessment}, problems) \
            if assessment else (None, problems)
    return None, [f"no verifier fetch for panel kind: {kind}"]


# ---------------------------------------------------------------------------
# Figure extraction — one path, used by assembly AND verification
# ---------------------------------------------------------------------------


def extract_panel(store, kind: str, scope: dict,
                  artefacts: dict) -> tuple[list[dict], list[dict], list[str]]:
    """(figures, rows, notes) for a panel from its artefacts.
    Every figure names its artefact and that artefact's
    as-of; badges carry the R6 staleness discipline and the
    R7 review states where they apply."""
    if kind == "demand_estimate":
        est = artefacts["estimate"]
        aid, as_of = est["estimate_id"], est["as_of"]
        badges = ["partial"] if est["status"] != "complete" else []
        figures = [_fig("Base demand (area × application rates)",
                        est["base_tonnes"], "t", aid, as_of, badges)]
        for line in est["contributions"]:
            figures.append(_fig(f"Driver: {line['driver']}",
                                line["delta_tonnes"], "t", aid, as_of,
                                badges))
        figures.append(_fig("Estimated demand", est["total_tonnes"], "t",
                            aid, as_of, badges))
        notes = []
        if est["status"] != "complete":
            notes.append(
                "this estimate is partial — missing drivers: "
                + ", ".join(est["missing_drivers"])
                + ". The degraded state is stated, never suppressed.")
        rows = [{
            "driver": line["driver"], "factor": line["factor"],
            "delta_tonnes": line["delta_tonnes"],
            "value_after_tonnes": line["value_after_tonnes"],
            "status": line["status"],
        } for line in est["contributions"]]
        return figures, rows, notes

    if kind == "season_outlook":
        outlook = artefacts["outlook"]
        aid, as_of = outlook["outlook_id"], outlook["as_of"]
        figures = [
            _fig("Total estimated demand", outlook["total_tonnes"], "t",
                 aid, as_of),
            _fig("Estimates in the grid", outlook["estimate_count"],
                 "count", aid, as_of),
            _fig("Partial estimates", outlook["partial_count"], "count",
                 aid, as_of,
                 ["partial inputs present"] if outlook["partial_count"] else []),
        ]
        rollups = [{"product": product, "total_tonnes": total}
                   for product, total in
                   sorted(outlook["product_rollups"].items())]
        for rollup in rollups:
            figures.append(_fig(f"{rollup['product']} — season total",
                                rollup["total_tonnes"], "t", aid, as_of))
        return figures, rollups, []

    if kind == "price_watch":
        movement, alerts = artefacts["movement"], artefacts["alerts"]
        if movement is None:
            return [], [], ["no price movements recorded for this series"]
        aid, as_of = movement["movement_id"], movement["as_of"]
        band = _band_of(alerts)
        figures = [_fig("Latest price", movement["price"],
                        artefacts.get("unit", ""), aid, as_of,
                        [f"band: {band}"] if band != "none" else [])]
        if movement["mom_pct"] is not None:
            figures.append(_fig("Month-on-month change",
                                movement["mom_pct"], "%", aid, as_of))
        if movement["baseline_pct"] is not None:
            figures.append(_fig("Change vs pre-shock baseline",
                                movement["baseline_pct"], "%", aid, as_of))
        figures.append(_fig("Open alerts", len(alerts), "count", aid, as_of))
        rows = [{"fact": "Series",
                 "value": f"{movement['series_kind']}/{movement['item']}"},
                {"fact": "Latest month", "value": movement["month"]},
                {"fact": "Band", "value": band}]
        rows += [{"fact": "Open alert", "value": a["rule_id"]}
                 for a in alerts]
        return figures, rows, []

    if kind == "watch_board":
        figures, rows = [], []
        for entry in artefacts["entries"]:
            movement, alerts = entry["movement"], entry["alerts"]
            band = _band_of(alerts)
            if movement["mom_pct"] is not None:
                figures.append(_fig(
                    f"{movement['item']} — month-on-month change",
                    movement["mom_pct"], "%", movement["movement_id"],
                    movement["as_of"],
                    [f"band: {band}"] if band != "none" else []))
            rows.append({
                "series": f"{movement['series_kind']}/{movement['item']}",
                "month": movement["month"], "price": movement["price"],
                "mom_pct": movement["mom_pct"], "band": band,
                "open_alerts": len(alerts),
            })
        return figures, rows, []

    if kind == "supply_position":
        position = artefacts["position"]
        aid = f"supply-position:{position['product']}:{position['month']}"
        as_of = position["as_of"]
        figures = [
            _fig("Opening stock", position["opening_stock_tonnes"], "t", aid, as_of),
            _fig("Production (actual)", position["production_actual_tonnes"], "t", aid, as_of),
            _fig("Imports", position["imports_tonnes"], "t", aid, as_of),
            _fig("Consumption", position["consumption_tonnes"], "t", aid, as_of),
            _fig("Closing stock", position["closing_stock_tonnes"], "t", aid, as_of),
        ]
        rows = [{"fact": "Production plan",
                 "value": position["production_plan_tonnes"]},
                {"fact": "Source", "value": position["source"]}]
        return figures, rows, []

    if kind == "supply_gap":
        gap = artefacts["gap"]
        aid, as_of = gap["gap_id"], gap["as_of"]
        figures = [
            _fig("Season demand", gap["demand_tonnes"], "t", aid, as_of),
            _fig("Available supply", gap["available_tonnes"], "t", aid, as_of),
            _fig("Gap", gap["gap_tonnes"], "t", aid, as_of),
            _fig("Gap as share of demand", gap["gap_pct_of_demand"], "%",
                 aid, as_of, [f"band: {gap['band']}"]),
        ]
        if gap.get("programme_cover_pct") is not None:
            figures.append(_fig("Import programme cover",
                                gap["programme_cover_pct"], "%", aid, as_of))
        rows = [
            {"fact": "Due imports inside the window",
             "value": gap["due_imports_tonnes"]},
            {"fact": "Credited imports", "value": gap["credited_imports_tonnes"]},
            {"fact": "Slipped imports", "value": gap["slipped_tonnes"]},
            {"fact": "Band basis", "value": gap["band_basis"]},
        ]
        return figures, rows, []

    if kind == "policy_events":
        events = artefacts["events"]
        figures = []
        if events:
            figures.append(_fig(
                "Policy events in scope", len(events), "count",
                events[0]["registry_id"], events[0]["as_of"]))
        rows = [{
            "event_id": e["event_id"], "registry_id": e["registry_id"],
            "title": e["title"], "event_class": e["event_class"],
            "direction": e["stated_effect"]["direction"],
            "window": f"{e['effective_from_month']} → "
                      f"{e['effective_to_month']}",
            "source": e["source"], "as_of": e["as_of"],
        } for e in events]
        notes = [] if events else [
            "no recorded policy events in the registry for this scope"]
        return figures, rows, notes

    if kind == "market_share":
        share = artefacts["share"]
        aid, as_of = share["share_id"], share["as_of"]
        reading = share.get("headline")
        stale_badges: list[str] = []
        notes: list[str] = []
        if reading is not None:
            if share.get("headline_note"):
                stale_badges = ["stale observations excluded"]
                notes.append(share["headline_note"])
        elif share["status"] == "not_current" and share.get("full_season"):
            reading = share["full_season"]
            stale_badges = ["stale"]
            notes.append(
                "no current reading at this date — the figures below are "
                "the full-season reading and every one is badged stale; "
                "they are never presented as current")
        if reading is None:
            notes.append(
                f"share status: {share['status']} — no reading can be "
                "rendered for this scope and date")
            return [], [], notes
        figures = [
            _fig("District demand", reading["demand_tonnes"], "t",
                 aid, as_of, stale_badges),
            _fig("Observed market", reading["observed_market_tonnes"], "t",
                 aid, as_of, stale_badges),
        ]
        sellers = [reading["kaveri"], *reading["competitors"]]
        for seller in sellers:
            figures.append(_fig(
                f"{seller['seller']} — share of observed market",
                seller["share_of_observed_market_pct"], "%",
                aid, as_of, stale_badges))
            figures.append(_fig(
                f"{seller['seller']} — volume",
                seller["volume_tonnes"], "t", aid, as_of, stale_badges))
        rows = [{
            "seller": s["seller"], "volume_tonnes": s["volume_tonnes"],
            "share_of_observed_market_pct": s["share_of_observed_market_pct"],
            "share_of_total_demand_pct": s["share_of_total_demand_pct"],
        } for s in sellers]
        rows.append({"fact": "Reading basis", "value": reading["basis"]})
        rows.append({"fact": "Kaveri basis", "value": share["kaveri_basis"]})
        return figures, rows, notes

    if kind == "share_movement":
        movement = artefacts["movement"]
        aid, as_of = movement["movement_id"], movement["as_of"]
        figures = []
        for row in movement["rows"]:
            figures.append(_fig(f"{row['seller']} — share change",
                                row["change_pp"], "pp", aid, as_of))
        biggest = movement.get("biggest_mover") or {}
        if biggest.get("change_pp") is not None:
            figures.append(_fig("Biggest mover — share change",
                                biggest["change_pp"], "pp", aid, as_of,
                                [f"biggest mover: {biggest['seller']}"]))
        rows = [dict(r) for r in movement["rows"]]
        rows.append({"fact": "Compared",
                     "value": f"{movement['from_crop_year']} → "
                              f"{movement['to_crop_year']}"})
        return figures, rows, []

    if kind == "field_signals":
        assessment = artefacts["assessment"]
        aid, as_of = assessment["assessment_id"], assessment["as_of"]
        capped = bool(assessment["capped_report_ids"])
        figures = [
            _fig("Estimate before field signals", assessment["base_tonnes"],
                 "t", aid, as_of),
            _fig("Field-signal adjustment", assessment["adjustment_pct"],
                 "%", aid, as_of, ["includes capped reports"] if capped else []),
            _fig("Adjusted estimate", assessment["adjusted_tonnes"], "t",
                 aid, as_of),
        ]
        for line in assessment["lines"]:
            badges = [f"review: {line['review_state']}",
                      f"reporter: {line['reporter']}"]
            if line["capped"]:
                badges.append("capped")
            figures.append(_fig(
                f"Signal {line['report_id']} — applied adjustment",
                line["applied_pct"], "%", aid, as_of, badges))
        rows = [dict(line) for line in assessment["lines"]]
        rows += [{"fact": "Excluded report", "value": e["report_id"],
                  "reason": e["reason"]} for e in assessment["excluded"]]
        notes = []
        if capped:
            notes.append(
                "unverified reports are capped by the field pack — the "
                "adjustment above is the capped figure, and the cap is "
                "badged, never hidden")
        return figures, rows, notes

    raise ValueError(f"no extractor for panel kind: {kind}")


# ---------------------------------------------------------------------------
# Verification — the R2 figure discipline at dashboard scale
# ---------------------------------------------------------------------------


def verify_panels(store, panels: list[dict]) -> list[str]:
    """Re-perform every figure on every panel against its
    pinned artefact. Returns problem strings naming the
    panel and the figure; empty means clean. Used as the
    pre-store gate at assembly and by verify_assembly."""
    problems: list[str] = []
    for panel in panels:
        no = panel["panel_no"]
        if panel["kind"] == "gap":
            if panel["figures"]:
                problems.append(
                    f"panel {no}: a gap panel carries figures — "
                    "gaps state needed data, they never invent numbers")
            continue
        ids = panel["artefact_ids"]
        if not ids:
            if panel["figures"]:
                problems.append(
                    f"panel {no}: figures with no artefact binding")
            elif panel["kind"] not in ("policy_events",):
                problems.append(f"panel {no}: no artefact binding")
            continue
        artefacts, fetch_problems = _fetch_artefacts(
            store, panel["kind"], panel["scope"], ids)
        problems.extend(f"panel {no}: {p}" for p in fetch_problems)
        if artefacts is None:
            continue
        figures, _rows, _notes = extract_panel(
            store, panel["kind"], panel["scope"], artefacts)
        if figures != panel["figures"]:
            stored = {f["label"]: f for f in panel["figures"]}
            fresh = {f["label"]: f for f in figures}
            for label in sorted(set(stored) | set(fresh)):
                if stored.get(label) != fresh.get(label):
                    problems.append(
                        f"panel {no}: figure {label!r} does not "
                        f"re-perform — stored {stored.get(label)} vs "
                        f"artefact {fresh.get(label)}")
            if len(stored) != len(panel["figures"]) or \
                    len(fresh) != len(figures):
                problems.append(
                    f"panel {no}: duplicate figure labels make the "
                    "panel unverifiable")
        for figure in panel["figures"]:
            if not figure.get("artefact_id"):
                problems.append(
                    f"panel {no}: figure {figure.get('label')!r} has "
                    "no artefact lineage")
            elif figure["artefact_id"] not in ids:
                problems.append(
                    f"panel {no}: figure {figure.get('label')!r} names "
                    f"artefact {figure['artefact_id']} outside the "
                    "panel's binding")
            if not figure.get("source_as_of"):
                problems.append(
                    f"panel {no}: figure {figure.get('label')!r} has "
                    "no source as-of")
    return problems


def verify_assembly(store, assembly: dict) -> list[str]:
    """Verify a stored assembly: every figure re-performs
    against its pinned artefact, gap panels carry no
    figures, and the stored HTML is byte-identical to a
    fresh render of the stored content."""
    problems = verify_panels(store, assembly["panels"])
    spec = store.get_dashboard_spec(assembly["spec_id"])
    if spec is None:
        problems.append(f"spec {assembly['spec_id']} not found")
        return problems
    rendered = render_dashboard(spec, assembly["panels"],
                                assembly["assembled_on"], assembly["diff"])
    if rendered != assembly["html"]:
        problems.append(
            "the stored HTML does not match a fresh render of the "
            "stored panels — the page was altered after assembly")
    return problems


# ---------------------------------------------------------------------------
# Assembly: supersession, diff, render
# ---------------------------------------------------------------------------


def build_panels(service, spec: dict, assembled_on: str) -> list[dict]:
    """Resolve every spec panel to its current head and note
    supersessions against the spec-time binding."""
    panels: list[dict] = []
    for spec_panel in spec["panels"]:
        resolved = resolve_panel(service, spec_panel, assembled_on)
        notes = list(resolved["notes"])
        binding = spec_panel.get("binding_artefact_ids") or []
        current = resolved["artefact_ids"]
        if binding and current != binding:
            notes.append(
                "superseded since the question was asked: "
                + ", ".join(binding) + " → " + ", ".join(current)
                + " — figures render from the current head")
        panels.append({
            "panel_no": spec_panel["panel_no"],
            "kind": spec_panel["kind"],
            "title": spec_panel["title"],
            "scope": spec_panel["scope"],
            "origin": spec_panel["origin"],
            "artefact_ids": current,
            "figures": resolved["figures"],
            "rows": resolved["rows"],
            "notes": notes,
        })
    return panels


def compute_diff(previous: dict | None, panels: list[dict]) -> list[dict]:
    """The stated difference between this assembly and the
    previous assembly of the same spec: figures whose value
    changed, and panels whose artefact binding superseded."""
    if previous is None:
        return []
    entries: list[dict] = []
    previous_panels = {p["panel_no"]: p for p in previous["panels"]}
    for panel in panels:
        before_panel = previous_panels.get(panel["panel_no"])
        if before_panel is None:
            continue
        if before_panel["artefact_ids"] != panel["artefact_ids"]:
            entries.append({
                "kind": "artefacts_superseded",
                "panel_no": panel["panel_no"],
                "panel_title": panel["title"],
                "before": before_panel["artefact_ids"],
                "after": panel["artefact_ids"],
            })
        before_figures = {f["label"]: f["value"]
                          for f in before_panel["figures"]}
        for figure in panel["figures"]:
            label = figure["label"]
            if label in before_figures and \
                    before_figures[label] != figure["value"]:
                entries.append({
                    "kind": "figure_changed",
                    "panel_no": panel["panel_no"],
                    "panel_title": panel["title"],
                    "label": label,
                    "before": before_figures[label],
                    "after": figure["value"],
                })
    return entries


def assemble(service, spec: dict, assembled_on: str) -> DashboardAssembly:
    """Assemble a dashboard from a spec. The pre-store gate
    re-performs every figure; one mismatch refuses the
    whole dashboard and nothing is stored by this function
    (the service stores only what assemble returns)."""
    store = service.store
    panels = build_panels(service, spec, assembled_on)
    problems = verify_panels(store, panels)
    if problems:
        raise DashboardRefused(
            "dashboard refused — a figure did not re-perform against "
            "its artefact: " + "; ".join(problems))
    previous = head_of(store.dashboard_assemblies(spec["spec_id"]),
                       "assembly_id")
    diff = compute_diff(previous, panels)
    fingerprint = _fingerprint({
        "spec_id": spec["spec_id"], "panels": panels, "diff": diff,
        "assembled_on": assembled_on, "rules_version": pack.RULES_VERSION,
    })
    rendered = render_dashboard(spec, panels, assembled_on, diff)
    return DashboardAssembly(
        assembly_id=f"DASH-{fingerprint[:10]}", fingerprint=fingerprint,
        spec_id=spec["spec_id"],
        supersedes=previous["assembly_id"] if previous else None,
        assembled_on=assembled_on, rules_version=pack.RULES_VERSION,
        panels=panels, diff=diff, html=rendered,
    )


# ---------------------------------------------------------------------------
# Rendering — one static HTML file, portfolio console conventions
# ---------------------------------------------------------------------------

_CSS = """
:root { --ink: #0A0A0A; --muted: #5D6472; --line: #E4E4EC;
  --panel: #F7F7FA; --indigo: #4F46E5; --indigo-dark: #3730A3;
  --lavender: #EEF0FF; --warn: #B54708; --bad: #B42318; }
* { box-sizing: border-box; }
body { margin: 0; background: #FFFFFF; color: var(--ink);
  font-family: "Plus Jakarta Sans", system-ui, sans-serif; }
header, main, footer { max-width: 1080px; margin: 0 auto; padding: 0 20px; }
header { padding-top: 28px; }
h1 { font-size: 24px; margin: 8px 0 4px; }
h2 { font-size: 17px; margin: 0 0 10px; }
.muted { color: var(--muted); }
.panel { border: 1px solid var(--line); border-radius: 12px;
  padding: 18px; margin: 18px 0; background: #FFFFFF; }
.panel.gap { background: var(--panel); border-style: dashed; }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th, td { text-align: left; padding: 6px 8px;
  border-bottom: 1px solid var(--line); vertical-align: top; }
th { color: var(--muted); font-weight: 600; }
.badge { display: inline-block; background: var(--lavender);
  color: var(--indigo-dark); border-radius: 999px; padding: 1px 8px;
  font-size: 12px; margin-right: 4px; }
.badge.stale { background: #FEF3E2; color: var(--warn); }
.note { color: var(--muted); font-size: 13px; margin-top: 8px; }
.lineage { color: var(--muted); font-size: 12px; }
footer { display: flex; justify-content: space-between; gap: 24px;
  border-top: 1px solid var(--line); padding-top: 18px;
  padding-bottom: 28px; margin-top: 28px; flex-wrap: wrap; }
.footer-brand { display: flex; align-items: center; gap: 8px; }
.footer-brand img { width: 28px; height: 28px; }
footer a { color: var(--indigo); text-decoration: none;
  margin-left: 16px; }
"""


def _fmt(value: Any) -> str:
    if isinstance(value, (dict, list)):
        # Canonical form: the store's payload round-trip
        # sorts keys, so a nested value must render from its
        # sorted JSON, never from an insertion-ordered repr.
        return json.dumps(value, sort_keys=True, default=str)
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if value == int(value) and abs(value) < 1e12:
            return f"{int(value):,}"
        return f"{value:,.4f}".rstrip("0").rstrip(".")
    if value is None:
        return "—"
    return str(value)


def _esc(value: Any) -> str:
    return html.escape(_fmt(value) if not isinstance(value, str)
                       else value)


def _render_panel(panel: dict) -> str:
    out = [f'<section class="panel{" gap" if panel["kind"] == "gap" else ""}">']
    out.append(f"<h2>{_esc(panel['title'])}</h2>")
    if panel["kind"] == "gap":
        out.append(
            '<p class="note">This part of the question cannot be '
            "answered from the data this system holds. What would be "
            "needed:</p>")
        for note in panel["notes"]:
            out.append(f'<p class="note">{_esc(note)}</p>')
        out.append("</section>")
        return "\n".join(out)
    if panel["figures"]:
        out.append("<table><thead><tr><th>Figure</th><th>Value</th>"
                   "<th>Source artefact</th><th></th></tr></thead><tbody>")
        for figure in panel["figures"]:
            badges = "".join(
                f'<span class="badge{" stale" if b == "stale" else ""}">'
                f"{_esc(b)}</span>" for b in figure["badges"])
            out.append(
                f"<tr><td>{_esc(figure['label'])}</td>"
                f"<td>{_esc(_fmt(figure['value']))} "
                f"{_esc(figure['unit'])}</td>"
                f'<td class="lineage">{_esc(figure["artefact_id"])}'
                f" · as of {_esc(figure['source_as_of'])}</td>"
                f"<td>{badges}</td></tr>")
        out.append("</tbody></table>")
    if panel["rows"]:
        # The sorted union of every row's keys: rows in one
        # panel can be heterogeneous (seller rows beside fact
        # rows), and the store serializes payloads with sorted
        # keys, so a re-render of the stored assembly must use
        # the same canonical order for the byte comparison to
        # mean anything.
        keys = sorted({k for row in panel["rows"] for k in row})
        out.append("<table><thead><tr>"
                   + "".join(f"<th>{_esc(k)}</th>" for k in keys)
                   + "</tr></thead><tbody>")
        for row in panel["rows"]:
            out.append("<tr>" + "".join(
                f"<td>{_esc(row.get(k))}</td>" for k in keys) + "</tr>")
        out.append("</tbody></table>")
    for note in panel["notes"]:
        out.append(f'<p class="note">{_esc(note)}</p>')
    out.append(
        f'<p class="lineage">Panel source: '
        f'{_esc(", ".join(panel["artefact_ids"]) or "—")}</p>')
    out.append("</section>")
    return "\n".join(out)


def render_dashboard(spec: dict, panels: list[dict], assembled_on: str,
                     diff: list[dict]) -> str:
    """A pure function of the stored content — the verifier
    re-renders and compares byte-for-byte."""
    title = spec.get("name") or "Dashboard"
    out = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        f"<title>{_esc(title)} — Kaveri Agro Inputs</title>",
        f"<style>{_CSS}</style>",
        "</head>",
        "<body>",
        "<header>",
        '<p class="muted">Kaveri Agro Inputs — market intelligence</p>',
        f"<h1>{_esc(title)}</h1>",
        f'<p class="muted">Question: {_esc(spec["question"])}</p>',
        f'<p class="muted">Asked by {_esc(spec["asked_by"])} · '
        f'spec as of {_esc(spec["as_of"])} · assembled '
        f"{_esc(assembled_on)} · every figure below names the "
        "artefact it came from; a part the data cannot answer is "
        "shown as a gap, never filled in.</p>",
        "</header>",
        "<main>",
    ]
    for panel in panels:
        out.append(_render_panel(panel))
    if diff:
        out.append('<section class="panel"><h2>What changed since '
                   "the previous assembly</h2><table><tbody>")
        for entry in diff:
            if entry["kind"] == "figure_changed":
                text = (f"Panel {entry['panel_no']} "
                        f"({entry['panel_title']}): {entry['label']} "
                        f"changed from {_fmt(entry['before'])} to "
                        f"{_fmt(entry['after'])}")
            else:
                text = (f"Panel {entry['panel_no']} "
                        f"({entry['panel_title']}): source artefacts "
                        f"superseded — {', '.join(entry['before'])} → "
                        f"{', '.join(entry['after'])}")
            out.append(f"<tr><td>{_esc(text)}</td></tr>")
        out.append("</tbody></table></section>")
    out += [
        "</main>",
        "<footer>",
        "<div>",
        '<div class="footer-brand">'
        '<img src="https://trida.ai/logos-rounded/trida-rounded.png" '
        'alt="Trida AI"><strong>Trida AI</strong></div>',
        '<p class="muted">Figures on this page are artefact figures '
        "re-performed by the assembler before serving. The dashboard "
        "selects and renders; it does not compute, and it never "
        "invents a figure for a part the data cannot answer.</p>",
        "</div>",
        '<div><a href="https://trida.ai/">Visit Trida AI →</a>'
        '<a href="https://github.com/tridaai">View all blueprints →</a>'
        "</div>",
        "</footer>",
        "</body>",
        "</html>",
    ]
    return "\n".join(out)
