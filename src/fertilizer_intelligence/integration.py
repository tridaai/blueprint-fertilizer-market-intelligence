"""Webhooks, scoped API tokens and the exchange
ports (R19, roadmap F21-IA1 + F21-IA2).

Three outward surfaces, one discipline — everything
here is an insert-only artefact that a verifier
re-performs:

- **Webhook subscriptions and deliveries.** A
  subscription names an integration, an endpoint and
  the event families it takes. Dispatch folds the
  triggering artefacts — spike alerts, gap-band
  changes, brief publications — and strikes one
  delivery per (subscription, trigger): the payload
  is the artefact read this system's own surfaces
  serve, signed under the subscription's secret.
  The secret is stored to sign and to verify, and
  no read returns it. A subscription silenced by a
  disable act receives nothing struck while it is
  disabled; re-dispatch is idempotent.
- **Scoped API tokens.** A token is issued to an
  integration with stated read scopes; the store
  keeps only its hash. A token read is judged —
  known token, not revoked, kind in scope — and
  every judgement, allowed or refused, lands as a
  decision entry. Revocation is an act; a revoked
  token refuses everything from its date.
- **Exchange ports.** Inbound batches are checked
  against the port's stated contract as a batch:
  one violation quarantines the whole batch, the
  violations are named on the batch artefact, and
  nothing lands. A conforming batch is translated
  at the border — the port's material codes and
  kilotonnes become this system's products and
  tonnes — and lands through the data plane under
  the port's own registered feed. Outbound feeds
  are artefacts whose rows derive from artefacts
  alone, under a checksum.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets as _secrets
from datetime import date

from pydantic import BaseModel

from . import brief_rules as brief_pack
from . import ingest as ingest_engine
from . import integration_rules as pack
from . import movements as movement_engine
from . import supply_rules as supply_pack


def _fingerprint(payload) -> str:
    blob = json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
        default=str).encode()
    return hashlib.sha256(blob).hexdigest()


def _require_date(value: str, field: str) -> None:
    try:
        date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"{field} is not an ISO date: {value!r}") from None


# ---------------------------------------------------------------------------
# Trigger payloads: the artefact reads, as the system's
# own surfaces serve them.
# ---------------------------------------------------------------------------


def alert_payload(store, alert_id: str) -> dict | None:
    alert = store.get_alert(alert_id)
    if alert is None:
        return None
    acts = store.list_alert_acts(alert_id)
    alert = dict(alert)
    alert["acts"] = acts
    alert["state"] = movement_engine.derive_state(acts)
    return alert


def gap_payload(store, gap_id: str) -> dict | None:
    return store.get_gap(gap_id)


def brief_payload(store, brief_id: str) -> dict | None:
    brief = store.get_weekly_brief(brief_id)
    if brief is None:
        return None
    acts = [
        a for a in store.list_publication_acts()
        if a["artefact_kind"] == brief_pack.KIND_BRIEF
        and a["artefact_id"] == brief_id]
    head = acts[-1] if acts else None
    payload = dict(brief)
    payload["publication"] = {
        "act_id": head["act_id"],
        "published_by": head["published_by"],
        "published_at": head["published_at"],
    } if head else None
    return payload


def _triggers(store, as_of: str) -> list[dict]:
    """Every webhook trigger the record holds at a
    date: spike alerts, gap-band changes (a band
    worsening against the cell's previous gap, or a
    first gap that is not comfortable), and brief
    publications. Each carries its kind, its
    artefact id, its own date and its payload."""
    out: list[dict] = []
    for alert in store.list_alerts():
        if alert["rule_id"] == "spike" \
                and alert["as_of"] <= as_of:
            out.append({
                "kind": pack.EVENT_PRICE_ALERT,
                "trigger_id": alert["alert_id"],
                "at": alert["as_of"],
                "payload": alert_payload(store, alert["alert_id"]),
            })
    cells: dict[tuple, list[dict]] = {}
    for gap in store.list_gaps():
        if gap["as_of"] <= as_of:
            cells.setdefault(
                (gap["product"], gap["crop_year"],
                 gap["season"]), []).append(gap)
    for cell_gaps in cells.values():
        ordered = sorted(
            cell_gaps, key=lambda g: (g["as_of"], g["gap_id"]))
        previous = None
        for gap in ordered:
            rank = supply_pack.BAND_RANK[gap["band"]]
            worsened = previous is not None \
                and rank > supply_pack.BAND_RANK[previous["band"]]
            first_hard = previous is None and rank > 0
            if worsened or first_hard:
                out.append({
                    "kind": pack.EVENT_GAP_BAND,
                    "trigger_id": gap["gap_id"],
                    "at": gap["as_of"],
                    "payload": gap_payload(store, gap["gap_id"]),
                })
            previous = gap
    for act in store.list_publication_acts():
        if act["artefact_kind"] != brief_pack.KIND_BRIEF:
            continue
        if act["published_at"] <= as_of:
            out.append({
                "kind": pack.EVENT_BRIEF_PUBLISHED,
                "trigger_id": act["artefact_id"],
                "at": act["published_at"],
                "payload": brief_payload(
                    store, act["artefact_id"]),
            })
    return sorted(
        out, key=lambda t: (t["at"], t["kind"], t["trigger_id"]))


# ---------------------------------------------------------------------------
# Webhook subscriptions, control acts, deliveries.
# ---------------------------------------------------------------------------


class WebhookSubscription(BaseModel):
    subscription_id: str
    fingerprint: str
    integration: str
    endpoint: str
    event_kinds: list[str]
    secret: str
    registered_by: str
    as_of: str
    rules_version: str


class WebhookControl(BaseModel):
    control_id: str
    fingerprint: str
    subscription_id: str
    act: str
    actor: str
    reason: str | None = None
    as_of: str
    rules_version: str


class WebhookDelivery(BaseModel):
    delivery_id: str
    fingerprint: str
    subscription_id: str
    event_kind: str
    trigger_id: str
    trigger_at: str
    dispatched_at: str
    payload: dict
    signature: str
    rules_version: str


def register_webhook(store, integration: str, endpoint: str,
                     event_kinds: list[str], secret: str,
                     registered_by: str,
                     as_of: str) -> WebhookSubscription:
    """Register one webhook subscription. Registering
    the identical subscription again is the same
    artefact, returned — a subscription's identity is
    its integration, endpoint, families and secret."""
    if not integration or not integration.strip():
        raise ValueError("a webhook subscription names "
                         "its integration")
    if not endpoint or not endpoint.strip():
        raise ValueError("a webhook subscription names "
                         "its endpoint")
    if not secret:
        raise ValueError("a webhook subscription carries "
                         "a signing secret")
    if not registered_by or not registered_by.strip():
        raise ValueError("a webhook subscription names "
                         "who registered it")
    _require_date(as_of, "as_of")
    kinds = sorted(set(event_kinds))
    unknown = [k for k in kinds if k not in pack.EVENTS]
    if unknown or not kinds:
        raise ValueError(
            f"event kinds must be drawn from "
            f"{sorted(pack.EVENTS)}: {unknown or 'none given'}")
    fingerprint = _fingerprint({
        "integration": integration.strip(),
        "endpoint": endpoint.strip(), "kinds": kinds,
        "secret_sha256": pack.secret_hash(secret),
        "pack": pack.RULES_VERSION,
    })
    subscription = WebhookSubscription(
        subscription_id=f"WHS-{fingerprint[:10]}",
        fingerprint=fingerprint,
        integration=integration.strip(),
        endpoint=endpoint.strip(), event_kinds=kinds,
        secret=secret, registered_by=registered_by.strip(),
        as_of=as_of, rules_version=pack.RULES_VERSION)
    existing = store.get_webhook_subscription(
        subscription.subscription_id)
    if existing is not None:
        return WebhookSubscription(
            **{**existing,
               "secret": store.webhook_subscription_secret(
                   subscription.subscription_id)})
    store.insert_webhook_subscription(subscription.model_dump())
    return subscription


def set_webhook_active(store, subscription_id: str, act: str,
                       actor: str, as_of: str,
                       reason: str | None = None) -> WebhookControl:
    """A disable or enable act on a subscription:
    while the latest act at a date is a disable, the
    subscription receives no deliveries for triggers
    at that date."""
    if store.get_webhook_subscription(subscription_id) is None:
        raise ValueError(
            f"no such webhook subscription: {subscription_id}")
    if act not in pack.CONTROL_ACTS:
        raise ValueError(
            f"a webhook control act is one of "
            f"{sorted(pack.CONTROL_ACTS)}")
    if not actor or not actor.strip():
        raise ValueError("a webhook control act names its actor")
    _require_date(as_of, "as_of")
    fingerprint = _fingerprint({
        "subscription": subscription_id, "act": act,
        "actor": actor.strip(), "reason": reason,
        "as_of": as_of, "pack": pack.RULES_VERSION,
    })
    control = WebhookControl(
        control_id=f"WHC-{fingerprint[:10]}",
        fingerprint=fingerprint,
        subscription_id=subscription_id, act=act,
        actor=actor.strip(), reason=reason, as_of=as_of,
        rules_version=pack.RULES_VERSION)
    if store.get_webhook_control(control.control_id) is None:
        store.insert_webhook_control(control.model_dump())
    return control


def _active_at(store, subscription_id: str, on_date: str) -> bool:
    controls = [
        c for c in store.list_webhook_controls(subscription_id)
        if c["as_of"] <= on_date]
    if not controls:
        return True
    latest = max(controls,
                 key=lambda c: (c["as_of"], c["control_id"]))
    return latest["act"] != pack.ACT_DISABLE


def dispatch_webhooks(store, as_of: str) -> dict:
    """Strike every delivery the record calls for at
    a date: for each subscription, each trigger of a
    subscribed family at or before the date — on or
    after the subscription's registration (a
    subscription never receives events from before
    it existed) and while the subscription stands
    active at the trigger's date. Deliveries already
    struck are left exactly as they stand — dispatch
    is idempotent."""
    _require_date(as_of, "as_of")
    triggers = _triggers(store, as_of)
    struck = 0
    for subscription in store.list_webhook_subscriptions():
        secret = store.webhook_subscription_secret(
            subscription["subscription_id"])
        for trigger in triggers:
            if trigger["kind"] not in subscription["event_kinds"]:
                continue
            if trigger["at"] < subscription["as_of"]:
                continue
            if not _active_at(
                    store, subscription["subscription_id"],
                    trigger["at"]):
                continue
            fingerprint = _fingerprint({
                "subscription": subscription["subscription_id"],
                "kind": trigger["kind"],
                "trigger": trigger["trigger_id"],
                "trigger_at": trigger["at"],
                "payload": trigger["payload"],
                "pack": pack.RULES_VERSION,
            })
            delivery_id = f"WHD-{fingerprint[:10]}"
            if store.get_webhook_delivery(delivery_id) is not None:
                continue
            delivery = WebhookDelivery(
                delivery_id=delivery_id,
                fingerprint=fingerprint,
                subscription_id=subscription["subscription_id"],
                event_kind=trigger["kind"],
                trigger_id=trigger["trigger_id"],
                trigger_at=trigger["at"],
                dispatched_at=as_of,
                payload=trigger["payload"],
                signature=pack.sign(secret, trigger["payload"]),
                rules_version=pack.RULES_VERSION)
            store.insert_webhook_delivery(delivery.model_dump())
            struck += 1
    return {
        "as_of": as_of, "triggers": len(triggers),
        "deliveries_struck": struck,
        "deliveries_total": len(store.list_webhook_deliveries()),
    }


def verify_webhooks(store) -> list[str]:
    """Re-perform the webhook layer: every delivery's
    payload is the artefact read it claims to carry,
    its signature recomputes under the subscription's
    secret, the subscription stood active at the
    trigger's date and takes that family, and the
    delivery set is complete to the latest dispatch
    date on file for each subscription — a missing
    delivery is named, not averaged away."""
    problems: list[str] = []
    deliveries = store.list_webhook_deliveries()
    by_subscription: dict[str, list[dict]] = {}
    for delivery in deliveries:
        by_subscription.setdefault(
            delivery["subscription_id"], []).append(delivery)
        subscription = store.get_webhook_subscription(
            delivery["subscription_id"])
        if subscription is None:
            problems.append(
                f"delivery {delivery['delivery_id']}: its "
                f"subscription {delivery['subscription_id']} "
                "is not in the store")
            continue
        if delivery["event_kind"] \
                not in subscription["event_kinds"]:
            problems.append(
                f"delivery {delivery['delivery_id']}: the "
                f"subscription does not take "
                f"{delivery['event_kind']}")
        if not _active_at(store, delivery["subscription_id"],
                          delivery["trigger_at"]):
            problems.append(
                f"delivery {delivery['delivery_id']}: the "
                "subscription stood disabled at the "
                "trigger's date")
        rebuilt = _fingerprint({
            "subscription": delivery["subscription_id"],
            "kind": delivery["event_kind"],
            "trigger": delivery["trigger_id"],
            "trigger_at": delivery["trigger_at"],
            "payload": delivery["payload"],
            "pack": pack.RULES_VERSION,
        })
        if rebuilt != delivery["fingerprint"] \
                or delivery["delivery_id"] != f"WHD-{rebuilt[:10]}":
            problems.append(
                f"delivery {delivery['delivery_id']}: its "
                "fingerprint does not match its fields")
        secret = store.webhook_subscription_secret(
            delivery["subscription_id"])
        if secret is None \
                or pack.sign(secret, delivery["payload"]) \
                != delivery["signature"]:
            problems.append(
                f"delivery {delivery['delivery_id']}: its "
                "signature does not verify under the "
                "subscription's secret")
    for subscription in store.list_webhook_subscriptions():
        mine = by_subscription.get(
            subscription["subscription_id"], [])
        if not mine:
            continue
        through = max(d["dispatched_at"] for d in mine)
        expected = {
            (t["kind"], t["trigger_id"])
            for t in _triggers(store, through)
            if t["kind"] in subscription["event_kinds"]
            and t["at"] >= subscription["as_of"]
            and _active_at(store, subscription["subscription_id"],
                           t["at"])}
        struck = {(d["event_kind"], d["trigger_id"]) for d in mine}
        for kind, trigger_id in sorted(expected - struck):
            problems.append(
                f"subscription {subscription['subscription_id']}: "
                f"no delivery on file for the {kind} trigger "
                f"{trigger_id} though dispatch ran through "
                f"{through}")
        for kind, trigger_id in sorted(struck - expected):
            problems.append(
                f"subscription {subscription['subscription_id']}: "
                f"a delivery stands for the {kind} trigger "
                f"{trigger_id}, which the record does not "
                "call for")
    return problems


# ---------------------------------------------------------------------------
# Scoped API tokens: issued, judged, revoked — every
# read leaves a decision entry.
# ---------------------------------------------------------------------------


class ApiToken(BaseModel):
    token_id: str
    fingerprint: str
    integration: str
    scopes: list[str]
    secret_sha256: str
    issued_by: str
    issued_at: str
    rules_version: str


class ApiTokenAct(BaseModel):
    act_id: str
    fingerprint: str
    token_id: str
    act: str
    actor: str
    reason: str | None = None
    as_of: str
    rules_version: str


class TokenDecision(BaseModel):
    decision_id: str
    fingerprint: str
    token_id: str | None
    integration: str | None
    kind: str
    target: str
    decision: str
    reason: str
    result_present: bool
    at: str
    # The revocation acts on file when the judgement
    # was made — the decision binds the acts it
    # judged under, so the verifier re-judges from
    # exactly those, never from acts struck later.
    acts_seen: list[str] = []
    rules_version: str


def issue_api_token(store, integration: str, scopes: list[str],
                    issued_by: str, issued_at: str,
                    secret: str | None = None) -> tuple[dict, str]:
    """Issue one scoped token. Returns the stored
    artefact — which carries the token's hash, never
    the token — and the token itself, once: the
    plaintext exists in the caller's hands and in no
    table. Issuing the identical token again (same
    integration, scopes and secret) is the same
    artefact."""
    if not integration or not integration.strip():
        raise ValueError("an API token names its integration")
    if not issued_by or not issued_by.strip():
        raise ValueError("an API token names who issued it")
    _require_date(issued_at, "issued_at")
    scope_list = sorted(set(scopes))
    unknown = [s for s in scope_list if s not in pack.SCOPES]
    if unknown or not scope_list:
        raise ValueError(
            f"token scopes must be drawn from "
            f"{sorted(pack.SCOPES)}: {unknown or 'none given'}")
    plaintext = secret if secret is not None \
        else _secrets.token_urlsafe(32)
    fingerprint = _fingerprint({
        "integration": integration.strip(),
        "scopes": scope_list,
        "secret_sha256": pack.secret_hash(plaintext),
        "pack": pack.RULES_VERSION,
    })
    token = ApiToken(
        token_id=f"TOK-{fingerprint[:10]}",
        fingerprint=fingerprint,
        integration=integration.strip(), scopes=scope_list,
        secret_sha256=pack.secret_hash(plaintext),
        issued_by=issued_by.strip(), issued_at=issued_at,
        rules_version=pack.RULES_VERSION)
    if store.get_api_token(token.token_id) is None:
        store.insert_api_token(token.model_dump())
    return store.get_api_token(token.token_id), plaintext


def revoke_api_token(store, token_id: str, actor: str,
                     as_of: str,
                     reason: str | None = None) -> ApiTokenAct:
    """The revocation act: from its date, the token
    refuses everything. Revocation is an act, not an
    edit — the token artefact stands as issued."""
    if store.get_api_token(token_id) is None:
        raise ValueError(f"no such API token: {token_id}")
    if not actor or not actor.strip():
        raise ValueError("a revocation names its actor")
    _require_date(as_of, "as_of")
    fingerprint = _fingerprint({
        "token": token_id, "act": pack.ACT_REVOKE,
        "actor": actor.strip(), "reason": reason,
        "as_of": as_of, "pack": pack.RULES_VERSION,
    })
    act = ApiTokenAct(
        act_id=f"TKA-{fingerprint[:10]}",
        fingerprint=fingerprint, token_id=token_id,
        act=pack.ACT_REVOKE, actor=actor.strip(),
        reason=reason, as_of=as_of,
        rules_version=pack.RULES_VERSION)
    if store.get_api_token_act(act.act_id) is None:
        store.insert_api_token_act(act.model_dump())
    return act


def _token_by_secret(store, presented: str) -> dict | None:
    digest = pack.secret_hash(presented)
    for token in store.list_api_tokens():
        if token["secret_sha256"] == digest:
            return token
    return None


def _revoked_at(store, token_id: str, on_date: str,
                acts: list[dict] | None = None) -> bool:
    pool = acts if acts is not None \
        else store.list_api_token_acts(token_id)
    return any(
        act["act"] == pack.ACT_REVOKE and act["as_of"] <= on_date
        for act in pool)


def _judge_token_read(store, token: dict | None, kind: str,
                      at: str,
                      acts: list[dict] | None = None) -> tuple[str, str]:
    """The scope judgement, as a pure function of the
    token artefact and its acts: the decision and the
    stated reason. The verifier re-judges by this
    same function over the acts the decision records
    having seen."""
    if token is None:
        return (pack.DECISION_REFUSED,
                "the presented token is not one this "
                "system issued")
    if kind not in pack.READ_KINDS:
        return (pack.DECISION_REFUSED,
                f"token reads serve exactly the kinds "
                f"{sorted(pack.READ_KINDS)}")
    if _revoked_at(store, token["token_id"], at, acts):
        return (pack.DECISION_REFUSED,
                "the token stands revoked at this date")
    if pack.KIND_SCOPE[kind] not in token["scopes"]:
        return (pack.DECISION_REFUSED,
                f"the token's scopes {token['scopes']} do "
                f"not cover the {kind} read family")
    return (pack.DECISION_ALLOWED,
            "the token is live and its scopes cover "
            "the read")


def token_read(store, presented: str, kind: str,
               target_id: str, at: str) -> tuple[dict, dict | None]:
    """One token-guarded read. The judgement is made
    and recorded first — every presented read leaves
    its decision entry, allowed or refused — and the
    artefact read is served only on an allowed
    judgement. A missing artefact under a live,
    in-scope token reads as absent, exactly like the
    desk's guarded reads."""
    _require_date(at, "at")
    token = _token_by_secret(store, presented)
    acts = store.list_api_token_acts(token["token_id"]) \
        if token else []
    decision, reason = _judge_token_read(
        store, token, kind, at, acts)
    payload = None
    if decision == pack.DECISION_ALLOWED:
        if kind == pack.KIND_ALERT:
            payload = alert_payload(store, target_id)
        elif kind == pack.KIND_GAP:
            payload = gap_payload(store, target_id)
        else:
            payload = brief_payload(store, target_id)
    acts_seen = [act["act_id"] for act in acts]
    fingerprint = _fingerprint({
        "token": token["token_id"] if token else None,
        "kind": kind, "target": target_id,
        "decision": decision, "reason": reason,
        "result_present": payload is not None,
        "at": at, "acts_seen": acts_seen,
        "pack": pack.RULES_VERSION,
    })
    entry = TokenDecision(
        decision_id=f"TKD-{fingerprint[:10]}",
        fingerprint=fingerprint,
        token_id=token["token_id"] if token else None,
        integration=token["integration"] if token else None,
        kind=kind, target=target_id, decision=decision,
        reason=reason, result_present=payload is not None,
        at=at, acts_seen=acts_seen,
        rules_version=pack.RULES_VERSION)
    if store.get_token_decision(entry.decision_id) is None:
        store.insert_token_decision(entry.model_dump())
    return store.get_token_decision(entry.decision_id), payload


def verify_tokens(store) -> list[str]:
    """Re-perform the token layer: token artefacts
    recompute and hold a hash, never a secret; acts
    name live tokens; and every decision entry
    re-judges from the token artefact and its acts
    at the entry's own date, with its recorded
    result presence matching the artefact's
    existence in the store."""
    problems: list[str] = []
    for token in store.list_api_tokens():
        if "secret" in token:
            problems.append(
                f"token {token['token_id']}: the artefact "
                "carries a secret field — only its hash "
                "may be stored")
        unknown = [s for s in token["scopes"]
                   if s not in pack.SCOPES]
        if unknown or not token["scopes"]:
            problems.append(
                f"token {token['token_id']}: scopes "
                f"{token['scopes']} are outside the "
                "pack's vocabulary")
        rebuilt = _fingerprint({
            "integration": token["integration"],
            "scopes": token["scopes"],
            "secret_sha256": token["secret_sha256"],
            "pack": pack.RULES_VERSION,
        })
        if rebuilt != token["fingerprint"] \
                or token["token_id"] != f"TOK-{rebuilt[:10]}":
            problems.append(
                f"token {token['token_id']}: its "
                "fingerprint does not match its fields")
    for act in store.list_api_token_acts():
        if store.get_api_token(act["token_id"]) is None:
            problems.append(
                f"token act {act['act_id']}: names token "
                f"{act['token_id']}, which is not in "
                "the store")
    for entry in store.list_token_decisions():
        token = store.get_api_token(entry["token_id"]) \
            if entry["token_id"] else None
        # The decision binds the acts it judged under.
        # The verifier grades the binding first — every
        # act dated before the read must be in it, no
        # act dated after it may be, and no act outside
        # the token's own record may be named — then
        # re-judges from exactly the bound acts. An act
        # dated the same day as the read may honestly
        # be in or out: it was struck before the read
        # or after it, and the binding is the record
        # of which.
        all_acts = store.list_api_token_acts(
            entry["token_id"]) if entry["token_id"] else []
        by_id = {a["act_id"]: a for a in all_acts}
        seen = list(entry.get("acts_seen") or [])
        unknown_seen = [a for a in seen if a not in by_id]
        if unknown_seen:
            problems.append(
                f"token decision {entry['decision_id']}: "
                f"names acts {unknown_seen} that are not "
                "on the token's record")
        missing_earlier = [
            a["act_id"] for a in all_acts
            if a["as_of"] < entry["at"]
            and a["act_id"] not in seen]
        if missing_earlier:
            problems.append(
                f"token decision {entry['decision_id']}: "
                f"acts dated before the read are missing "
                f"from its binding: {missing_earlier}")
        later_included = [
            a["act_id"] for a in all_acts
            if a["as_of"] > entry["at"]
            and a["act_id"] in seen]
        if later_included:
            problems.append(
                f"token decision {entry['decision_id']}: "
                f"acts dated after the read are bound "
                f"into its judgement: {later_included}")
        seen_acts = [by_id[a] for a in seen if a in by_id]
        decision, reason = _judge_token_read(
            store, token, entry["kind"], entry["at"],
            seen_acts)
        if decision != entry["decision"] \
                or reason != entry["reason"]:
            problems.append(
                f"token decision {entry['decision_id']}: "
                f"recorded {entry['decision']} "
                f"({entry['reason']}), the re-judgement "
                f"says {decision} ({reason})")
        if entry["decision"] == pack.DECISION_ALLOWED:
            payload = None
            if entry["kind"] == pack.KIND_ALERT:
                payload = alert_payload(store, entry["target"])
            elif entry["kind"] == pack.KIND_GAP:
                payload = gap_payload(store, entry["target"])
            elif entry["kind"] == pack.KIND_BRIEF:
                payload = brief_payload(store, entry["target"])
            if (payload is not None) != entry["result_present"]:
                problems.append(
                    f"token decision {entry['decision_id']}: "
                    "its recorded result presence does not "
                    "match the artefact's existence")
        rebuilt = _fingerprint({
            "token": entry["token_id"], "kind": entry["kind"],
            "target": entry["target"],
            "decision": entry["decision"],
            "reason": entry["reason"],
            "result_present": entry["result_present"],
            "at": entry["at"],
            "acts_seen": list(entry.get("acts_seen") or []),
            "pack": pack.RULES_VERSION,
        })
        if rebuilt != entry["fingerprint"] \
                or entry["decision_id"] != f"TKD-{rebuilt[:10]}":
            problems.append(
                f"token decision {entry['decision_id']}: "
                "its fingerprint does not match its fields")
    return problems


# ---------------------------------------------------------------------------
# Exchange ports: contract first, translation at the
# border, feeds out under checksum.
# ---------------------------------------------------------------------------


class ExchangeBatch(BaseModel):
    batch_id: str
    fingerprint: str
    port: str
    outcome: str
    loaded_by: str
    as_of: str
    rows: list
    violations: list[dict]
    ingest_batch_id: str | None = None
    counts: dict | None = None
    rules_version: str


class ExchangeFeed(BaseModel):
    feed_id: str
    fingerprint: str
    port: str
    as_of: str
    struck_by: str
    rows: list[dict]
    row_count: int
    checksum: str
    rules_version: str


_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) \
        and not isinstance(value, bool)


def check_contract(port: str, rows) -> list[dict]:
    """Grade one inbound batch against its port's
    stated contract, in the external shape: every
    violation found, named by kind and row. An empty
    list is a conforming batch."""
    contract = pack.PORT_CONTRACTS[port]
    violations: list[dict] = []

    def flag(index, kind, detail):
        violations.append({
            "row_index": index, "violation": kind,
            "detail": detail})

    if not isinstance(rows, list) or not rows:
        flag(None, pack.V_EMPTY_BATCH,
             "the batch carries no rows")
        return violations
    source_entry = pack.PORT_SOURCES[port]
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            flag(index, pack.V_MALFORMED_ROW,
                 "row is not an object")
            continue
        missing = [f for f in contract["required"]
                   if row.get(f) is None
                   or (isinstance(row.get(f), str)
                       and not row.get(f))]
        if missing:
            flag(index, pack.V_MISSING_FIELD,
                 f"missing fields: {', '.join(missing)}")
            continue
        unknown = sorted(set(row) - set(contract["required"]))
        if unknown:
            flag(index, pack.V_UNKNOWN_FIELD,
                 f"fields outside the contract: "
                 f"{', '.join(unknown)}")
        if row["material_code"] not in pack.MATERIAL_MAP:
            flag(index, pack.V_UNKNOWN_MATERIAL,
                 f"material code {row['material_code']!r} "
                 "is not in the port's material map")
        for field in contract["quantities"]:
            if not _is_number(row[field]):
                flag(index, pack.V_MALFORMED_ROW,
                     f"{field} is not a number")
            elif row[field] < 0:
                flag(index, pack.V_NEGATIVE_QUANTITY,
                     f"{field} {row[field]} is negative")
        for field in contract["period_fields"]:
            if not isinstance(row[field], str) \
                    or not _PERIOD_RE.match(row[field]):
                flag(index, pack.V_MALFORMED_PERIOD,
                     f"{field} {row[field]!r} is not a "
                     "YYYY-MM period")
        if row["source"] != source_entry["provenance_source"]:
            flag(index, pack.V_SOURCE_MISMATCH,
                 f"row carries source {row['source']!r}, "
                 f"the port is registered as "
                 f"{source_entry['provenance_source']!r}")
        if port == pack.PORT_DISPATCH_IN \
                and row["season"] not in ("kharif", "rabi"):
            flag(index, pack.V_MALFORMED_ROW,
                 f"season {row['season']!r} is not a "
                 "tracked season")
    return violations


def translate_row(port: str, row: dict) -> dict:
    """One conforming external row in this system's
    shape: the port's material code becomes the
    tracked product, its kilotonnes become tonnes.
    The translation is stated here and nowhere else,
    so the verifier re-performs it exactly."""
    product = pack.MATERIAL_MAP[row["material_code"]]
    if port == pack.PORT_PRODUCTION_IN:
        return {
            "product": product, "month": row["period"],
            "planned_tonnes": round(
                row["planned_qty_kt"]
                * pack.QTY_FACTOR_TO_TONNES, 3),
            "actual_tonnes": round(
                row["actual_qty_kt"]
                * pack.QTY_FACTOR_TO_TONNES, 3),
            "source": row["source"], "as_of": row["as_of"],
        }
    return {
        "district_id": row["district_code"],
        "crop_year": row["crop_year"],
        "season": row["season"], "product": product,
        "actual_kind": "dispatch",
        "quantity_tonnes": round(
            row["dispatched_qty_kt"]
            * pack.QTY_FACTOR_TO_TONNES, 3),
        "source": row["source"], "as_of": row["as_of"],
    }


def import_exchange_batch(store, port: str, rows,
                          loaded_by: str,
                          as_of: str) -> ExchangeBatch:
    """Land one inbound exchange batch. The contract
    is graded first, as a batch: any violation
    quarantines the whole batch — the artefact
    records the violations and nothing is offered
    to the data plane. A conforming batch is
    translated and lands through the connector path
    under the port's registered feed, and the
    artefact binds the ingest batch it produced.
    Re-presenting the identical batch is the same
    artefact, returned."""
    if port not in pack.INBOUND_PORTS:
        raise ValueError(
            f"{port!r} is not an inbound exchange port")
    if not loaded_by or not loaded_by.strip():
        raise ValueError("an exchange batch names its loader")
    _require_date(as_of, "as_of")
    fingerprint = _fingerprint({
        "port": port, "rows": rows,
        "loaded_by": loaded_by.strip(), "as_of": as_of,
        "pack": pack.RULES_VERSION,
    })
    batch_id = f"EXB-{fingerprint[:10]}"
    existing = store.get_exchange_batch(batch_id)
    if existing is not None:
        return ExchangeBatch(**existing)
    violations = check_contract(port, rows)
    if violations:
        batch = ExchangeBatch(
            batch_id=batch_id, fingerprint=fingerprint,
            port=port,
            outcome=pack.OUTCOME_QUARANTINED_WHOLE,
            loaded_by=loaded_by.strip(), as_of=as_of,
            rows=rows, violations=violations,
            rules_version=pack.RULES_VERSION)
        store.insert_exchange_batch(batch.model_dump())
        return batch
    translated = [translate_row(port, row) for row in rows]
    report = ingest_engine.load_batch(
        store, port, translated, loaded_by.strip(), as_of,
        source_entry_override=pack.PORT_SOURCES[port])
    batch = ExchangeBatch(
        batch_id=batch_id, fingerprint=fingerprint,
        port=port, outcome=pack.OUTCOME_LANDED,
        loaded_by=loaded_by.strip(), as_of=as_of,
        rows=rows, violations=[],
        ingest_batch_id=report["batch_id"],
        counts={key: report[key] for key in (
            "received", "inserted", "duplicates",
            "quarantined", "refused")},
        rules_version=pack.RULES_VERSION)
    store.insert_exchange_batch(batch.model_dump())
    return batch


def _feed_rows(store, port: str, as_of: str) -> list[dict]:
    if port == pack.PORT_BRIEF_FEED_OUT:
        rows = []
        briefs: dict[str, dict] = {}
        for act in store.list_publication_acts():
            if act["artefact_kind"] != brief_pack.KIND_BRIEF \
                    or act["published_at"] > as_of:
                continue
            briefs[act["artefact_id"]] = act
        for brief_id, act in sorted(briefs.items()):
            brief = store.get_weekly_brief(brief_id)
            if brief is None:
                continue
            rows.append({
                "brief_id": brief_id,
                "week_ending": brief["week_ending"],
                "published_by": act["published_by"],
                "published_at": act["published_at"],
                "act_id": act["act_id"],
            })
        return rows
    rows = []
    for alert in store.list_alerts():
        if alert["as_of"] > as_of:
            continue
        acts = store.list_alert_acts(alert["alert_id"])
        rows.append({
            "alert_id": alert["alert_id"],
            "series_kind": alert["series_kind"],
            "item": alert["item"],
            "rule_id": alert["rule_id"],
            "band": alert["band"],
            "period_month": alert["period_month"],
            "state": movement_engine.derive_state(acts),
            "as_of": alert["as_of"],
        })
    return sorted(rows, key=lambda r: r["alert_id"])


def strike_exchange_feed(store, port: str, as_of: str,
                         struck_by: str) -> ExchangeFeed:
    """Strike one outbound feed artefact: its rows
    derived from the artefacts of record at the
    date, under a checksum over their canonical
    form. The same feed struck again is the same
    artefact."""
    if port not in pack.OUTBOUND_PORTS:
        raise ValueError(
            f"{port!r} is not an outbound exchange port")
    if not struck_by or not struck_by.strip():
        raise ValueError("an exchange feed names who struck it")
    _require_date(as_of, "as_of")
    rows = _feed_rows(store, port, as_of)
    fingerprint = _fingerprint({
        "port": port, "as_of": as_of, "rows": rows,
        "pack": pack.RULES_VERSION,
    })
    feed = ExchangeFeed(
        feed_id=f"EXF-{fingerprint[:10]}",
        fingerprint=fingerprint, port=port, as_of=as_of,
        struck_by=struck_by.strip(), rows=rows,
        row_count=len(rows), checksum=pack.checksum(rows),
        rules_version=pack.RULES_VERSION)
    if store.get_exchange_feed(feed.feed_id) is None:
        store.insert_exchange_feed(feed.model_dump())
    return feed


def verify_exchange(store) -> list[str]:
    """Re-perform the exchange layer: a landed
    batch's contract re-grades clean, its ingest
    batch stands with the translated rows and the
    recorded counts; a whole-quarantined batch's
    violations re-derive and no unclaimed ingest
    batch exists for its translation (an ingest
    batch a landed exchange batch claims as its own
    product explains its rows' landing — this batch
    landed nothing); a feed's rows re-derive from
    the artefacts at its date and its checksum
    recomputes."""
    problems: list[str] = []
    claimed = {
        b["ingest_batch_id"]
        for b in store.list_exchange_batches()
        if b["outcome"] == pack.OUTCOME_LANDED
        and b["ingest_batch_id"]}
    for batch in store.list_exchange_batches():
        rebuilt = _fingerprint({
            "port": batch["port"], "rows": batch["rows"],
            "loaded_by": batch["loaded_by"],
            "as_of": batch["as_of"],
            "pack": pack.RULES_VERSION,
        })
        if rebuilt != batch["fingerprint"] \
                or batch["batch_id"] != f"EXB-{rebuilt[:10]}":
            problems.append(
                f"exchange batch {batch['batch_id']}: its "
                "fingerprint does not match its fields")
        violations = check_contract(batch["port"], batch["rows"])
        if batch["outcome"] == pack.OUTCOME_QUARANTINED_WHOLE:
            if violations != batch["violations"]:
                problems.append(
                    f"exchange batch {batch['batch_id']}: "
                    "its recorded violations do not "
                    "re-derive from its rows")
            translated = []
            if batch["rows"] and all(
                    isinstance(r, dict) for r in batch["rows"]):
                try:
                    translated = [
                        translate_row(batch["port"], r)
                        for r in batch["rows"]
                        if r.get("material_code")
                        in pack.MATERIAL_MAP]
                except (KeyError, TypeError):
                    translated = []
            would_be = ingest_engine._fingerprint({
                "source_id": batch["port"],
                "fact_class":
                    pack.PORT_SOURCES[batch["port"]]["fact_class"],
                "loaded_by": batch["loaded_by"],
                "load_date": batch["as_of"],
                "rows": translated})
            standing = store.ingest_batch_by_fingerprint(
                would_be) if translated else None
            if standing is not None \
                    and standing["batch_id"] not in claimed:
                problems.append(
                    f"exchange batch {batch['batch_id']}: "
                    "quarantined whole, yet an ingest "
                    "batch stands for its translation "
                    "that no landed exchange batch claims")
        elif batch["outcome"] == pack.OUTCOME_LANDED:
            if violations:
                problems.append(
                    f"exchange batch {batch['batch_id']}: "
                    "recorded as landed, but its rows no "
                    "longer grade clean against the "
                    "contract")
            report = store.get_ingest_batch(
                batch["ingest_batch_id"])
            if report is None:
                problems.append(
                    f"exchange batch {batch['batch_id']}: "
                    f"its ingest batch "
                    f"{batch['ingest_batch_id']} is not in "
                    "the store")
            else:
                if batch["counts"] != {
                        key: report[key] for key in (
                            "received", "inserted",
                            "duplicates", "quarantined",
                            "refused")}:
                    problems.append(
                        f"exchange batch {batch['batch_id']}: "
                        "its counts disagree with the "
                        "ingest batch it produced")
                fact_class = \
                    pack.PORT_SOURCES[batch["port"]]["fact_class"]
                landed = set(report["inserted_keys"]) \
                    | set(report["duplicate_keys"])
                held = {h["natural_key"]
                        for h in report["quarantine"]}
                for row in batch["rows"]:
                    content = ingest_engine._content(
                        fact_class,
                        translate_row(batch["port"], row))
                    label = ingest_engine.pack.key_label(
                        fact_class,
                        ingest_engine.pack.natural_key(
                            fact_class, content))
                    if label not in landed | held:
                        problems.append(
                            f"exchange batch "
                            f"{batch['batch_id']}: translated "
                            f"row {label} is neither landed "
                            "nor held in its ingest batch")
        else:
            problems.append(
                f"exchange batch {batch['batch_id']}: "
                f"outcome {batch['outcome']!r} is outside "
                "the pack's vocabulary")
    for feed in store.list_exchange_feeds():
        rows = _feed_rows(store, feed["port"], feed["as_of"])
        if rows != feed["rows"]:
            problems.append(
                f"exchange feed {feed['feed_id']}: its "
                "rows do not re-derive from the artefacts "
                "at its date")
        if pack.checksum(feed["rows"]) != feed["checksum"]:
            problems.append(
                f"exchange feed {feed['feed_id']}: its "
                "checksum does not recompute over its rows")
        if feed["row_count"] != len(feed["rows"]):
            problems.append(
                f"exchange feed {feed['feed_id']}: its "
                "row count disagrees with its rows")
    return problems
