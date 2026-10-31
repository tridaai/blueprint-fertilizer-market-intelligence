"""Pack configuration as stored, effective-dated
versions (R19, roadmap F21-AD2).

The register this module keeps is one artefact per
configuration decision: a family's complete values, a
named editor, the date the version takes effect, and
the diff it makes against the version in force the
day before. Versions are insert-only and chained by
link, exactly like every other artefact family in
this system, and the module's one promise is the
roadmap's gate: **a pack effective mid-season applies
only from its date, and historical firings never
change retroactively.**

The promise is kept by how the engines resolve:

- at strike time, by the artefact's own date —
  :func:`resolve_config` returns the version in
  force on that date, or the code pack when the
  register holds nothing in force yet;
- at verification time, by the artefact's named
  version — :func:`values_for_label` returns the
  code pack for the code label and the stored
  snapshot for a register label, and names an
  unknown label as unknown, which every verifier
  already treats as a defect.

Two refusals guard the register's own integrity: a
version may not be backdated (its effective date
precedes the date it is struck) and effective dates
strictly increase within a family, so the version in
force at any date can never be rewritten by a later
act; and a version whose diff is empty is refused,
so the register holds decisions, not noise.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date

from pydantic import BaseModel

from . import configuration_rules as pack


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


class PackConfigVersion(BaseModel):
    version_id: str
    fingerprint: str
    family: str
    version_label: str
    values: dict
    diff: list[dict]
    effective_from: str
    struck_on: str
    editor: str
    rules_version: str
    supersedes: str | None = None


def _versions(store, family: str) -> list[dict]:
    return store.list_pack_config_versions(family=family)


def _in_force(store, family: str, on_date: str) -> dict | None:
    """The register version in force at a date: the
    one with the latest effective date on or before
    it, or None when the register holds none yet."""
    candidates = [
        v for v in _versions(store, family)
        if v["effective_from"] <= on_date]
    if not candidates:
        return None
    return max(candidates,
               key=lambda v: (v["effective_from"], v["version_id"]))


def resolve_config(store, family: str, on_date: str) -> dict:
    """What governs a family at a date: the register
    version in force, or the code pack when none is.
    Returns the version label, the values, and which
    of the two supplied them."""
    if family not in pack.FAMILIES:
        raise ValueError(f"unknown config family: {family!r}")
    _require_date(on_date, "resolution date")
    version = _in_force(store, family, on_date)
    if version is None:
        return {"version_label": pack.code_label(family),
                "values": pack.code_values(family),
                "origin": "code"}
    return {"version_label": version["version_label"],
            "values": version["values"], "origin": "register"}


def values_for_label(store, family: str,
                     label: str) -> dict | None:
    """The values a version label names, for a
    verifier re-performing an artefact that carries
    it: the code pack for the code label, the stored
    snapshot for a register label, None for a label
    nothing holds — the caller names it unknown."""
    if family not in pack.FAMILIES:
        raise ValueError(f"unknown config family: {family!r}")
    if label == pack.code_label(family):
        return pack.code_values(family)
    for version in _versions(store, family):
        if version["version_label"] == label:
            return version["values"]
    return None


def set_pack_config(store, family: str, values: dict,
                    effective_from: str, editor: str,
                    struck_on: str) -> PackConfigVersion:
    """Strike one configuration version. The values
    are a complete snapshot for the family, validated
    fail-closed by the pack; the diff is computed
    against the version in force the day before the
    effective date; the label is the code label for a
    seed (a first version equal to the code pack) and
    the next in the family's sequence otherwise.
    Striking the identical version again — same
    values, same effective date, same editor — is the
    same artefact, returned, never duplicated."""
    if family not in pack.FAMILIES:
        raise ValueError(f"unknown config family: {family!r}")
    if not editor or not editor.strip():
        raise ValueError(
            "a pack version names its editor — an "
            "unnamed configuration change is refused")
    _require_date(effective_from, "effective_from")
    _require_date(struck_on, "struck_on")
    if effective_from < struck_on:
        raise ValueError(
            f"a pack version is never backdated: "
            f"effective_from {effective_from} precedes "
            f"the date it is struck, {struck_on}")
    problems = pack.validate_values(family, values)
    if problems:
        raise ValueError(
            f"invalid {family} values: " + "; ".join(problems))
    existing = _versions(store, family)
    for version in existing:
        if effective_from <= version["effective_from"]:
            raise ValueError(
                f"effective dates strictly increase "
                f"within a family: {family} already "
                f"carries a version effective "
                f"{version['effective_from']}")
    # The predecessor is the version in force the day
    # before the effective date — and since effective
    # dates strictly increase (graded just above), that
    # is exactly the current head, or the code pack
    # when the register holds none. (Resolving by the
    # literal day before would also underflow at the
    # seed's first-day effective date.)
    head = _in_force(store, family, "9999-12-31")
    predecessor = {
        "version_label": head["version_label"],
        "values": head["values"]} if head else {
        "version_label": pack.code_label(family),
        "values": pack.code_values(family)}
    diff = pack.diff_values(predecessor["values"], values)
    if not diff:
        raise ValueError(
            f"the {family} values are identical to the "
            f"version in force before {effective_from} "
            f"({predecessor['version_label']}) — a "
            "version that changes nothing is refused")
    label = pack.next_label(existing, family)
    fingerprint = _fingerprint({
        "family": family, "version_label": label,
        "values": values, "diff": diff,
        "effective_from": effective_from,
        "struck_on": struck_on, "editor": editor.strip(),
        "pack": pack.RULES_VERSION,
        "supersedes": head["version_id"] if head else None,
    })
    version = PackConfigVersion(
        version_id=f"PCV-{fingerprint[:10]}",
        fingerprint=fingerprint, family=family,
        version_label=label, values=values, diff=diff,
        effective_from=effective_from, struck_on=struck_on,
        editor=editor.strip(),
        rules_version=pack.RULES_VERSION,
        supersedes=head["version_id"] if head else None)
    stored = store.get_pack_config_version(version.version_id)
    if stored is not None:
        return PackConfigVersion(**stored)
    store.insert_pack_config_version(version.model_dump())
    return version


def seed_pack_config(store, family: str, editor: str,
                     struck_on: str) -> dict:
    """Strike the family's seed version — its code
    values, in force from the earliest date — when
    the register holds none. Idempotent: a family
    that already carries versions returns its head
    untouched. The seed is how the baseline becomes
    an artefact the verifier can grade against the
    code pack. It is struck directly, not through
    :func:`set_pack_config`: its diff against the
    code pack is empty by construction (it IS the
    code pack), and its effective date is the
    earliest date there is — the one backdating the
    register otherwise refuses, reserved for the
    seed alone."""
    if family not in pack.FAMILIES:
        raise ValueError(f"unknown config family: {family!r}")
    if not editor or not editor.strip():
        raise ValueError(
            "a pack version names its editor — an "
            "unnamed configuration change is refused")
    _require_date(struck_on, "struck_on")
    existing = _versions(store, family)
    if existing:
        head = _in_force(store, family, "9999-12-31")
        return store.get_pack_config_version(head["version_id"])
    values = pack.code_values(family)
    label = pack.code_label(family)
    fingerprint = _fingerprint({
        "family": family, "version_label": label,
        "values": values, "diff": [],
        "effective_from": "0001-01-01",
        "struck_on": struck_on, "editor": editor.strip(),
        "pack": pack.RULES_VERSION, "supersedes": None,
    })
    version = PackConfigVersion(
        version_id=f"PCV-{fingerprint[:10]}",
        fingerprint=fingerprint, family=family,
        version_label=label, values=values, diff=[],
        effective_from="0001-01-01", struck_on=struck_on,
        editor=editor.strip(),
        rules_version=pack.RULES_VERSION, supersedes=None)
    stored = store.get_pack_config_version(version.version_id)
    if stored is not None:
        return stored
    store.insert_pack_config_version(version.model_dump())
    return store.get_pack_config_version(version.version_id)


def verify_config(store) -> list[str]:
    """Re-perform the whole register: every version's
    fingerprint recomputes from its fields, its
    values validate, its diff re-derives against the
    version in force the day before its effective
    date, effective dates strictly increase, the
    supersedes chain stands in strike order, and a
    version carrying the code label equals the code
    pack field for field."""
    problems: list[str] = []
    for family in pack.FAMILIES:
        versions = _versions(store, family)
        ordered = sorted(
            versions,
            key=lambda v: (v["effective_from"], v["version_id"]))
        for idx, version in enumerate(ordered):
            want = ordered[idx - 1]["version_id"] if idx else None
            if version["supersedes"] != want:
                problems.append(
                    f"pack config {version['version_id']}: "
                    f"supersedes {version['supersedes']}, "
                    f"but the chain order says {want}")
            invalid = pack.validate_values(
                family, version["values"])
            if invalid:
                problems.append(
                    f"pack config {version['version_id']}: "
                    f"its values do not validate: "
                    + "; ".join(invalid))
            if version["version_label"] == pack.code_label(family) \
                    and version["values"] != pack.code_values(family):
                problems.append(
                    f"pack config {version['version_id']}: "
                    "carries the code label but its values "
                    "are not the code pack's")
            # The predecessor is the latest version
            # effective strictly before this one (the
            # same set as "in force the day before",
            # since effective dates strictly increase) —
            # or the code pack when there is none. The
            # strict comparison also covers the seed,
            # whose first-day effective date has no day
            # before it.
            earlier = [
                v for v in ordered
                if v["effective_from"] < version["effective_from"]]
            predecessor_values = earlier[-1]["values"] \
                if earlier else pack.code_values(family)
            rebuilt_diff = pack.diff_values(
                predecessor_values, version["values"])
            if rebuilt_diff != version["diff"]:
                problems.append(
                    f"pack config {version['version_id']}: "
                    "its diff does not re-derive from its "
                    "predecessor's values")
            rebuilt = _fingerprint({
                "family": family,
                "version_label": version["version_label"],
                "values": version["values"],
                "diff": version["diff"],
                "effective_from": version["effective_from"],
                "struck_on": version["struck_on"],
                "editor": version["editor"],
                "pack": pack.RULES_VERSION,
                "supersedes": version["supersedes"],
            })
            if rebuilt != version["fingerprint"] \
                    or version["version_id"] != f"PCV-{rebuilt[:10]}":
                problems.append(
                    f"pack config {version['version_id']}: "
                    "its fingerprint does not match its fields")
            if version["effective_from"] < version["struck_on"] \
                    and version["effective_from"] != "0001-01-01":
                problems.append(
                    f"pack config {version['version_id']}: "
                    "effective before it was struck — a "
                    "backdated version")
    return problems
