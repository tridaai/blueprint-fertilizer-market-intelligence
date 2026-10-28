"""Field signals & mobile intake (R7): submissions, review
acts and the weighting assessment.

Three artefacts, all insert-only like the rest of the store:

- A **field signal report** is what one attributed field
  submission becomes when it lands. Submissions arrive from
  the mobile intake's offline outbox (F21-DI3/MF1): each
  carries a client-generated submission id, and landing is
  exactly-once per (submission id, payload) — a re-send is a
  duplicate, answered with the artefact already stored. The
  same id with a different payload is a conflict: the new
  artefact lands alongside, linked to the first by
  `conflicts_with`, and both read as conflicted — the server
  keeps both, never a silent overwrite. The twelve planted
  R1 field reports enter through the same landing machinery
  by promotion, so one lifecycle covers every field signal
  in the system. Attribution is constitutive: the intake
  refuses a submission missing its reporter, district,
  product, signal type or observation date, naming the
  missing fields — nothing is defaulted.

- A **review act** is a named reviewer's confirm / query /
  reject against one report, with a reason from the act's
  stated vocabulary (the field pack). Acts are insert-only;
  the report's review state is their fold and is stored
  nowhere. A rejection is terminal.

- A **field signal assessment** is the weighting consumer —
  the first thing in the system a field signal can move.
  Per district x product x season it folds the cell's
  reports into an adjustment against the head R2 demand
  estimate: each report contributes its kind's stated effect
  (the pack), decayed by freshness, weighted by review
  state — confirmed at full decayed weight, unreviewed
  clamped to the pack's unverified cap (Law 5, as a number),
  queried and rejected at zero, expired at zero and named.
  Every contribution is a line on the artefact naming its
  reporter and review state, so the adjustment re-performs
  from the stored reports, acts and pack alone. The estimate
  itself is never mutated: the assessment carries the base
  total and the adjusted total side by side.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date

from pydantic import BaseModel

from . import field_rules as pack
from .generator import PRODUCTS
from .share import season_of_month
from .supply import head_of

__all__ = [
    "FieldReviewError",
    "FieldSignalReport",
    "FieldSignalAssessment",
    "payload_hash",
    "validate_submission",
    "normalize_kind",
    "build_report",
    "land_submission",
    "planted_submission",
    "derive_review_state",
    "report_view",
    "decay_factor",
    "compute_assessment",
    "verify_report",
    "verify_assessment",
]


class FieldReviewError(Exception):
    """A review act the report's current state refuses."""


# -- submissions ---------------------------------------------------------------


def _canonical_payload(sub: dict) -> dict:
    """The content that defines a submission's identity for
    exactly-once landing: the form fields as received. Sync
    envelope noise (when it was sent, by what transport) is
    not identity — the same queued report re-sent is the
    same submission."""
    keys = (
        "reporter", "district_id", "product", "signal_type", "signal_kind",
        "observed_on", "quantity_tonnes", "price_inr_tonne", "direction",
        "detail", "photo_ref", "source",
    )
    return {key: sub.get(key) for key in keys if sub.get(key) is not None}


def payload_hash(sub: dict) -> str:
    blob = json.dumps(
        _canonical_payload(sub), sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(blob).hexdigest()


def normalize_kind(sub: dict) -> str:
    """The weighted kind a submission speaks in: a planted
    report carries its kind directly; an intake type maps
    through the pack, with demand_signal taking its kind
    from its stated direction."""
    if sub.get("signal_kind"):
        return sub["signal_kind"]
    if sub["signal_type"] == "demand_signal":
        return pack.KIND_BY_DEMAND_DIRECTION[sub["direction"]]
    return pack.KIND_BY_INTAKE_TYPE[sub["signal_type"]]


def validate_submission(store, sub: dict) -> None:
    """The intake port's validation: attribution fields are
    mandatory and named when missing (never defaulted), the
    district and product must be ones the system tracks, the
    signal type must be one the form may carry, and the
    observation date must be a date."""
    label = sub.get("submission_id") or "<no submission id>"
    missing = [
        field
        for field in ("submission_id",) + pack.REQUIRED_FIELDS
        if sub.get(field) is None or str(sub.get(field)).strip() == ""
    ]
    if missing:
        raise ValueError(
            f"field submission {label} is missing required fields: "
            f"{', '.join(missing)} — a field report is attributed or "
            "it is not a field report; nothing was defaulted"
        )
    district_ids = {d["district_id"] for d in store.list_districts()}
    if sub["district_id"] not in district_ids:
        raise ValueError(
            f"field submission {label} names unknown district "
            f"{sub['district_id']}"
        )
    if sub["product"] not in PRODUCTS:
        raise ValueError(
            f"field submission {label} names untracked product {sub['product']}"
        )
    if sub.get("signal_kind"):
        if sub["signal_kind"] not in pack.EFFECT_PCT:
            raise ValueError(
                f"field submission {label} carries unknown signal kind "
                f"{sub['signal_kind']}"
            )
    else:
        if sub["signal_type"] not in pack.SIGNAL_TYPES:
            raise ValueError(
                f"field submission {label} carries signal type "
                f"{sub['signal_type']}, not one of {sorted(pack.SIGNAL_TYPES)}"
            )
        if sub["signal_type"] == "demand_signal" \
                and sub.get("direction") not in pack.DEMAND_DIRECTIONS:
            raise ValueError(
                f"field submission {label} is a demand_signal without a "
                f"direction in {sorted(pack.DEMAND_DIRECTIONS)}"
            )
    try:
        date.fromisoformat(str(sub["observed_on"]))
    except ValueError:
        raise ValueError(
            f"field submission {label} has observed_on "
            f"{sub['observed_on']!r}, not an ISO date"
        ) from None
    for field in ("quantity_tonnes", "price_inr_tonne"):
        value = sub.get(field)
        if value is not None and (not isinstance(value, (int, float)) or value < 0):
            raise ValueError(
                f"field submission {label} has {field} {value!r}, "
                "not a non-negative number"
            )


class FieldSignalReport(BaseModel):
    report_id: str
    submission_id: str
    payload_hash: str
    reporter: str  # attribution: the named field officer / dealer
    district_id: str
    product: str
    signal_type: str  # as submitted (an intake type, or planted_report)
    signal_kind: str  # normalized by the pack — the weighted kind
    observed_on: str  # ISO date the observation was made
    quantity_tonnes: float | None = None
    price_inr_tonne: float | None = None
    direction: str | None = None
    detail: str | None = None
    photo_ref: str | None = None  # a reference string only, never a binary
    crop_year: str | None = None  # season attribution of the observed month
    season: str | None = None  # None: the month belongs to no tracked season
    source: str  # provenance: the label of the channel it arrived by
    as_of: str  # the date the report landed
    conflicts_with: str | None = None
    submission: dict  # the submission exactly as received
    rules_version: str


def build_report(sub: dict, landed_on: str, conflicts_with: str | None) -> FieldSignalReport:
    """Build (do not store) the artefact one submission lands
    as. The id is the submission id's first landing; a
    conflicting payload lands under a hash-suffixed id, so
    the same conflict re-sent builds the same artefact and
    the landing reads it as a duplicate."""
    digest = payload_hash(sub)
    if conflicts_with is None:
        report_id = f"FSR-{sub['submission_id']}"
    else:
        report_id = f"FSR-{sub['submission_id']}-X{digest[:6]}"
    attributed = season_of_month(str(sub["observed_on"])[:7])
    crop_year, season = attributed if attributed else (None, None)
    return FieldSignalReport(
        report_id=report_id,
        submission_id=sub["submission_id"],
        payload_hash=digest,
        reporter=str(sub["reporter"]),
        district_id=sub["district_id"],
        product=sub["product"],
        signal_type=sub.get("signal_type") or "planted_report",
        signal_kind=normalize_kind(sub),
        observed_on=str(sub["observed_on"]),
        quantity_tonnes=sub.get("quantity_tonnes"),
        price_inr_tonne=sub.get("price_inr_tonne"),
        direction=sub.get("direction"),
        detail=sub.get("detail"),
        photo_ref=sub.get("photo_ref"),
        crop_year=crop_year,
        season=season,
        source=sub.get("source") or pack.INTAKE_SOURCE,
        as_of=landed_on,
        conflicts_with=conflicts_with,
        submission=dict(sub),
        rules_version=pack.RULES_VERSION,
    )


def land_submission(store, sub: dict, landed_on: str) -> dict:
    """Land one validated submission exactly once. Returns
    the outcome — landed / duplicate / conflict — with the
    stored artefact. A conflict lands alongside the original
    and links to it; the original is never touched."""
    digest = payload_hash(sub)
    same_id = store.list_field_report_artefacts(submission_id=sub["submission_id"])
    for existing in same_id:
        if existing["payload_hash"] == digest:
            return {"outcome": "duplicate", "report": existing}
    conflicts_with = same_id[0]["report_id"] if same_id else None
    report = build_report(sub, landed_on, conflicts_with)
    store.insert_field_report_artefact(report.model_dump())
    stored = store.get_field_report_artefact(report.report_id)
    return {
        "outcome": "conflict" if same_id else "landed",
        "report": stored,
    }


def planted_submission(fact: dict) -> dict:
    """The submission a planted R1 field report promotes
    through: its fact identity becomes the submission id, its
    kind and source ride along, so promotion and intake land
    artefacts of exactly the same shape."""
    return {
        "submission_id": fact["report_id"],
        "reporter": fact["reporter"],
        "district_id": fact["district_id"],
        "product": fact["product"],
        "signal_type": "planted_report",
        "signal_kind": fact["signal_kind"],
        "observed_on": fact["date"],
        "detail": fact["detail"],
        "source": fact["source"],
    }


# -- review state ----------------------------------------------------------------


def derive_review_state(acts: list[dict]) -> str:
    """The fold the pack states: any reject act makes the
    report rejected, terminally; otherwise the latest act
    decides; no acts is unreviewed."""
    if any(act["act"] == pack.ACT_REJECT for act in acts):
        return pack.STATE_REJECTED
    if not acts:
        return pack.STATE_UNREVIEWED
    latest = acts[-1]["act"]
    return pack.STATE_CONFIRMED if latest == pack.ACT_CONFIRM else pack.STATE_QUERIED


def report_view(store, report: dict) -> dict:
    """One report with everything a reader needs: its acts,
    its derived review state, and its conflict standing —
    the ids of the other artefacts that share its submission
    id under a different payload."""
    acts = store.list_field_review_acts(report["report_id"])
    siblings = store.list_field_report_artefacts(
        submission_id=report["submission_id"]
    )
    conflict_ids = sorted(
        s["report_id"] for s in siblings
        if s["report_id"] != report["report_id"]
        and s["payload_hash"] != report["payload_hash"]
    )
    view = dict(report)
    view["acts"] = acts
    view["review_state"] = derive_review_state(acts)
    view["has_conflict"] = bool(conflict_ids)
    view["conflict_report_ids"] = conflict_ids
    return view


def verify_report(store, report: dict) -> list[str]:
    """Re-perform a landed report from its own submission:
    the stored payload hash must be the submission's hash,
    and every normalized field — kind, season attribution,
    provenance — must be what the landing rules build from
    that submission."""
    problems: list[str] = []
    if not report.get("reporter") or not report.get("source") \
            or not report.get("observed_on"):
        problems.append("the report carries no attribution")
        return problems
    sub = report["submission"]
    if report["payload_hash"] != payload_hash(sub):
        problems.append("payload hash does not re-perform from the submission")
    fresh = build_report(sub, report["as_of"], report["conflicts_with"])
    stored = {k: report[k] for k in fresh.model_dump() if k != "submission"}
    rebuilt = {k: v for k, v in fresh.model_dump().items() if k != "submission"}
    if stored != rebuilt:
        problems.append("report does not re-perform from its submission")
    return problems


# -- the weighting assessment -----------------------------------------------------


def decay_factor(age_days: int) -> float:
    """The pack's freshness decay: half-life halving from
    the observation date, zero past the maximum age."""
    if age_days > pack.MAX_AGE_DAYS:
        return 0.0
    return round(0.5 ** (age_days / pack.HALF_LIFE_DAYS), pack.DECAY_DECIMALS)


class FieldSignalAssessment(BaseModel):
    assessment_id: str
    district_id: str
    product: str
    crop_year: str
    season: str
    as_of: str  # the date the assessment is struck at
    estimate_id: str  # the head R2 estimate it adjusts
    estimate_status: str
    base_tonnes: float  # the estimate's total, unmutated
    lines: list[dict]  # one per contributing report, attributed
    excluded: list[dict]  # reports in the cell not yet observable, named
    adjustment_pct: float
    adjustment_tonnes: float
    adjusted_tonnes: float
    capped_report_ids: list[str]  # unreviewed reports the cap bound
    rules_version: str
    fact_fingerprint: str
    supersedes: str | None = None


def _fingerprint(material) -> str:
    blob = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def _contribution_line(store, report: dict, as_of: str) -> dict:
    """One report's weighted line at the assessment date:
    kind effect, freshness decay, review state, the cap —
    every intermediate carried so the line re-performs."""
    acts = [
        act for act in store.list_field_review_acts(report["report_id"])
        if act["as_of"] <= as_of
    ]
    state = derive_review_state(acts)
    age_days = (date.fromisoformat(as_of) - date.fromisoformat(report["observed_on"])).days
    expired = age_days > pack.MAX_AGE_DAYS
    decay = decay_factor(age_days)
    effect = pack.EFFECT_PCT[report["signal_kind"]]
    uncapped = round(effect * decay, pack.CONTRIBUTION_DECIMALS)
    capped = False
    zero_reason = None
    if expired:
        applied = 0.0
        zero_reason = "expired"
    elif state == pack.STATE_CONFIRMED:
        applied = uncapped
    elif state == pack.STATE_UNREVIEWED:
        applied = round(
            max(-pack.UNVERIFIED_CAP_PCT, min(pack.UNVERIFIED_CAP_PCT, uncapped)),
            pack.CONTRIBUTION_DECIMALS,
        )
        capped = applied != uncapped
    elif state == pack.STATE_QUERIED:
        applied = 0.0
        zero_reason = "queried"
    else:  # rejected
        applied = 0.0
        zero_reason = "rejected"
    return {
        "report_id": report["report_id"],
        "submission_id": report["submission_id"],
        "reporter": report["reporter"],
        "signal_kind": report["signal_kind"],
        "observed_on": report["observed_on"],
        "age_days": age_days,
        "decay": decay,
        "effect_pct": effect,
        "review_state": state,
        "uncapped_pct": uncapped,
        "applied_pct": applied,
        "capped": capped,
        "expired": expired,
        "zero_reason": zero_reason,
    }


def compute_assessment(store, district_id, product, crop_year, season, as_of) -> FieldSignalAssessment:
    """Fold one cell's field reports into an adjustment
    against its head R2 demand estimate. The estimate must
    already be stored (the service ensures it); the estimate
    is read, never mutated."""
    head = head_of(
        store.list_estimates(district_id, product, crop_year, season),
        "estimate_id",
    )
    if head is None:
        raise ValueError(
            f"no demand estimate stored for {district_id} {product} "
            f"{crop_year} {season} — compute the estimate first"
        )
    in_cell = [
        report
        for report in store.list_field_report_artefacts(
            district_id=district_id, product=product
        )
        if report["crop_year"] == crop_year and report["season"] == season
    ]
    lines: list[dict] = []
    excluded: list[dict] = []
    act_ids: list[str] = []
    for report in sorted(in_cell, key=lambda r: (r["observed_on"], r["report_id"])):
        if report["as_of"] > as_of:
            excluded.append({
                "report_id": report["report_id"],
                "reporter": report["reporter"],
                "reason": "landed_after_as_of",
            })
            continue
        if report["observed_on"] > as_of:
            excluded.append({
                "report_id": report["report_id"],
                "reporter": report["reporter"],
                "reason": "observed_after_as_of",
            })
            continue
        act_ids.extend(
            act["act_id"]
            for act in store.list_field_review_acts(report["report_id"])
            if act["as_of"] <= as_of
        )
        lines.append(_contribution_line(store, report, as_of))
    adjustment_pct = round(
        sum(line["applied_pct"] for line in lines), pack.PCT_DECIMALS
    )
    base = head["total_tonnes"]
    adjusted = round(base * (1 + adjustment_pct / 100.0), pack.TONNE_DECIMALS)
    fingerprint = _fingerprint({
        "cell": [district_id, product, crop_year, season],
        "as_of": as_of,
        "estimate": [head["estimate_id"], head["fact_fingerprint"], base],
        "reports": sorted(
            [r["report_id"], r["payload_hash"]] for r in in_cell
        ),
        "acts": sorted(act_ids),
        "rules_version": pack.RULES_VERSION,
    })
    return FieldSignalAssessment(
        assessment_id=(
            f"FSA-{district_id}-{product}-{crop_year}-{season}-"
            f"{fingerprint[:10]}"
        ),
        district_id=district_id,
        product=product,
        crop_year=crop_year,
        season=season,
        as_of=as_of,
        estimate_id=head["estimate_id"],
        estimate_status=head["status"],
        base_tonnes=base,
        lines=lines,
        excluded=excluded,
        adjustment_pct=adjustment_pct,
        adjustment_tonnes=round(adjusted - base, pack.TONNE_DECIMALS),
        adjusted_tonnes=adjusted,
        capped_report_ids=[line["report_id"] for line in lines if line["capped"]],
        rules_version=pack.RULES_VERSION,
        fact_fingerprint=fingerprint,
    )


def verify_assessment(store, assessment: dict) -> list[str]:
    """Re-perform a stored assessment from the stored
    reports, acts, estimate and pack: the recomputation must
    equal the artefact, line for line and total for total."""
    try:
        fresh = compute_assessment(
            store,
            assessment["district_id"], assessment["product"],
            assessment["crop_year"], assessment["season"],
            assessment["as_of"],
        )
    except ValueError as exc:
        return [str(exc)]
    stored = {
        k: assessment[k] for k in fresh.model_dump() if k != "supersedes"
    }
    rebuilt = fresh.model_dump(exclude={"supersedes"})
    if stored != rebuilt:
        return ["assessment does not re-perform from its reports, acts and estimate"]
    return []
