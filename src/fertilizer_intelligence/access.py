"""Regional role scopes & the access audit log (R15,
roadmap F21-AS1).

The guard stands in front of the surfaces the roadmap
names as sensitive — competitor reads and export packs —
and in front of the district register a regional reader
enumerates. Its discipline is the repo's discipline
applied to readers instead of artefacts:

- **Decisions are computed from a versioned pack.**
  Who a reader is, what their role may see and how a
  scope decision falls out are all pack data
  (``access_rules``). The judge is a pure function of
  the pack, the district register and the read's target.
- **Out of scope reads as absent.** A guarded read
  whose target sits outside the reader's remit returns
  exactly what a missing artefact returns — ``None``
  from a single read, absence from a list. The surface
  never says "exists but not yours"; existence is
  itself information, and a regional reader must not
  be able to enumerate another region's districts or
  competitor positions by probing.
- **Every decision leaves an entry.** Allowed, hidden
  and refused decisions alike append an insert-only
  access entry binding the principal, the surface, the
  target and the pack version. The log is the audit:
  export entries reconcile one-to-one with export pack
  artefacts, and any entry can be re-decided from the
  pack by an independent route — a tampered decision
  or a forged entry does not verify.
"""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel

from . import access_rules as pack


class AccessEntry(BaseModel):
    entry_id: str
    fingerprint: str
    principal: str
    role: str
    surface: str
    target: str
    district_id: str | None = None
    region: str | None = None
    product: str | None = None
    decision: str
    reason: str
    at: str
    rules_version: str


def _fingerprint(payload: dict) -> str:
    blob = json.dumps(
        payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------------------
# Principals & decisions: pure functions of the pack and
# the district register.
# ---------------------------------------------------------------------------


def resolve_principal(name: str) -> dict:
    """A reader's judged identity: their register entry,
    or the pack's stated unregistered default — the
    narrowest role, never more."""
    entry = pack.PRINCIPALS.get(name)
    if entry is None:
        return {"name": name, "registered": False,
                **pack.UNREGISTERED}
    return {"name": name, "registered": True, **entry}


def region_of(store, district_id: str | None) -> str | None:
    if district_id is None:
        return None
    for district in store.list_districts():
        if district["district_id"] == district_id:
            return district["region"]
    return None


def decide(store, principal: dict, surface: str,
           district_id: str | None = None,
           product: str | None = None,
           region: str | None = None,
           subscriber: str | None = None,
           reach_products: tuple = (),
           reach_regions: tuple = ()) -> dict:
    """One scope decision, judged from the pack. Returns
    the decision and the stated reason for it. A read's
    geography arrives as a district (resolved to its
    region from the register) or as a region directly —
    competitor observations are struck per region. The
    subscription surface (R16) is judged on the
    subscriber it names and the reach it asks for,
    carried in the extra arguments."""
    role = principal["role"]
    if surface == pack.SURFACE_EXPORT:
        return {"decision": pack.DECISION_ALLOWED,
                "reason": "exports are open to any named "
                          "exporter and audited by entry"}
    if surface == pack.SURFACE_DISTRICT_LIST:
        return {"decision": pack.DECISION_ALLOWED,
                "reason": "the district list is filtered "
                          "to the reader's regions"}
    if surface == pack.SURFACE_SUBSCRIPTION:
        sub = resolve_principal(subscriber) \
            if subscriber else None
        if sub is None or not sub["registered"] \
                or sub["role"] == pack.ROLE_VIEWER:
            return {"decision": pack.DECISION_REFUSED,
                    "reason": "subscriptions are not open "
                              "to viewers or unregistered "
                              "names"}
        if principal["name"] != subscriber \
                and role != pack.ROLE_STRATEGY:
            return {"decision": pack.DECISION_REFUSED,
                    "reason": "a subscription is struck "
                              "by its subscriber or by the "
                              "strategy desk"}
        if sub["role"] == pack.ROLE_PRODUCT \
                and reach_products \
                and not set(reach_products) \
                <= set(sub["products"]):
            return {"decision": pack.DECISION_REFUSED,
                    "reason": "the subscription reaches "
                              "products outside the "
                              "subscriber's remit"}
        if sub["role"] == pack.ROLE_REGIONAL \
                and reach_regions \
                and not set(reach_regions) \
                <= set(sub["regions"]):
            return {"decision": pack.DECISION_REFUSED,
                    "reason": "the subscription reaches "
                              "regions outside the "
                              "subscriber's remit"}
        return {"decision": pack.DECISION_ALLOWED,
                "reason": "the subscription sits inside "
                          "the subscriber's remit"}
    if surface == pack.SURFACE_ALERT_READ:
        if role == pack.ROLE_VIEWER:
            return {"decision": pack.DECISION_REFUSED,
                    "reason": "alert surfaces are closed "
                              "to viewers"}
        if role == pack.ROLE_STRATEGY:
            return {"decision": pack.DECISION_ALLOWED,
                    "reason": "strategy reads the whole book"}
        if role == pack.ROLE_PRODUCT:
            if product is not None \
                    and product in principal["products"]:
                return {"decision": pack.DECISION_ALLOWED,
                        "reason": "the alert's item is in "
                                  "the reader's remit"}
            return {"decision": pack.DECISION_HIDDEN,
                    "reason": "the alert's item is outside "
                              "the reader's remit"}
        if role == pack.ROLE_REGIONAL:
            judged_region = region if region is not None \
                else region_of(store, district_id)
            if judged_region is not None \
                    and judged_region in principal["regions"]:
                return {"decision": pack.DECISION_ALLOWED,
                        "reason": "the alert's geography is "
                                  "in the reader's region"}
            return {"decision": pack.DECISION_HIDDEN,
                    "reason": "the alert carries no "
                              "geography inside the "
                              "reader's regions"}
    if surface == pack.SURFACE_COMPETITOR:
        if role == pack.ROLE_VIEWER:
            return {"decision": pack.DECISION_REFUSED,
                    "reason": "competitor surfaces are "
                              "closed to viewers"}
        if role == pack.ROLE_STRATEGY:
            return {"decision": pack.DECISION_ALLOWED,
                    "reason": "strategy reads the whole book"}
        if role == pack.ROLE_PRODUCT:
            if product is not None \
                    and product in principal["products"]:
                return {"decision": pack.DECISION_ALLOWED,
                        "reason": "the product is in the "
                                  "reader's remit"}
            return {"decision": pack.DECISION_HIDDEN,
                    "reason": "the product is outside the "
                              "reader's remit"}
        if role == pack.ROLE_REGIONAL:
            judged_region = region if region is not None \
                else region_of(store, district_id)
            if judged_region is not None \
                    and judged_region in principal["regions"]:
                return {"decision": pack.DECISION_ALLOWED,
                        "reason": "the district is in the "
                                  "reader's region"}
            return {"decision": pack.DECISION_HIDDEN,
                    "reason": "the district is outside the "
                              "reader's regions"}
    raise ValueError(f"unknown access surface: {surface!r}")


def visible_districts(store, principal: dict) -> list[dict]:
    """The district register as this reader may
    enumerate it: a regional reader's list holds only
    their regions' districts — the other regions'
    districts are not named, counted or hinted at."""
    districts = store.list_districts()
    if principal["role"] == pack.ROLE_REGIONAL:
        return [d for d in districts
                if d["region"] in principal["regions"]]
    return districts


# ---------------------------------------------------------------------------
# The log: insert-only entries, re-derived and verified
# by a second route.
# ---------------------------------------------------------------------------


def build_entry(principal: dict, surface: str, target: str,
                district_id: str | None, product: str | None,
                decision: str, reason: str,
                at: str, region: str | None = None) -> AccessEntry:
    fingerprint = _fingerprint({
        "principal": principal["name"], "role": principal["role"],
        "surface": surface, "target": target,
        "district_id": district_id, "region": region,
        "product": product,
        "decision": decision, "reason": reason, "at": at,
        "pack": pack.RULES_VERSION,
    })
    return AccessEntry(
        entry_id=f"ACC-{fingerprint[:10]}",
        fingerprint=fingerprint, principal=principal["name"],
        role=principal["role"], surface=surface, target=target,
        district_id=district_id, region=region, product=product,
        decision=decision, reason=reason, at=at,
        rules_version=pack.RULES_VERSION)


def record_entry(store, principal_name: str, surface: str,
                 target: str, district_id: str | None,
                 product: str | None, at: str,
                 region: str | None = None,
                 subscriber: str | None = None,
                 reach_products: tuple = (),
                 reach_regions: tuple = ()) -> dict:
    """Judge one guarded action and append its entry.
    Returns the entry and the decision, so the caller
    renders allowed content or the absence shape. An
    identical decision at the same moment is the same
    entry — recording is idempotent, never duplicated.
    A subscription entry (R16) carries its re-decision
    material in the entry's own fields: the subscriber
    in district_id, the reach in product and region as
    comma-joined lists."""
    principal = resolve_principal(principal_name)
    if surface == pack.SURFACE_SUBSCRIPTION:
        district_id = subscriber
        product = ",".join(reach_products) or None
        region = ",".join(reach_regions) or None
    judged = decide(store, principal, surface, district_id,
                    product, region, subscriber,
                    reach_products, reach_regions)
    entry = build_entry(principal, surface, target,
                        district_id, product,
                        judged["decision"], judged["reason"], at,
                        region)
    existing = store.get_access_entry(entry.entry_id)
    if existing is not None:
        return existing
    store.insert_access_entry(entry.model_dump())
    return store.get_access_entry(entry.entry_id)


def derive_access_log(entries: list[dict]) -> list[dict]:
    """The log as read: entries in (at, entry) order
    with a gapless sequence number, derived from the
    entries alone."""
    ordered = sorted(entries, key=lambda e: (e["at"], e["entry_id"]))
    return [{"seq": seq, **entry}
            for seq, entry in enumerate(ordered, start=1)]


def verify_access_log(store) -> list[str]:
    """Re-perform the log by a second route: every
    entry's fingerprint recomputes from its fields,
    every decision re-decides from the pack and the
    register as they stand, and the export entries
    reconcile one-to-one with the export pack
    artefacts — a pack without its entry, an entry
    naming no pack, or two entries for one pack are
    each named."""
    problems: list[str] = []
    entries = store.list_access_entries()
    for entry in entries:
        rebuilt = build_entry(
            resolve_principal(entry["principal"]),
            entry["surface"], entry["target"],
            entry["district_id"], entry["product"],
            entry["decision"], entry["reason"], entry["at"],
            entry.get("region"))
        if rebuilt.entry_id != entry["entry_id"] \
                or rebuilt.fingerprint != entry["fingerprint"]:
            problems.append(
                f"access entry {entry['entry_id']}: its "
                "fingerprint does not match its fields")
        if entry["rules_version"] != pack.RULES_VERSION:
            problems.append(
                f"access entry {entry['entry_id']}: judged "
                f"under pack {entry['rules_version']}, which "
                "this verifier does not re-perform")
            continue
        if entry["surface"] == pack.SURFACE_SUBSCRIPTION:
            judged = decide(
                store, resolve_principal(entry["principal"]),
                entry["surface"], entry["district_id"],
                entry["product"], entry.get("region"),
                subscriber=entry["district_id"],
                reach_products=tuple(entry["product"].split(","))
                if entry["product"] else (),
                reach_regions=tuple(entry["region"].split(","))
                if entry.get("region") else ())
        else:
            judged = decide(store, resolve_principal(entry["principal"]),
                            entry["surface"], entry["district_id"],
                            entry["product"], entry.get("region"))
        if judged["decision"] != entry["decision"]:
            problems.append(
                f"access entry {entry['entry_id']}: recorded "
                f"decision {entry['decision']} does not "
                f"re-decide — the pack says {judged['decision']}")
    packs = store.list_export_packs()
    pack_ids = {p["pack_id"] for p in packs}
    export_entries = [e for e in entries
                      if e["surface"] == pack.SURFACE_EXPORT]
    by_target: dict[str, int] = {}
    for entry in export_entries:
        by_target[entry["target"]] = by_target.get(entry["target"], 0) + 1
        if entry["target"] not in pack_ids:
            problems.append(
                f"access entry {entry['entry_id']}: names "
                f"export pack {entry['target']}, which is "
                "not in the store")
        if entry["decision"] != pack.DECISION_ALLOWED:
            problems.append(
                f"access entry {entry['entry_id']}: an "
                "export that happened was not recorded as "
                "allowed")
    for pack_id in sorted(pack_ids):
        count = by_target.get(pack_id, 0)
        if count == 0:
            problems.append(
                f"export pack {pack_id}: no access entry "
                "records its export")
        elif count > 1:
            problems.append(
                f"export pack {pack_id}: {count} access "
                "entries record its export, not one")
    return problems
