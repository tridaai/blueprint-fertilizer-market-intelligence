"""The price & feedstock watch (R3): movements and alerts.

A **movement** is a computed artefact: for one price series and
one month, the month-on-month change and the change against the
trailing baseline (the mean of the up-to-six preceding months),
each pinned to the exact price facts it was computed from and to
the alert rule pack version. Movements are computed in code from
stored price points only — the model never touches a figure here
either.

An **alert** is a recorded act of the rule engine: it exists only
because a rule in the pack fired on a movement, and it carries the
triggering movement ids and the computed figures on its face, so
an alert without its movement cannot be constructed — the firing
pass is the only way one comes into being, and it always names
its movements. Firing is a pure function of the stored movements
and the pack, and it is idempotent: re-running the pass over the
same movements produces the same alert ids and stores nothing new.

Alert state is never a stored, editable field. An alert's state
is derived from its **acts** — acknowledgement by a named person
with a note, closure with a stated reason from the pack's
vocabulary — each act its own insert-only artefact. The state
machine (open → acknowledged → closed, or open → closed) is
enforced when an act is recorded; there is no other way for an
alert's state to change.
"""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel

from . import alert_rules as pack

RULE_MOM = "mom_move"
RULE_BASELINE = "baseline_move"
RULE_SPIKE = "spike"
RULE_SUSTAINED = "sustained_move"

PCT_TOL = 0.01


class PriceMovement(BaseModel):
    movement_id: str
    series_kind: str  # product / feedstock
    item: str
    month: str  # YYYY-MM, the month the movement describes
    price: float
    prev_price: float | None
    mom_pct: float | None  # vs the previous month
    baseline_mean: float | None
    baseline_pct: float | None  # vs the trailing baseline mean
    baseline_months: list[str]
    fact_ids: list[str]
    rules_version: str
    fact_fingerprint: str
    as_of: str


class PriceAlert(BaseModel):
    alert_id: str
    series_kind: str
    item: str
    rule_id: str
    band: str  # watch / alert
    period_month: str  # the month the rule fired on
    movement_ids: list[str]
    figures: dict
    rules_version: str
    as_of: str


def _fingerprint(material) -> str:
    blob = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def _price_fact_id(series_kind, item, month):
    return f"price_points:{series_kind}|{item}|{month}"


def _shift_month(month: str, delta: int) -> str:
    year, mon = int(month[:4]), int(month[5:7])
    index = year * 12 + (mon - 1) + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


# -- movements ------------------------------------------------------------


def compute_movements(store, series_kind: str, item: str, as_of: str) -> list[PriceMovement]:
    """Compute (but do not store) the movement artefact for every
    month of one series that has a predecessor month."""
    points = sorted(store.price_points(series_kind, item), key=lambda p: p["month"])
    out: list[PriceMovement] = []
    for i, point in enumerate(points):
        if i == 0:
            continue  # no predecessor: no movement is stated
        price = point["price"]
        prev = points[i - 1]
        mom_pct = round((price - prev["price"]) / prev["price"] * 100.0, 4)
        trailing = points[max(0, i - pack.BASELINE_WINDOW_MONTHS):i]
        baseline_months = [p["month"] for p in trailing]
        if len(trailing) >= pack.BASELINE_MIN_MONTHS:
            baseline_mean = sum(p["price"] for p in trailing) / len(trailing)
            baseline_pct = round((price - baseline_mean) / baseline_mean * 100.0, 4)
            baseline_mean = round(baseline_mean, 4)
        else:
            baseline_mean, baseline_pct = None, None
        consumed = (
            [[_price_fact_id(series_kind, item, point["month"]), price],
             [_price_fact_id(series_kind, item, prev["month"]), prev["price"]]]
            + [[_price_fact_id(series_kind, item, p["month"]), p["price"]] for p in trailing]
        )
        fingerprint = _fingerprint({
            "series": [series_kind, item, point["month"]],
            "rules": pack.RULES_VERSION,
            "points": consumed,
        })
        out.append(PriceMovement(
            movement_id=f"MOV-{series_kind}-{item}-{point['month']}-{fingerprint[:10]}",
            series_kind=series_kind, item=item, month=point["month"],
            price=price, prev_price=prev["price"], mom_pct=mom_pct,
            baseline_mean=baseline_mean, baseline_pct=baseline_pct,
            baseline_months=baseline_months,
            fact_ids=[entry[0] for entry in consumed],
            rules_version=pack.RULES_VERSION,
            fact_fingerprint=fingerprint, as_of=as_of,
        ))
    return out


def verify_movement(store, movement: dict) -> list[str]:
    """Re-perform a stored movement from the stored price facts.
    The artefact must be exactly what the engine computes today
    from those facts under the pack it names."""
    problems: list[str] = []
    if movement["rules_version"] != pack.RULES_VERSION:
        return [f"movement names unknown rule pack {movement['rules_version']}"]
    fresh = compute_movements(store, movement["series_kind"], movement["item"], movement["as_of"])
    match = next((m for m in fresh if m.month == movement["month"]), None)
    if match is None:
        return [f"no movement re-performs for {movement['series_kind']} {movement['item']} {movement['month']}"]
    if match.movement_id != movement["movement_id"]:
        problems.append("movement id does not match the re-performed fingerprint")
    for field in ("price", "prev_price", "mom_pct", "baseline_mean", "baseline_pct"):
        mine, theirs = movement[field], getattr(match, field)
        if (mine is None) != (theirs is None) or (mine is not None and abs(mine - theirs) > 1e-6):
            problems.append(f"{field}: stored {mine} != re-performed {theirs}")
    if movement["baseline_months"] != match.baseline_months:
        problems.append("baseline months do not match the re-performed window")
    if movement["fact_ids"] != match.fact_ids:
        problems.append("fact ids do not match the re-performed inputs")
    return problems


# -- alert firing: a pure function of movements + pack ----------------------


def evaluate_movements(movements: list[dict]) -> list[dict]:
    """Fire the pack's rules over one series' movements (dicts in
    the stored shape, any order). Returns the alert payloads the
    rules produce — alert ids are not assigned here, so the same
    output serves the firing pass and the verifier.

    Each payload: {series_kind, item, rule_id, band, period_month,
    movement_ids, figures}.
    """
    series = sorted(movements, key=lambda m: m["month"])
    if not series:
        return []
    kind, item = series[0]["series_kind"], series[0]["item"]
    fired: list[dict] = []

    def fire(rule_id, band, movement, movement_ids, figures):
        fired.append({
            "series_kind": kind, "item": item, "rule_id": rule_id,
            "band": band, "period_month": movement["month"],
            "movement_ids": movement_ids, "figures": figures,
        })

    # The spike rule, with its event window: after a spike fires,
    # the same series' spike rule stays quiet for the pack's event
    # window — those months are the same event unwinding.
    last_spike_idx: int | None = None
    for idx, movement in enumerate(series):
        mom = movement["mom_pct"]
        if mom is None or abs(mom) < pack.SPIKE_PCT:
            continue
        if last_spike_idx is not None and idx - last_spike_idx <= pack.SPIKE_EVENT_WINDOW_MONTHS:
            continue
        fire(RULE_SPIKE, "alert", movement, [movement["movement_id"]], {"mom_pct": mom})
        last_spike_idx = idx

    # The ordinary movement rules: each fires at the highest band
    # its figure reaches.
    for movement in series:
        mom = movement["mom_pct"]
        if mom is not None:
            band = pack.band_for(kind, RULE_MOM, abs(mom))
            if band:
                fire(RULE_MOM, band, movement, [movement["movement_id"]], {"mom_pct": mom})
        base = movement["baseline_pct"]
        if base is not None:
            band = pack.band_for(kind, RULE_BASELINE, abs(base))
            if band:
                fire(RULE_BASELINE, band, movement, [movement["movement_id"]],
                     {"baseline_pct": base, "baseline_mean": movement["baseline_mean"]})

    # The sustained-move rule: trailing windows of the pack's
    # length, all months in one unbroken same-direction run, each
    # month at or over the floor, the window summing to at least
    # the cumulative floor. Fires once per run.
    n = pack.SUSTAINED_MONTHS
    fired_runs: set[int] = set()
    run_id = -1
    run_direction = 0
    for idx, movement in enumerate(series):
        mom = movement["mom_pct"]
        direction = 0
        if mom is not None and abs(mom) >= pack.SUSTAINED_MIN_MONTHLY_PCT:
            direction = 1 if mom > 0 else -1
        if direction == 0 or direction != run_direction:
            run_id += 1
            run_direction = direction
        movement["_run"] = run_id if direction else None
    for idx in range(n - 1, len(series)):
        window = series[idx - n + 1: idx + 1]
        if any(m["_run"] is None for m in window):
            continue
        if len({m["_run"] for m in window}) != 1:
            continue
        run = window[0]["_run"]
        if run in fired_runs:
            continue
        monthly = [m["mom_pct"] for m in window]
        cumulative = round(sum(monthly), 4)
        if abs(cumulative) < pack.SUSTAINED_CUMULATIVE_PCT:
            continue
        fire(RULE_SUSTAINED, pack.SUSTAINED_BAND, window[-1],
             [m["movement_id"] for m in window],
             {"monthly_pcts": monthly, "cumulative_pct": cumulative})
        fired_runs.add(run)
    for movement in series:
        movement.pop("_run", None)
    return fired


def alert_id_for(payload: dict) -> str:
    fingerprint = _fingerprint({
        "series": [payload["series_kind"], payload["item"]],
        "rule": payload["rule_id"],
        "period": payload["period_month"],
        "movements": payload["movement_ids"],
        "rules": pack.RULES_VERSION,
    })
    return (
        f"ALR-{payload['series_kind']}-{payload['item']}-"
        f"{payload['rule_id']}-{payload['period_month']}-{fingerprint[:10]}"
    )


def verify_alert(store, alert: dict) -> list[str]:
    """Re-perform an alert: its movements must be in the store and
    re-perform clean, and the firing function over the series'
    stored movements must produce this alert — same rule, same
    month, same band, same triggering movements."""
    problems: list[str] = []
    if alert["rules_version"] != pack.RULES_VERSION:
        return [f"alert names unknown rule pack {alert['rules_version']}"]
    for movement_id in alert["movement_ids"]:
        movement = store.get_movement(movement_id)
        if movement is None:
            problems.append(f"triggering movement {movement_id} is not in the store")
            continue
        problems.extend(
            f"{movement_id}: {p}" for p in verify_movement(store, movement)
        )
    movements = store.list_movements(alert["series_kind"], alert["item"])
    expected = {
        (p["rule_id"], p["period_month"]): p for p in evaluate_movements(movements)
    }
    mine = expected.get((alert["rule_id"], alert["period_month"]))
    if mine is None:
        problems.append(
            f"the rules do not fire {alert['rule_id']} for {alert['item']} "
            f"in {alert['period_month']} over the stored movements"
        )
    else:
        if mine["band"] != alert["band"]:
            problems.append(f"band: stored {alert['band']} != re-performed {mine['band']}")
        if mine["movement_ids"] != alert["movement_ids"]:
            problems.append("triggering movements do not match the re-performed firing")
        for key, value in mine["figures"].items():
            stored = alert["figures"].get(key)
            if isinstance(value, list):
                if stored is None or len(stored) != len(value) or any(
                    abs(a - b) > PCT_TOL for a, b in zip(stored, value)
                ):
                    problems.append(f"figure {key}: stored {stored} != re-performed {value}")
            elif stored is None or abs(stored - value) > PCT_TOL:
                problems.append(f"figure {key}: stored {stored} != re-performed {value}")
    return problems


# -- alert state, derived from acts ------------------------------------------


class AlertStateError(RuntimeError):
    """An act was attempted against an alert whose derived state
    does not allow it (acknowledging an acknowledged or closed
    alert, closing a closed alert, acting on a missing alert)."""


def derive_state(acts: list[dict]) -> str:
    """An alert's state is the fold of its acts: open until an
    acknowledgement, acknowledged until a closure, closed for
    good. Acts are append-only, so this fold is the whole story."""
    state = "open"
    for act in acts:
        if act["act"] == "acknowledge":
            state = "acknowledged"
        elif act["act"] == "close":
            state = "closed"
    return state
