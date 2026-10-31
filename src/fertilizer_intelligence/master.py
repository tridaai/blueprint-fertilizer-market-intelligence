"""Master data as stored, effective-dated versions
(R19, roadmap F21-AD1).

One artefact per administered change: a register's
complete content, a named editor, an effective date,
and the diff against the version in force the day
before — insert-only and chained by link, under the
same discipline as the pack-configuration register.
The register this module exists for is the
application-rate table: the demand engine resolves
its rates here, so a rate-table change is a new
version that applies to estimates struck from its
date, while prior estimates keep the version they
name on their face and re-perform from the rates
their own base lines recorded — unchanged, forever.

The remaining registers — the season calendar,
districts, products, crops — are kept as versioned
records of the administered data: their seeds are
graded against the code and the store they describe,
and their changes land here first. Their consumers
read the underlying tables and constants directly
in this release; the module states that plainly
rather than wiring a resolution nothing grades.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date

from pydantic import BaseModel

from . import master_rules as pack


def _fingerprint(payload: dict) -> str:
    blob = json.dumps(
        payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def _require_date(value: str, field: str) -> None:
    try:
        date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"{field} is not an ISO date: {value!r}") from None


class MasterDataVersion(BaseModel):
    version_id: str
    fingerprint: str
    register: str
    version_label: str
    content: dict
    diff: list[dict]
    effective_from: str
    struck_on: str
    editor: str
    rules_version: str
    supersedes: str | None = None


def _versions(store, register: str) -> list[dict]:
    return store.list_master_data_versions(register=register)


def _in_force(store, register: str, on_date: str) -> dict | None:
    candidates = [
        v for v in _versions(store, register)
        if v["effective_from"] <= on_date]
    if not candidates:
        return None
    return max(candidates,
               key=lambda v: (v["effective_from"], v["version_id"]))


def resolve_master(store, register: str, on_date: str) -> dict:
    """What a register holds at a date: the version
    in force, or the baseline read from the code and
    the store when the register holds none yet.
    Returns the version label, the content, and
    which of the two supplied them."""
    if register not in pack.REGISTERS:
        raise ValueError(f"unknown master register: {register!r}")
    _require_date(on_date, "resolution date")
    version = _in_force(store, register, on_date)
    if version is None:
        return {"version_label": pack.seed_label(register),
                "content": pack.base_content(store, register),
                "origin": "base"}
    return {"version_label": version["version_label"],
            "content": version["content"],
            "origin": "register"}


def content_for_label(store, register: str,
                      label: str) -> dict | None:
    """The content a version label names: the
    baseline for the seed label, the stored snapshot
    for a register label, None for a label nothing
    holds."""
    if register not in pack.REGISTERS:
        raise ValueError(f"unknown master register: {register!r}")
    if label == pack.seed_label(register):
        return pack.base_content(store, register)
    for version in _versions(store, register):
        if version["version_label"] == label:
            return version["content"]
    return None


def set_master_version(store, register: str, content: dict,
                       effective_from: str, editor: str,
                       struck_on: str) -> MasterDataVersion:
    """Strike one master-data version: a complete
    snapshot for the register, validated fail-closed
    by the pack, diffed against the version in force
    the day before its effective date. Never
    backdated, effective dates strictly increasing,
    a no-change version refused — the configuration
    register's rules, kept identically here."""
    if register not in pack.REGISTERS:
        raise ValueError(f"unknown master register: {register!r}")
    if not editor or not editor.strip():
        raise ValueError(
            "a master-data version names its editor — "
            "an unnamed change is refused")
    _require_date(effective_from, "effective_from")
    _require_date(struck_on, "struck_on")
    if effective_from < struck_on:
        raise ValueError(
            f"a master-data version is never backdated: "
            f"effective_from {effective_from} precedes "
            f"the date it is struck, {struck_on}")
    problems = pack.validate_content(register, content)
    if problems:
        raise ValueError(
            f"invalid {register} content: "
            + "; ".join(problems))
    existing = _versions(store, register)
    for version in existing:
        if effective_from <= version["effective_from"]:
            raise ValueError(
                f"effective dates strictly increase "
                f"within a register: {register} already "
                f"carries a version effective "
                f"{version['effective_from']}")
    # The predecessor is the version in force the day
    # before the effective date — exactly the current
    # head, since effective dates strictly increase
    # (graded just above), or the baseline when the
    # register holds none. (The literal day before
    # would underflow at the seed's first-day date.)
    head = _in_force(store, register, "9999-12-31")
    predecessor = {
        "version_label": head["version_label"],
        "content": head["content"]} if head else {
        "version_label": pack.seed_label(register),
        "content": pack.base_content(store, register)}
    diff = pack.diff_content(predecessor["content"], content)
    if not diff:
        raise ValueError(
            f"the {register} content is identical to "
            f"the version in force before "
            f"{effective_from} "
            f"({predecessor['version_label']}) — a "
            "version that changes nothing is refused")
    label = pack.next_label(existing, register)
    fingerprint = _fingerprint({
        "register": register, "version_label": label,
        "content": content, "diff": diff,
        "effective_from": effective_from,
        "struck_on": struck_on, "editor": editor.strip(),
        "pack": pack.RULES_VERSION,
        "supersedes": head["version_id"] if head else None,
    })
    version = MasterDataVersion(
        version_id=f"MDV-{fingerprint[:10]}",
        fingerprint=fingerprint, register=register,
        version_label=label, content=content, diff=diff,
        effective_from=effective_from, struck_on=struck_on,
        editor=editor.strip(),
        rules_version=pack.RULES_VERSION,
        supersedes=head["version_id"] if head else None)
    stored = store.get_master_data_version(version.version_id)
    if stored is not None:
        return MasterDataVersion(**stored)
    store.insert_master_data_version(version.model_dump())
    return version


def seed_master_register(store, register: str, editor: str,
                         struck_on: str) -> dict:
    """Strike the register's seed version — its
    baseline content, in force from the earliest
    date — when the register holds none. Struck
    directly, like the configuration seed: its diff
    against the baseline is empty by construction,
    and the earliest date is reserved for it."""
    if register not in pack.REGISTERS:
        raise ValueError(f"unknown master register: {register!r}")
    if not editor or not editor.strip():
        raise ValueError(
            "a master-data version names its editor — "
            "an unnamed change is refused")
    _require_date(struck_on, "struck_on")
    existing = _versions(store, register)
    if existing:
        head = _in_force(store, register, "9999-12-31")
        return store.get_master_data_version(head["version_id"])
    content = pack.base_content(store, register)
    label = pack.seed_label(register)
    fingerprint = _fingerprint({
        "register": register, "version_label": label,
        "content": content, "diff": [],
        "effective_from": "0001-01-01",
        "struck_on": struck_on, "editor": editor.strip(),
        "pack": pack.RULES_VERSION, "supersedes": None,
    })
    version = MasterDataVersion(
        version_id=f"MDV-{fingerprint[:10]}",
        fingerprint=fingerprint, register=register,
        version_label=label, content=content, diff=[],
        effective_from="0001-01-01", struck_on=struck_on,
        editor=editor.strip(),
        rules_version=pack.RULES_VERSION, supersedes=None)
    stored = store.get_master_data_version(version.version_id)
    if stored is not None:
        return stored
    store.insert_master_data_version(version.model_dump())
    return store.get_master_data_version(version.version_id)


# -- the wired register: application rates -----------------


def rates_in_force(store, on_date: str) -> tuple[str, dict]:
    """The demand engine's rate resolution: the rate
    table in force at a date, as the version label
    an estimate names and the (crop, product) ->
    rate map it computes from."""
    resolved = resolve_master(store, pack.REGISTER_RATES, on_date)
    rates = {
        (row["crop"], row["product"]): row["rate_kg_ha"]
        for row in resolved["content"]["rates"]}
    return resolved["version_label"], rates


def rates_for_label(store, label: str) -> dict | None:
    """The rate map a version label names, for
    re-performing an estimate that carries it."""
    content = content_for_label(store, pack.REGISTER_RATES, label)
    if content is None:
        return None
    return {
        (row["crop"], row["product"]): row["rate_kg_ha"]
        for row in content["rates"]}


def verify_master(store) -> list[str]:
    """Re-perform the whole register set: every
    version's fingerprint recomputes, its content
    validates, its diff re-derives against the
    version in force the day before, the supersedes
    chain stands in order, and a version carrying
    the seed label equals the baseline read from
    the code and the store, field for field."""
    problems: list[str] = []
    for register in pack.REGISTERS:
        versions = _versions(store, register)
        ordered = sorted(
            versions,
            key=lambda v: (v["effective_from"], v["version_id"]))
        for idx, version in enumerate(ordered):
            want = ordered[idx - 1]["version_id"] if idx else None
            if version["supersedes"] != want:
                problems.append(
                    f"master version {version['version_id']}: "
                    f"supersedes {version['supersedes']}, "
                    f"but the chain order says {want}")
            invalid = pack.validate_content(
                register, version["content"])
            if invalid:
                problems.append(
                    f"master version {version['version_id']}: "
                    f"its content does not validate: "
                    + "; ".join(invalid))
            if version["version_label"] == pack.seed_label(register) \
                    and version["content"] \
                    != pack.base_content(store, register):
                problems.append(
                    f"master version {version['version_id']}: "
                    "carries the seed label but its content "
                    "is not the register's baseline")
            # The predecessor is the latest version
            # effective strictly before this one — the
            # same set as "in force the day before",
            # since effective dates strictly increase —
            # or the baseline when there is none. The
            # strict comparison also covers the seed,
            # whose first-day effective date has no day
            # before it.
            predecessor_content = pack.base_content(store, register)
            earlier = [
                v for v in ordered
                if v["effective_from"] < version["effective_from"]]
            if earlier:
                predecessor_content = earlier[-1]["content"]
            rebuilt_diff = pack.diff_content(
                predecessor_content, version["content"])
            if rebuilt_diff != version["diff"]:
                problems.append(
                    f"master version {version['version_id']}: "
                    "its diff does not re-derive from its "
                    "predecessor's content")
            rebuilt = _fingerprint({
                "register": register,
                "version_label": version["version_label"],
                "content": version["content"],
                "diff": version["diff"],
                "effective_from": version["effective_from"],
                "struck_on": version["struck_on"],
                "editor": version["editor"],
                "pack": pack.RULES_VERSION,
                "supersedes": version["supersedes"],
            })
            if rebuilt != version["fingerprint"] \
                    or version["version_id"] != f"MDV-{rebuilt[:10]}":
                problems.append(
                    f"master version {version['version_id']}: "
                    "its fingerprint does not match its fields")
            if version["effective_from"] < version["struck_on"] \
                    and version["effective_from"] != "0001-01-01":
                problems.append(
                    f"master version {version['version_id']}: "
                    "effective before it was struck — a "
                    "backdated version")
    return problems
