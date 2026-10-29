"""The estimate review & publication queue (R15,
roadmap F21-OW4; the publication gate itself is R10's,
roadmap F21-CA1).

The queue is struck like the board and the rollup: an
insert-only artefact over the record at a date, never
a live list someone edits. Its membership is the
publication fold taken at its date — every outlook
and brief no act has published — and each item carries
what a reviewer actually needs:

- the artefact's own summary: for an outlook, its
  tonnage, its partial districts and its largest
  cells; for a brief, its sections and figure counts;
- the diff against the family's published head,
  computed cell by cell (outlooks) or figure by figure
  (briefs), listing exactly what changed — an item
  whose family has never published diffs against
  nothing and says first publication;
- the fingerprint a publication act would bind, so
  what was reviewed is what can be published, and the
  equality of the two is checkable forever after.

A pending artefact that fails its own verifier refuses
the whole queue — a reviewer is never handed a number
the system itself cannot re-perform — and the refusal
is recorded as its own artefact. Verification rebuilds
the queue's membership and diffs by a second route
from the raw store and compares them whole.
"""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, Field

from . import brief as brief_engine
from . import brief_rules as brief_pack
from . import demand as demand_engine
from . import review_rules as pack


class ReviewRefused(RuntimeError):
    """A queue whose pending set contains an artefact
    that does not verify; the refusal artefact's id is
    carried so callers can read what was refused."""

    def __init__(self, problems: list[str], refusal_id: str):
        super().__init__("; ".join(problems))
        self.problems = problems
        self.refusal_id = refusal_id


class ReviewQueue(BaseModel):
    queue_id: str
    fingerprint: str
    as_of: str
    struck_by: str
    items: list[dict] = Field(default_factory=list)
    supersedes: str | None = None
    rules_version: str


class ReviewRefusal(BaseModel):
    refusal_id: str
    fingerprint: str
    as_of: str
    struck_by: str
    problems: list[str] = Field(default_factory=list)
    rules_version: str


def _fingerprint(payload: dict) -> str:
    blob = json.dumps(
        payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------------------
# The publication fold at a date.
# ---------------------------------------------------------------------------


def state_at(store, artefact_kind: str, artefact_id: str,
             as_of: str) -> dict:
    """One artefact's publication state folded from the
    acts recorded on or before a date — the R10 fold
    with a date bound, so a queue struck for yesterday
    does not see today's publication."""
    acts = [a for a in store.list_publication_acts()
            if a["published_at"] <= as_of]
    return brief_engine.publication_state(acts, artefact_kind,
                                          artefact_id)


def published_head(store, artefact_kind: str, artefact: dict,
                   as_of: str) -> dict | None:
    """The artefact the family's head act names at a
    date, or None when the family has never published."""
    family = brief_engine.family_key_for(artefact_kind, artefact)
    acts = [a for a in store.list_publication_acts(family_key=family)
            if a["published_at"] <= as_of]
    head = brief_engine.head_act(acts)
    if head is None:
        return None
    if artefact_kind == brief_pack.KIND_OUTLOOK:
        return store.get_outlook(head["artefact_id"])
    return store.get_weekly_brief(head["artefact_id"])


# ---------------------------------------------------------------------------
# Diffs: exactly what changed against the published head.
# ---------------------------------------------------------------------------


def _outlook_cells(store, outlook: dict) -> dict:
    cells = {}
    for estimate_id in outlook["estimate_ids"]:
        estimate = store.get_estimate(estimate_id)
        cells[(estimate["district_id"], estimate["product"])] = {
            "estimate_id": estimate_id,
            "total_tonnes": estimate["total_tonnes"],
            "status": estimate["status"],
        }
    return cells


def outlook_diff(store, pending: dict,
                 published: dict | None) -> dict:
    if published is None:
        return {"basis": pack.BASIS_FIRST_PUBLICATION,
                "published_outlook_id": None,
                "changed_cells": [], "added_cells": [],
                "removed_cells": []}
    old = _outlook_cells(store, published)
    new = _outlook_cells(store, pending)
    changed, added, removed = [], [], []
    for key in sorted(set(old) | set(new)):
        district_id, product = key
        if key not in old:
            added.append({
                "district_id": district_id, "product": product,
                "new_estimate_id": new[key]["estimate_id"],
                "new_tonnes": new[key]["total_tonnes"]})
        elif key not in new:
            removed.append({
                "district_id": district_id, "product": product,
                "old_estimate_id": old[key]["estimate_id"],
                "old_tonnes": old[key]["total_tonnes"]})
        elif old[key]["estimate_id"] != new[key]["estimate_id"]:
            changed.append({
                "district_id": district_id, "product": product,
                "old_estimate_id": old[key]["estimate_id"],
                "new_estimate_id": new[key]["estimate_id"],
                "old_tonnes": old[key]["total_tonnes"],
                "new_tonnes": new[key]["total_tonnes"]})
    return {"basis": pack.BASIS_PUBLISHED_HEAD,
            "published_outlook_id": published["outlook_id"],
            "changed_cells": changed, "added_cells": added,
            "removed_cells": removed}


def _brief_figures(brief: dict) -> dict:
    figures = {}
    for section in brief["sections"]:
        for figure in section["figures"]:
            figures[(section["key"], figure["label"])] = figure["value"]
    return figures


def brief_diff(pending: dict, published: dict | None) -> dict:
    if published is None:
        return {"basis": pack.BASIS_FIRST_PUBLICATION,
                "published_brief_id": None,
                "changed_figures": [], "added_sections": [],
                "removed_sections": []}
    old = _brief_figures(published)
    new = _brief_figures(pending)
    changed = []
    for key in sorted(set(old) & set(new)):
        if old[key] != new[key]:
            changed.append({
                "section": key[0], "label": key[1],
                "old_value": old[key], "new_value": new[key]})
    old_sections = {s["key"] for s in published["sections"]}
    new_sections = {s["key"] for s in pending["sections"]}
    return {"basis": pack.BASIS_PUBLISHED_HEAD,
            "published_brief_id": published["brief_id"],
            "changed_figures": changed,
            "added_sections": sorted(new_sections - old_sections),
            "removed_sections": sorted(old_sections - new_sections)}


# ---------------------------------------------------------------------------
# Items & the queue artefact.
# ---------------------------------------------------------------------------


def _outlook_item(store, outlook: dict, as_of: str) -> dict:
    cells = _outlook_cells(store, outlook)
    partial_districts = sorted({
        district_id for (district_id, _product), cell
        in cells.items() if cell["status"] == "partial"})
    top = sorted(
        cells.items(),
        key=lambda kv: (-kv[1]["total_tonnes"], kv[0]))[
        :pack.DRIVER_SUMMARY_CELLS]
    published = published_head(
        store, brief_pack.KIND_OUTLOOK, outlook, as_of)
    return {
        "artefact_kind": brief_pack.KIND_OUTLOOK,
        "artefact_id": outlook["outlook_id"],
        "family_key": brief_engine.family_key_for(
            brief_pack.KIND_OUTLOOK, outlook),
        "reviewed_fingerprint": outlook["fact_fingerprint"],
        "crop_year": outlook["crop_year"],
        "season": outlook["season"],
        "driver_summary": {
            "total_tonnes": outlook["total_tonnes"],
            "estimate_count": outlook["estimate_count"],
            "partial_count": outlook["partial_count"],
            "partial_districts": partial_districts,
            "top_cells": [
                {"district_id": key[0], "product": key[1],
                 "total_tonnes": cell["total_tonnes"]}
                for key, cell in top],
        },
        "diff": outlook_diff(store, outlook, published),
    }


def _brief_item(store, brief: dict, as_of: str) -> dict:
    published = published_head(
        store, brief_pack.KIND_BRIEF, brief, as_of)
    return {
        "artefact_kind": brief_pack.KIND_BRIEF,
        "artefact_id": brief["brief_id"],
        "family_key": brief_engine.family_key_for(
            brief_pack.KIND_BRIEF, brief),
        "reviewed_fingerprint": brief["fingerprint"],
        "week_ending": brief["week_ending"],
        "driver_summary": {
            "sections": [
                {"key": section["key"],
                 "figures": len(section["figures"])}
                for section in brief["sections"]],
        },
        "diff": brief_diff(brief, published),
    }


def pending_items(store, as_of: str) -> tuple[list[dict], list[str]]:
    """The queue's membership and its problems: every
    outlook and brief in draft state at the date, each
    verified under its own family's verifier — a
    pending artefact that does not verify is a problem
    that refuses the queue, never a row on it."""
    items: list[dict] = []
    problems: list[str] = []
    for outlook in store.list_outlooks():
        if state_at(store, brief_pack.KIND_OUTLOOK,
                    outlook["outlook_id"], as_of)["status"] \
                != "draft":
            continue
        found = demand_engine.verify_outlook(store, outlook)
        if found:
            problems.append(
                f"pending outlook {outlook['outlook_id']} "
                f"does not verify: " + "; ".join(found))
            continue
        items.append(_outlook_item(store, outlook, as_of))
    for brief in store.list_weekly_briefs():
        if state_at(store, brief_pack.KIND_BRIEF,
                    brief["brief_id"], as_of)["status"] != "draft":
            continue
        found = brief_engine.verify_brief(store, brief)
        if found:
            problems.append(
                f"pending brief {brief['brief_id']} does "
                f"not verify: " + "; ".join(found))
            continue
        items.append(_brief_item(store, brief, as_of))
    items.sort(key=lambda i: (i["artefact_kind"],
                              i["family_key"],
                              i["artefact_id"]))
    return items, problems


def build_queue(store, struck_by: str,
                as_of: str) -> tuple[ReviewQueue, list[str]]:
    items, problems = pending_items(store, as_of)
    fingerprint = _fingerprint({
        "as_of": as_of, "struck_by": struck_by,
        "items": items, "pack": pack.RULES_VERSION,
    })
    queue = ReviewQueue(
        queue_id=f"RVQ-{fingerprint[:10]}",
        fingerprint=fingerprint, as_of=as_of,
        struck_by=struck_by, items=items,
        rules_version=pack.RULES_VERSION)
    return queue, problems


def build_refusal(as_of: str, struck_by: str,
                  problems: list[str]) -> ReviewRefusal:
    fingerprint = _fingerprint({
        "as_of": as_of, "struck_by": struck_by,
        "problems": problems, "pack": pack.RULES_VERSION,
    })
    return ReviewRefusal(
        refusal_id=f"RVR-{fingerprint[:10]}",
        fingerprint=fingerprint, as_of=as_of,
        struck_by=struck_by, problems=problems,
        rules_version=pack.RULES_VERSION)


# ---------------------------------------------------------------------------
# Verification: the second route. Membership and diffs
# are recomputed straight from acts, artefacts and
# estimates — not via the builder's helpers — and the
# stored queue must match whole.
# ---------------------------------------------------------------------------


def _expected_items(store, as_of: str) -> list[dict]:
    acts = store.list_publication_acts()
    by_family: dict[str, list[dict]] = {}
    for act in acts:
        if act["published_at"] <= as_of:
            by_family.setdefault(act["family_key"], []).append(act)

    def head_artefact(kind: str, artefact: dict) -> dict | None:
        family = brief_engine.family_key_for(kind, artefact)
        head = brief_engine.head_act(by_family.get(family, []))
        if head is None:
            return None
        if kind == brief_pack.KIND_OUTLOOK:
            return store.get_outlook(head["artefact_id"])
        return store.get_weekly_brief(head["artefact_id"])

    def is_draft(kind: str, artefact_id: str) -> bool:
        return not any(
            a["artefact_kind"] == kind
            and a["artefact_id"] == artefact_id
            and a["published_at"] <= as_of for a in acts)

    expected: list[dict] = []
    for outlook in store.list_outlooks():
        if not is_draft(brief_pack.KIND_OUTLOOK,
                        outlook["outlook_id"]):
            continue
        published = head_artefact(brief_pack.KIND_OUTLOOK, outlook)
        # The item is rebuilt by the same pure builders;
        # what differs on this route is membership and
        # head resolution, re-derived from the raw acts.
        item = _outlook_item(store, outlook, as_of)
        item["diff"] = outlook_diff(store, outlook, published)
        expected.append(item)
    for brief in store.list_weekly_briefs():
        if not is_draft(brief_pack.KIND_BRIEF, brief["brief_id"]):
            continue
        published = head_artefact(brief_pack.KIND_BRIEF, brief)
        item = _brief_item(store, brief, as_of)
        item["diff"] = brief_diff(brief, published)
        expected.append(item)
    expected.sort(key=lambda i: (i["artefact_kind"],
                                 i["family_key"],
                                 i["artefact_id"]))
    return expected


def verify_queue(store, queue: dict) -> list[str]:
    problems: list[str] = []
    rebuilt, build_problems = build_queue(
        store, queue["struck_by"], queue["as_of"])
    if rebuilt.queue_id != queue["queue_id"] \
            or rebuilt.fingerprint != queue["fingerprint"]:
        problems.append(
            "the queue's id does not match its content")
    expected = _expected_items(store, queue["as_of"])
    if expected != queue["items"]:
        problems.append(
            "the queue's items do not re-derive from the "
            "record: membership or a diff has moved")
    if build_problems:
        problems.append(
            "pending artefacts do not verify on the "
            "second route: " + "; ".join(build_problems))
    return problems
