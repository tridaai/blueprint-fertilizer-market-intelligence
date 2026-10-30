"""Alert subscriptions, deliveries, escalation &
digests (R16, roadmap F21-AL1 + F21-AL2).

Who hears about an alert is a governed decision in
this build, not a mailing list kept in someone's
head:

- **A subscription is an artefact.** A named reader
  from the access register (R15) holds a standing
  instruction — classes, products, regions, severity
  floors — struck by themselves or by the strategy
  desk, judged by the access pack before it exists,
  and superseded by link when it changes. It is never
  edited.
- **A delivery is derived, never authored.** At any
  read date, the deliveries are recomputed from the
  notices (the alert artefacts as they stand), the
  subscription versions in force when each notice was
  struck, and the subscriber's remit in the access
  register. A delivery changes no alert's state; the
  alert's own acts remain the whole story of the
  alert. A notice no subscription reaches is counted
  as undelivered-by-design — a fact about coverage,
  not an error.
- **Escalation is a clock in code.** An alert-band
  price alert still open past the pack's windows
  climbs a ladder resolved from the register. The
  state is derived from the acts and the read date on
  every read, and an escalation names follow-up tasks
  pinned to the alert by reference — it never writes
  one.
- **A digest freezes a derivation.** The digest
  artefact holds one subscription version's delivery
  set and its escalations at a generation date, so
  what a reader was told can be re-performed later
  exactly. Regenerating is a new artefact superseding
  the old, never an edit.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date

from pydantic import BaseModel

from . import access as access_engine
from . import access_rules as access_pack
from . import movements as movement_engine
from . import notify_rules as pack
from . import policy as policy_engine
from . import queue as queue_engine
from .generator import FEEDSTOCKS, PRODUCTS, REGIONS

ITEMS = sorted(PRODUCTS + FEEDSTOCKS)
CLASS_ORDER = {pack.CLASS_PRICE: 0, pack.CLASS_GAP: 1,
               pack.CLASS_POLICY: 2}


class SubscriptionRefused(RuntimeError):
    """A subscription strike the access pack judged
    out of bounds: the refusal is in the access log,
    and no artefact exists."""

    def __init__(self, reason: str, entry_id: str):
        super().__init__(reason)
        self.reason = reason
        self.entry_id = entry_id


class Subscription(BaseModel):
    subscription_id: str
    fingerprint: str
    principal: str
    struck_by: str
    at: str
    classes: list[str]
    products: list[str]
    regions: list[str]
    floors: dict
    rules_version: str
    supersedes: str | None = None


class Digest(BaseModel):
    digest_id: str
    fingerprint: str
    subscription_id: str
    principal: str
    as_of: str
    deliveries: list[dict]
    counts: dict
    escalations: list[dict]
    rules_version: str
    supersedes: str | None = None


def _fingerprint(payload: dict) -> str:
    blob = json.dumps(
        payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------------------
# Subscriptions: struck once per version, superseded by
# link, judged by the access pack before they exist.
# ---------------------------------------------------------------------------


def _floor_label(notice_class: str, label: str | None) -> str:
    scale = pack.SEVERITY[notice_class]
    if label is None:
        return min(scale, key=scale.get)
    if label not in scale:
        raise ValueError(
            f"a {notice_class} floor names a severity "
            f"from {sorted(scale)} — got {label!r}")
    return label


def build_subscription(principal: str, struck_by: str,
                       at: str, classes, products, regions,
                       floors=None,
                       supersedes=None) -> Subscription:
    """Strike (do not store) one subscription version.
    Filters are validated against the tracked universe
    and normalised; the floors are completed per class
    with the class's lowest severity, so the artefact
    states its whole filter on its face."""
    classes = sorted(set(classes or []))
    if not classes:
        raise ValueError(
            "a subscription names at least one alert class")
    unknown = [c for c in classes if c not in pack.CLASSES]
    if unknown:
        raise ValueError(
            f"unknown alert classes {unknown} — the "
            f"notify pack names {list(pack.CLASSES)}")
    products = sorted(set(products or []))
    bad = [p for p in products if p not in ITEMS]
    if bad:
        raise ValueError(
            f"a subscription filters on tracked items — "
            f"{bad} are not tracked")
    regions = sorted(set(regions or []))
    bad = [r for r in regions if r not in REGIONS]
    if bad:
        raise ValueError(
            f"a subscription filters on register regions "
            f"— {bad} are not in the register")
    floors = dict(floors or {})
    bad = [c for c in floors if c not in classes]
    if bad:
        raise ValueError(
            f"floors are stated for subscribed classes "
            f"only — {bad} are not subscribed")
    floors = {c: _floor_label(c, floors.get(c))
              for c in classes}
    fingerprint = _fingerprint({
        "principal": principal, "struck_by": struck_by,
        "at": at, "classes": classes, "products": products,
        "regions": regions, "floors": floors,
        "supersedes": supersedes, "pack": pack.RULES_VERSION,
    })
    return Subscription(
        subscription_id=f"SUB-{fingerprint[:10]}",
        fingerprint=fingerprint, principal=principal,
        struck_by=struck_by, at=at, classes=classes,
        products=products, regions=regions, floors=floors,
        rules_version=pack.RULES_VERSION,
        supersedes=supersedes)


def subscription_versions(store, principal: str) -> list[dict]:
    """One principal's versions in chain order (strike
    order): by strike date, then id."""
    return sorted(store.list_subscriptions(principal),
                  key=lambda s: (s["at"], s["subscription_id"]))


def version_in_force(versions: list[dict],
                     on_date: str) -> dict | None:
    """The version governing a date: the latest version
    struck on or before it, in chain order."""
    in_force = None
    for version in versions:
        if version["at"] <= on_date:
            in_force = version
    return in_force


# ---------------------------------------------------------------------------
# Notices: the deliverable units, derived from the
# alert artefacts as they stand.
# ---------------------------------------------------------------------------


def list_notices(store) -> list[dict]:
    """Every notice the record currently raises: one
    per price alert, one per non-comfortable gap head
    (the R13 queue's membership), one per current,
    real policy registry head. Policy notices are
    their own class — they are never price alerts."""
    notices: list[dict] = []
    for alert in store.list_alerts():
        notices.append({
            "notice_id": alert["alert_id"],
            "notice_class": pack.CLASS_PRICE,
            "item": alert["item"],
            "products": [alert["item"]],
            "regions": [],
            "severity": alert["band"],
            "severity_rank":
                pack.SEVERITY[pack.CLASS_PRICE][alert["band"]],
            "struck_on": alert["as_of"],
            "queue_item_id": None,
            "event_id": None,
        })
    for gap in queue_engine.member_gaps(store):
        notices.append({
            "notice_id": gap["gap_id"],
            "notice_class": pack.CLASS_GAP,
            "item": None,
            "products": [gap["product"]],
            "regions": [],
            "severity": gap["band"],
            "severity_rank":
                pack.SEVERITY[pack.CLASS_GAP][gap["band"]],
            "struck_on": gap["as_of"],
            "queue_item_id": queue_engine.item_id_for(gap),
            "event_id": None,
        })
    region_of = {d["district_id"]: d["region"]
                 for d in store.list_districts()}
    heads = policy_engine.heads_by_event(
        store.list_policy_registrations())
    for event in heads.values():
        if event["hypothetical"]:
            continue
        notices.append({
            "notice_id": event["registry_id"],
            "notice_class": pack.CLASS_POLICY,
            "item": None,
            "products": sorted(event["products"]),
            "regions": sorted({region_of[d]
                               for d in event["districts"]
                               if d in region_of}),
            "severity": "marker",
            "severity_rank":
                pack.SEVERITY[pack.CLASS_POLICY]["marker"],
            "struck_on": event["recorded_on"],
            "queue_item_id": None,
            "event_id": event["event_id"],
        })
    return sorted(notices, key=lambda n: (
        CLASS_ORDER[n["notice_class"]], n["notice_id"]))


# ---------------------------------------------------------------------------
# Matching: the subscription's filter, then the
# register's remit — a delivery needs both.
# ---------------------------------------------------------------------------


def filter_matches(version: dict, notice: dict) -> bool:
    """Whether a subscription version's stated filter
    takes a notice: class, product touch, region touch
    (a national notice touches no region filter), and
    the class's severity floor."""
    if notice["notice_class"] not in version["classes"]:
        return False
    if version["products"] and not (
            set(notice["products"]) & set(version["products"])):
        return False
    if version["regions"] and not (
            notice["regions"]
            and set(notice["regions"]) & set(version["regions"])):
        return False
    floor = pack.SEVERITY[notice["notice_class"]][
        version["floors"][notice["notice_class"]]]
    return notice["severity_rank"] >= floor


def remit_allows(principal: dict, notice: dict) -> bool:
    """Whether the access register's remit lets this
    principal receive this notice at all — the delivery
    side of the R15 scope rules, applied to notices:
    strategy the whole book, a product reader their
    products, a regional reader only geography that
    touches their regions, a viewer nothing."""
    role = principal["role"]
    if role == access_pack.ROLE_STRATEGY:
        return True
    if role == access_pack.ROLE_VIEWER:
        return False
    if role == access_pack.ROLE_PRODUCT:
        return bool(set(notice["products"])
                    & set(principal["products"]))
    if role == access_pack.ROLE_REGIONAL:
        return bool(notice["regions"]
                    and set(notice["regions"])
                    & set(principal["regions"]))
    return False


# ---------------------------------------------------------------------------
# Deliveries: derived from notices × versions × remit.
# ---------------------------------------------------------------------------


def derive_deliveries(store, as_of: str) -> list[dict]:
    """Every delivery in force at a read date: for each
    notice, the subscription version in force on the
    day the notice was struck delivers it — when that
    version's filter takes the notice and the
    subscriber's remit allows it. Nothing here is
    stored, and nothing here moves an alert."""
    notices = [n for n in list_notices(store)
               if n["struck_on"] <= as_of]
    deliveries: list[dict] = []
    principals = sorted({s["principal"]
                         for s in store.list_subscriptions()})
    for principal_name in principals:
        principal = access_engine.resolve_principal(
            principal_name)
        versions = subscription_versions(store, principal_name)
        for notice in notices:
            version = version_in_force(versions,
                                       notice["struck_on"])
            if version is None:
                continue
            if not filter_matches(version, notice):
                continue
            if not remit_allows(principal, notice):
                continue
            deliveries.append({
                "subscription_id": version["subscription_id"],
                "principal": principal_name,
                "notice_id": notice["notice_id"],
                "notice_class": notice["notice_class"],
                "item": notice["item"],
                "products": notice["products"],
                "regions": notice["regions"],
                "severity": notice["severity"],
                "struck_on": notice["struck_on"],
                "queue_item_id": notice["queue_item_id"],
                "event_id": notice["event_id"],
            })
    return sorted(deliveries, key=lambda d: (
        d["principal"], d["subscription_id"],
        CLASS_ORDER[d["notice_class"]], d["notice_id"]))


def undelivered_counts(store, as_of: str) -> dict:
    """Notices at the read date that no subscription
    delivers, counted per class — undelivered by
    design, a coverage fact. Policy counts are stated
    apart from price counts, always."""
    delivered = {d["notice_id"]
                 for d in derive_deliveries(store, as_of)}
    counts = {c: 0 for c in pack.CLASSES}
    for notice in list_notices(store):
        if notice["struck_on"] <= as_of \
                and notice["notice_id"] not in delivered:
            counts[notice["notice_class"]] += 1
    return counts


# ---------------------------------------------------------------------------
# Escalation: a clock over the alert acts.
# ---------------------------------------------------------------------------


def _strategy_principal(store) -> str | None:
    names = [name for name, entry
             in access_pack.PRINCIPALS.items()
             if entry["role"] == access_pack.ROLE_STRATEGY]
    return sorted(names)[0] if names else None


def _product_owner(item: str) -> str | None:
    names = [name for name, entry
             in access_pack.PRINCIPALS.items()
             if entry["role"] == access_pack.ROLE_PRODUCT
             and item in entry["products"]]
    return sorted(names)[0] if names else None


def ladder_targets(store, item: str, level: int) -> list[dict]:
    """The ladder's named targets at a level: level 1
    engages the product owner slot (the register's
    product reader for the item, falling back to the
    strategy principal for an item nobody owns, such
    as a feedstock); level 2 adds the strategy slot."""
    targets: list[dict] = []
    if level >= 1:
        owner = _product_owner(item)
        targets.append({
            "level": 1, "slot": pack.LADDER_PRODUCT_OWNER,
            "principal": owner or _strategy_principal(store),
            "via": "product remit" if owner
                   else "strategy fallback"})
    if level >= 2:
        strategy = _strategy_principal(store)
        if all(t["principal"] != strategy for t in targets):
            targets.append({
                "level": 2, "slot": pack.LADDER_STRATEGY,
                "principal": strategy, "via": "strategy desk"})
    return targets


def escalation_for(store, alert: dict, as_of: str) -> dict:
    """One price alert's escalation state at a read
    date, derived from its acts and the clock: the
    act fold is taken at the read date (the readiness
    round's discipline — an act speaks from its own
    date), only an alert-band alert still open at
    that date escalates, and an acknowledgement or a
    closure stops the clock for good. Follow-up tasks
    pinned to the alert are named by reference."""
    acts = [a for a in store.list_alert_acts(alert["alert_id"])
            if a["as_of"] <= as_of]
    state = movement_engine.derive_state(acts)
    age_days = (date.fromisoformat(as_of)
                - date.fromisoformat(alert["as_of"])).days
    level = 0
    if alert["band"] == pack.ESCALATION_BAND \
            and state == "open":
        for rung, window in sorted(
                pack.ESCALATION_WINDOWS.items()):
            if age_days >= window:
                level = rung
    tasks = store.list_followup_tasks(
        target_kind="price_alert", target_id=alert["alert_id"])
    return {
        "alert_id": alert["alert_id"],
        "item": alert["item"],
        "band": alert["band"],
        "state": state,
        "struck_on": alert["as_of"],
        "age_days": age_days,
        "level": level,
        "targets": ladder_targets(store, alert["item"], level)
                   if level else [],
        "followup_task_ids": [t["task_id"] for t in tasks],
    }


def derive_escalations(store, as_of: str) -> list[dict]:
    """Every alert-band price alert's escalation state
    at a read date, worst first: level, then age."""
    rows = [escalation_for(store, alert, as_of)
            for alert in store.list_alerts()
            if alert["band"] == pack.ESCALATION_BAND]
    return sorted(rows, key=lambda r: (
        -r["level"], -r["age_days"], r["alert_id"]))


# ---------------------------------------------------------------------------
# Digests: a subscription's derivation, frozen.
# ---------------------------------------------------------------------------


def build_digest(store, subscription: dict,
                 as_of: str) -> Digest:
    """Strike (do not store) the digest of one
    subscription version at a generation date: exactly
    the deliveries derived for that version at that
    date, its counts per class — policy apart from
    price, always — and the escalations of the
    critical price alerts it delivered."""
    deliveries = [d for d in derive_deliveries(store, as_of)
                  if d["subscription_id"]
                  == subscription["subscription_id"]]
    counts = {c: 0 for c in pack.CLASSES}
    for row in deliveries:
        counts[row["notice_class"]] += 1
    escalations = []
    for row in deliveries:
        if row["notice_class"] != pack.CLASS_PRICE:
            continue
        alert = store.get_alert(row["notice_id"])
        esc = escalation_for(store, alert, as_of)
        if esc["level"] >= 1:
            escalations.append(esc)
    fingerprint = _fingerprint({
        "subscription": subscription["subscription_id"],
        "as_of": as_of, "deliveries": deliveries,
        "counts": counts, "escalations": escalations,
        "pack": pack.RULES_VERSION,
    })
    return Digest(
        digest_id=f"DIG-{fingerprint[:10]}",
        fingerprint=fingerprint,
        subscription_id=subscription["subscription_id"],
        principal=subscription["principal"], as_of=as_of,
        deliveries=deliveries, counts=counts,
        escalations=escalations,
        rules_version=pack.RULES_VERSION)


def render_digest_text(digest: dict) -> str:
    """The low-bandwidth form of a digest: the same
    content, as plain lines a slow link or a phone can
    carry. Nothing is added and nothing is dropped."""
    lines = [
        f"DIGEST {digest['digest_id']}",
        f"subscription {digest['subscription_id']} "
        f"for {digest['principal']} at {digest['as_of']}",
        "counts: " + ", ".join(
            f"{c} {digest['counts'][c]}"
            for c in pack.CLASSES),
    ]
    for row in digest["deliveries"]:
        subject = row["item"] or "/".join(row["products"])
        lines.append(
            f"- [{row['notice_class']}] {subject} "
            f"{row['severity']} {row['struck_on']} "
            f"{row['notice_id']}")
    for esc in digest["escalations"]:
        names = ", ".join(
            t["principal"] or "unstaffed"
            for t in esc["targets"])
        lines.append(
            f"! ESCALATED {esc['item']} level "
            f"{esc['level']} after {esc['age_days']}d "
            f"open — with {names} ({esc['alert_id']})")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Verification: a second route over the raw store.
# ---------------------------------------------------------------------------


def _expected_deliveries(store, as_of: str) -> set:
    """The delivery set re-derived by the opposite
    walk: notices outer, the in-force version found by
    walking each principal's chain, filter and remit
    re-judged inline. Any disagreement with
    derive_deliveries is a defect, whichever route is
    wrong."""
    expected = set()
    versions_by_principal: dict[str, list[dict]] = {}
    for sub in store.list_subscriptions():
        versions_by_principal.setdefault(
            sub["principal"], []).append(sub)
    for versions in versions_by_principal.values():
        versions.sort(key=lambda s: (s["at"],
                                     s["subscription_id"]))
    for notice in list_notices(store):
        if notice["struck_on"] > as_of:
            continue
        for principal_name, versions in \
                versions_by_principal.items():
            version = None
            for candidate in versions:
                if candidate["at"] <= notice["struck_on"]:
                    version = candidate
            if version is None:
                continue
            if notice["notice_class"] not in version["classes"]:
                continue
            if version["products"] and not (
                    set(notice["products"])
                    & set(version["products"])):
                continue
            if version["regions"] and not (
                    notice["regions"]
                    and set(notice["regions"])
                    & set(version["regions"])):
                continue
            floor = pack.SEVERITY[notice["notice_class"]][
                version["floors"][notice["notice_class"]]]
            if notice["severity_rank"] < floor:
                continue
            principal = access_engine.resolve_principal(
                principal_name)
            role = principal["role"]
            if role == access_pack.ROLE_VIEWER:
                continue
            if role == access_pack.ROLE_PRODUCT and not (
                    set(notice["products"])
                    & set(principal["products"])):
                continue
            if role == access_pack.ROLE_REGIONAL and not (
                    notice["regions"]
                    and set(notice["regions"])
                    & set(principal["regions"])):
                continue
            expected.add((version["subscription_id"],
                          notice["notice_id"]))
    return expected


def verify_subscriptions(store, as_of: str) -> list[str]:
    """Re-perform the whole notify layer: every
    subscription rebuilds from its fields and its
    chain links in order; every subscription reconciles
    one-to-one with an allowed access entry naming it;
    the delivery set re-derives by the opposite walk;
    every escalation re-derives from the acts and the
    clock; every digest re-performs against the
    derivation at its own date."""
    problems: list[str] = []
    subscriptions = store.list_subscriptions()
    by_id = {s["subscription_id"]: s for s in subscriptions}
    for sub in subscriptions:
        try:
            rebuilt = build_subscription(
                sub["principal"], sub["struck_by"], sub["at"],
                sub["classes"], sub["products"],
                sub["regions"], sub["floors"],
                sub["supersedes"])
        except ValueError as exc:
            problems.append(
                f"subscription {sub['subscription_id']}: {exc}")
            continue
        if rebuilt.subscription_id != sub["subscription_id"] \
                or rebuilt.fingerprint != sub["fingerprint"]:
            problems.append(
                f"subscription {sub['subscription_id']}: "
                "its fingerprint does not match its fields")
    principals = sorted({s["principal"] for s in subscriptions})
    for principal_name in principals:
        versions = subscription_versions(store, principal_name)
        for idx, version in enumerate(versions):
            want = versions[idx - 1]["subscription_id"] \
                if idx else None
            if version["supersedes"] != want:
                problems.append(
                    f"subscription {version['subscription_id']}: "
                    f"supersedes {version['supersedes']}, but "
                    f"the chain order says {want}")
    entries = [e for e in store.list_access_entries()
               if e["surface"] == access_pack.SURFACE_SUBSCRIPTION]
    allowed_targets = [e["target"] for e in entries
                       if e["decision"]
                       == access_pack.DECISION_ALLOWED]
    for sub in subscriptions:
        if allowed_targets.count(sub["subscription_id"]) != 1:
            problems.append(
                f"subscription {sub['subscription_id']}: "
                f"{allowed_targets.count(sub['subscription_id'])} "
                "allowed access entries name it, not one")
    for entry in entries:
        if entry["decision"] == access_pack.DECISION_ALLOWED \
                and entry["target"] not in by_id:
            problems.append(
                f"access entry {entry['entry_id']}: allows "
                f"subscription {entry['target']}, which is "
                "not in the store")
    actual = {(d["subscription_id"], d["notice_id"])
              for d in derive_deliveries(store, as_of)}
    expected = _expected_deliveries(store, as_of)
    for pair in sorted(actual - expected):
        problems.append(
            f"delivery {pair[0]} -> {pair[1]}: derived by "
            "the service route but not by re-performance "
            "(an orphan delivery)")
    for pair in sorted(expected - actual):
        problems.append(
            f"delivery {pair[0]} -> {pair[1]}: required by "
            "re-performance but not derived")
    notices = {n["notice_id"]: n for n in list_notices(store)}
    for delivery in derive_deliveries(store, as_of):
        sub = by_id.get(delivery["subscription_id"])
        notice = notices.get(delivery["notice_id"])
        if sub is None or notice is None:
            problems.append(
                f"delivery {delivery['subscription_id']} -> "
                f"{delivery['notice_id']}: names a missing "
                "subscription or notice")
            continue
        if delivery["principal"] != sub["principal"]:
            problems.append(
                f"delivery {delivery['subscription_id']} -> "
                f"{delivery['notice_id']}: addressed to "
                f"{delivery['principal']}, but the "
                f"subscription belongs to {sub['principal']}")
        principal = access_engine.resolve_principal(
            sub["principal"])
        if not remit_allows(principal, notice):
            problems.append(
                f"delivery {delivery['subscription_id']} -> "
                f"{delivery['notice_id']}: outside "
                f"{sub['principal']}'s remit")
    for alert in store.list_alerts():
        if alert["band"] != pack.ESCALATION_BAND:
            continue
        mine = escalation_for(store, alert, as_of)
        acts = [a for a in store.list_alert_acts(alert["alert_id"])
                if a["as_of"] <= as_of]
        state = "open"
        for act in acts:
            if act["act"] == "acknowledge":
                state = "acknowledged"
            elif act["act"] == "close":
                state = "closed"
        age = (date.fromisoformat(as_of)
               - date.fromisoformat(alert["as_of"])).days
        level = 0
        if state == "open":
            for rung, window in sorted(
                    pack.ESCALATION_WINDOWS.items()):
                if age >= window:
                    level = rung
        if mine["state"] != state or mine["level"] != level \
                or mine["age_days"] != age:
            problems.append(
                f"escalation of {alert['alert_id']}: the "
                f"service reads level {mine['level']} "
                f"({mine['state']}, {mine['age_days']}d) but "
                f"re-performance reads level {level} "
                f"({state}, {age}d)")
    for digest in store.list_digests():
        sub = by_id.get(digest["subscription_id"])
        if sub is None:
            problems.append(
                f"digest {digest['digest_id']}: names "
                f"subscription {digest['subscription_id']}, "
                "which is not in the store")
            continue
        rebuilt = build_digest(store, sub, digest["as_of"])
        for field in ("digest_id", "fingerprint",
                      "deliveries", "counts", "escalations"):
            if rebuilt.model_dump()[field] != digest[field]:
                problems.append(
                    f"digest {digest['digest_id']}: its "
                    f"{field} does not re-perform from the "
                    "record at its generation date")
    return problems
