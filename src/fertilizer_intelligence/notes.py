"""Annotations & assigned follow-ups (R15, roadmap
F21-CA2).

A comment pinned to an artefact, and a task a named
owner owes the desk, are small things with one strict
discipline — the discipline the whole repo runs on:

- **A pin binds a version.** An annotation records the
  target's kind, its id and the fingerprint of the
  exact stored version, recomputed over the artefact
  as stored at writing time. Artefacts here are
  insert-only, so the pinned version can never change
  under the comment; what can change is its standing.
  When a successor takes the family's head, the
  annotation's read view says so — flagged, never
  moved.
- **A task's state is a fold, never a field.** The
  task artefact is struck once, with its first owner;
  assign, complete and close are insert-only acts, and
  the current owner and state are derived from the
  fold at every read. An act against a terminal task
  is refused at the door and named as a defect if one
  is ever found in the store.
- **Everything re-performs.** The verifier recomputes
  every fingerprint, re-resolves every pin against the
  target as stored now, re-derives every superseded
  flag and re-folds every task by a second route.
"""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel

from . import notes_rules as pack
from .demand import head_of


class FollowupStateError(RuntimeError):
    """An act was attempted against a follow-up task
    whose derived state does not allow it (acting on a
    completed or closed task, acting on a missing
    task)."""


class Annotation(BaseModel):
    annotation_id: str
    fingerprint: str
    target_kind: str
    target_id: str
    target_fingerprint: str
    author: str
    at: str
    text: str
    rules_version: str


class FollowupTask(BaseModel):
    task_id: str
    fingerprint: str
    target_kind: str
    target_id: str
    target_fingerprint: str
    assignee: str
    created_by: str
    at: str
    text: str
    due: str | None = None
    rules_version: str


class FollowupAct(BaseModel):
    act_id: str
    fingerprint: str
    task_id: str
    act: str
    actor: str
    at: str
    assignee: str | None = None
    reason: str | None = None
    note: str | None = None
    rules_version: str


def _fingerprint(payload: dict) -> str:
    blob = json.dumps(
        payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------------------
# Targets: resolution, fingerprints, supersession.
# ---------------------------------------------------------------------------


def get_target(store, target_kind: str,
               target_id: str) -> dict | None:
    if target_kind == pack.KIND_ESTIMATE:
        return store.get_estimate(target_id)
    if target_kind == pack.KIND_GAP:
        return store.get_gap(target_id)
    if target_kind == pack.KIND_ALERT:
        return store.get_alert(target_id)
    raise ValueError(
        f"artefacts of kind {target_kind!r} take no pins — "
        f"the notes pack names {pack.TARGET_KINDS}")


def target_fingerprint(target: dict) -> str:
    """The pin: a fingerprint over the artefact exactly
    as stored, so any later read can prove the comment
    still sits on the version it was written against."""
    return _fingerprint(target)


def target_is_superseded(store, target_kind: str,
                         target: dict) -> bool:
    """Whether a successor has taken the target family's
    head since the pinned version was struck. Alerts
    fold state and never supersede (pack-stated)."""
    if target_kind == pack.KIND_ESTIMATE:
        head = head_of(
            store.list_estimates(
                target["district_id"], target["product"],
                target["crop_year"], target["season"]),
            "estimate_id")
        return head is not None \
            and head["estimate_id"] != target["estimate_id"]
    if target_kind == pack.KIND_GAP:
        head = head_of(
            store.list_gaps(target["product"],
                            target["crop_year"],
                            target["season"]),
            "gap_id")
        return head is not None \
            and head["gap_id"] != target["gap_id"]
    return False


# ---------------------------------------------------------------------------
# Annotations.
# ---------------------------------------------------------------------------


def build_annotation(store, target_kind: str, target_id: str,
                     author: str, at: str,
                     text: str) -> Annotation:
    target = get_target(store, target_kind, target_id)
    if target is None:
        raise ValueError(
            f"no such {target_kind}: {target_id} — an "
            "annotation pins an artefact that exists")
    fingerprint = _fingerprint({
        "target_kind": target_kind, "target_id": target_id,
        "target_fingerprint": target_fingerprint(target),
        "author": author, "at": at, "text": text,
        "pack": pack.RULES_VERSION,
    })
    return Annotation(
        annotation_id=f"ANN-{fingerprint[:10]}",
        fingerprint=fingerprint, target_kind=target_kind,
        target_id=target_id,
        target_fingerprint=target_fingerprint(target),
        author=author, at=at, text=text,
        rules_version=pack.RULES_VERSION)


def annotation_view(store, annotation: dict) -> dict:
    """One annotation as read: the pin, whether the
    pinned version is still the version stored (it
    always is, in an insert-only store — the view
    proves it), and whether a successor has taken the
    family's head."""
    target = get_target(store, annotation["target_kind"],
                        annotation["target_id"])
    return {
        **annotation,
        "target_present": target is not None,
        "target_matches_pin": target is not None
        and target_fingerprint(target)
        == annotation["target_fingerprint"],
        "pinned_to_superseded": target is not None
        and target_is_superseded(
            store, annotation["target_kind"], target),
    }


# ---------------------------------------------------------------------------
# Follow-up tasks: struck once, moved only by acts.
# ---------------------------------------------------------------------------


def build_task(store, target_kind: str, target_id: str,
               assignee: str, created_by: str, at: str,
               text: str, due: str | None) -> FollowupTask:
    target = get_target(store, target_kind, target_id)
    if target is None:
        raise ValueError(
            f"no such {target_kind}: {target_id} — a "
            "follow-up pins an artefact that exists")
    fingerprint = _fingerprint({
        "target_kind": target_kind, "target_id": target_id,
        "target_fingerprint": target_fingerprint(target),
        "assignee": assignee, "created_by": created_by,
        "at": at, "text": text, "due": due,
        "pack": pack.RULES_VERSION,
    })
    return FollowupTask(
        task_id=f"TSK-{fingerprint[:10]}",
        fingerprint=fingerprint, target_kind=target_kind,
        target_id=target_id,
        target_fingerprint=target_fingerprint(target),
        assignee=assignee, created_by=created_by, at=at,
        text=text, due=due, rules_version=pack.RULES_VERSION)


def build_act(task_id: str, act: str, actor: str, at: str,
              assignee: str | None = None,
              reason: str | None = None,
              note: str | None = None) -> FollowupAct:
    if act not in pack.ACTS:
        raise ValueError(
            f"act {act!r} is not a follow-up act — the "
            f"notes pack names {pack.ACTS}")
    if act == pack.ACT_ASSIGN and not assignee:
        raise ValueError(
            "an assign act names the new owner — an "
            "unnamed assignment is refused")
    if act == pack.ACT_CLOSE \
            and reason not in pack.CLOSE_REASONS:
        raise ValueError(
            f"a close speaks a reason from the pack's "
            f"vocabulary {sorted(pack.CLOSE_REASONS)} — "
            f"got {reason!r}")
    fingerprint = _fingerprint({
        "task_id": task_id, "act": act, "actor": actor,
        "at": at, "assignee": assignee, "reason": reason,
        "note": note, "pack": pack.RULES_VERSION,
    })
    return FollowupAct(
        act_id=f"FUA-{fingerprint[:10]}",
        fingerprint=fingerprint, task_id=task_id, act=act,
        actor=actor, at=at, assignee=assignee,
        reason=reason, note=note,
        rules_version=pack.RULES_VERSION)


def derive_state(task: dict, acts: list[dict]) -> dict:
    """The fold: current owner and state from the acts
    alone, in (at, act) order. The struck assignee is
    the owner until an assign act says otherwise; a
    complete or a close ends the task."""
    owner = task["assignee"]
    state = pack.STATE_OPEN
    ordered = sorted(acts, key=lambda a: (a["at"], a["act_id"]))
    for act in ordered:
        if state in pack.TERMINAL_STATES:
            break
        if act["act"] == pack.ACT_ASSIGN:
            owner = act["assignee"]
        elif act["act"] == pack.ACT_COMPLETE:
            state = pack.STATE_COMPLETED
        elif act["act"] == pack.ACT_CLOSE:
            state = pack.STATE_CLOSED
    return {"state": state, "owner": owner,
            "acts": len(ordered)}


def task_view(store, task: dict) -> dict:
    acts = store.list_followup_acts(task["task_id"])
    derived = derive_state(task, acts)
    target = get_target(store, task["target_kind"],
                        task["target_id"])
    return {
        **task, **derived,
        "pinned_to_superseded": target is not None
        and target_is_superseded(
            store, task["target_kind"], target),
    }


# ---------------------------------------------------------------------------
# Verification: a second route over the raw store.
# ---------------------------------------------------------------------------


def verify_notes(store) -> list[str]:
    problems: list[str] = []
    for annotation in store.list_annotations():
        target = get_target(store, annotation["target_kind"],
                            annotation["target_id"])
        if target is None:
            problems.append(
                f"annotation {annotation['annotation_id']}: "
                f"its {annotation['target_kind']} "
                f"{annotation['target_id']} is not in the store")
            continue
        rebuilt = build_annotation(
            store, annotation["target_kind"],
            annotation["target_id"], annotation["author"],
            annotation["at"], annotation["text"])
        if rebuilt.annotation_id != annotation["annotation_id"] \
                or rebuilt.fingerprint != annotation["fingerprint"] \
                or rebuilt.target_fingerprint \
                != annotation["target_fingerprint"]:
            problems.append(
                f"annotation {annotation['annotation_id']}: "
                "its fingerprint or pin does not match its "
                "fields and target")
    tasks = {t["task_id"]: t for t in store.list_followup_tasks()}
    for task in tasks.values():
        target = get_target(store, task["target_kind"],
                            task["target_id"])
        if target is None:
            problems.append(
                f"follow-up {task['task_id']}: its "
                f"{task['target_kind']} {task['target_id']} "
                "is not in the store")
            continue
        rebuilt = build_task(
            store, task["target_kind"], task["target_id"],
            task["assignee"], task["created_by"], task["at"],
            task["text"], task["due"])
        if rebuilt.task_id != task["task_id"] \
                or rebuilt.fingerprint != task["fingerprint"] \
                or rebuilt.target_fingerprint \
                != task["target_fingerprint"]:
            problems.append(
                f"follow-up {task['task_id']}: its "
                "fingerprint or pin does not match its "
                "fields and target")
    for act in store.list_followup_acts():
        if act["task_id"] not in tasks:
            problems.append(
                f"follow-up act {act['act_id']}: names task "
                f"{act['task_id']}, which is not in the store")
            continue
        try:
            rebuilt = build_act(
                act["task_id"], act["act"], act["actor"],
                act["at"], act["assignee"], act["reason"],
                act["note"])
        except ValueError as exc:
            problems.append(
                f"follow-up act {act['act_id']}: {exc}")
            continue
        if rebuilt.act_id != act["act_id"] \
                or rebuilt.fingerprint != act["fingerprint"]:
            problems.append(
                f"follow-up act {act['act_id']}: its "
                "fingerprint does not match its fields")
        task = tasks[act["task_id"]]
        prior = [a for a in store.list_followup_acts(task["task_id"])
                 if (a["at"], a["act_id"]) < (act["at"], act["act_id"])]
        if derive_state(task, prior)["state"] in pack.TERMINAL_STATES:
            problems.append(
                f"follow-up act {act['act_id']}: recorded "
                f"against task {task['task_id']} after it "
                "reached a terminal state")
    return problems
