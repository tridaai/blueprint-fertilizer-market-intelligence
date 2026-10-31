"""The pack-configuration rule pack — versioned data
for the admin configuration register (R19, roadmap
F21-AD2).

Until this round, a threshold change in this system
was a code release: the alert bands, the gap bands,
the freshness windows and the field-signal cap live
in their packs as constants under a version label,
and an artefact names the label it was struck under.
That discipline stays. What this pack adds is the
register beside it: a threshold change may now also
be struck as a stored pack version — complete values,
a named editor, an effective date, and a diff against
the version it replaces — and the engines resolve
their thresholds through the register at strike time.

The register's rules, stated here as data:

- **Four families**, the ones the roadmap names:
  the price watch's firing thresholds, the supply
  gap's band thresholds, the ingest registry's
  freshness windows, and the field layer's
  unverified-report cap. Each family's configurable
  values are a stated, complete snapshot — the
  movement windows, the decay curve and the driver
  rules are computation, not configuration, and stay
  in their code packs.
- **Resolution is by date at strike, by name at
  verification.** An artefact struck at a date is
  judged under the version in force at that date —
  the stored version with the latest effective date
  on or before it, or the code pack when none is in
  force — and names that version on its face. A
  verifier re-performs the artefact under the
  version it names, fetched from the register, so a
  later version can never change what an earlier
  firing means: pack changes are never retroactive.
- **A version is never backdated.** Its effective
  date may not precede the date it is struck, and
  effective dates strictly increase within a
  family. A version that changes nothing is refused:
  the register records decisions, not noise.
- **The code pack is the seed.** Every family's
  baseline values are exactly its code pack's, under
  the code pack's own label. A stored version
  carrying that label must equal the code pack
  field for field — the verifier grades it — so the
  register can never quietly redefine the baseline.
"""

from __future__ import annotations

from . import alert_rules, field_rules, ingest_rules, supply_rules

RULES_VERSION = "2026.10.1"

# -- families -------------------------------------------------------------
FAMILY_ALERTS = "alerts"
FAMILY_GAPS = "gaps"
FAMILY_FRESHNESS = "freshness"
FAMILY_FIELD = "field_signals"
FAMILIES = (FAMILY_ALERTS, FAMILY_GAPS,
            FAMILY_FRESHNESS, FAMILY_FIELD)

# The code pack each family is seeded from, and the
# label its baseline carries.
FAMILY_CODE_PACK = {
    FAMILY_ALERTS: alert_rules,
    FAMILY_GAPS: supply_rules,
    FAMILY_FRESHNESS: ingest_rules,
    FAMILY_FIELD: field_rules,
}


def code_label(family: str) -> str:
    return FAMILY_CODE_PACK[family].RULES_VERSION


def code_values(family: str) -> dict:
    """The family's baseline values, read out of its
    code pack — the seed every register starts from
    and the fallback when no version is in force."""
    if family == FAMILY_ALERTS:
        return {
            "mom_bands": {k: dict(v) for k, v in
                          alert_rules.MOM_BANDS.items()},
            "baseline_bands": {k: dict(v) for k, v in
                               alert_rules.BASELINE_BANDS.items()},
            "spike_pct": alert_rules.SPIKE_PCT,
            "spike_event_window_months":
                alert_rules.SPIKE_EVENT_WINDOW_MONTHS,
            "sustained_months": alert_rules.SUSTAINED_MONTHS,
            "sustained_min_monthly_pct":
                alert_rules.SUSTAINED_MIN_MONTHLY_PCT,
            "sustained_cumulative_pct":
                alert_rules.SUSTAINED_CUMULATIVE_PCT,
            "sustained_band": alert_rules.SUSTAINED_BAND,
        }
    if family == FAMILY_GAPS:
        return {
            "programme_cover_comfortable_pct":
                supply_rules.PROGRAMME_COVER_COMFORTABLE_PCT,
            "programme_cover_tight_pct":
                supply_rules.PROGRAMME_COVER_TIGHT_PCT,
            "level_gap_comfortable_pct":
                supply_rules.LEVEL_GAP_COMFORTABLE_PCT,
            "level_gap_tight_pct":
                supply_rules.LEVEL_GAP_TIGHT_PCT,
        }
    if family == FAMILY_FRESHNESS:
        return {
            "windows_days": {
                source_id: entry["freshness_days"]
                for source_id, entry in
                ingest_rules.SOURCES.items()},
        }
    if family == FAMILY_FIELD:
        return {
            "unverified_cap_pct": field_rules.UNVERIFIED_CAP_PCT,
        }
    raise ValueError(f"unknown config family: {family!r}")


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) \
        and not isinstance(value, bool)


def _check_band_table(values: dict, key: str,
                      problems: list[str]) -> None:
    table = values.get(key)
    if not isinstance(table, dict) \
            or set(table) != {"product", "feedstock"}:
        problems.append(
            f"{key} must state bands for exactly the "
            "product and feedstock series classes")
        return
    for kind, bands in table.items():
        if not isinstance(bands, dict) \
                or set(bands) != {"watch", "alert"} \
                or not all(_is_number(bands[b])
                           for b in ("watch", "alert")):
            problems.append(
                f"{key}.{kind} must state numeric watch "
                "and alert bands")
        elif not 0 < bands["watch"] < bands["alert"]:
            problems.append(
                f"{key}.{kind}: the watch band must sit "
                "below the alert band, both above zero")


def validate_values(family: str, values) -> list[str]:
    """Fail-closed validation of one family's complete
    values snapshot: exact key sets, numeric ranges,
    stated orderings. Returns the problems found —
    a version with problems is never struck."""
    problems: list[str] = []
    if not isinstance(values, dict):
        return ["values must be an object"]
    baseline = code_values(family)
    if set(values) != set(baseline):
        problems.append(
            f"a {family} version states exactly the "
            f"family's keys {sorted(baseline)}, not "
            f"{sorted(values)}")
        return problems
    if family == FAMILY_ALERTS:
        _check_band_table(values, "mom_bands", problems)
        _check_band_table(values, "baseline_bands", problems)
        if not _is_number(values["spike_pct"]) \
                or values["spike_pct"] <= 0:
            problems.append("spike_pct must be a positive number")
        window = values["spike_event_window_months"]
        if not isinstance(window, int) or isinstance(window, bool) \
                or window < 0:
            problems.append(
                "spike_event_window_months must be a "
                "non-negative integer")
        months = values["sustained_months"]
        if not isinstance(months, int) or isinstance(months, bool) \
                or months < 2:
            problems.append("sustained_months must be an integer >= 2")
        for key in ("sustained_min_monthly_pct",
                    "sustained_cumulative_pct"):
            if not _is_number(values[key]) or values[key] <= 0:
                problems.append(f"{key} must be a positive number")
        if values["sustained_band"] not in ("watch", "alert"):
            problems.append(
                "sustained_band must be watch or alert")
    elif family == FAMILY_GAPS:
        for stem in ("programme_cover", "level_gap"):
            comfort = values[f"{stem}_comfortable_pct"]
            tight = values[f"{stem}_tight_pct"]
            if not _is_number(comfort) or not _is_number(tight):
                problems.append(f"{stem} thresholds must be numeric")
            elif stem == "programme_cover" \
                    and not comfort > tight > 0:
                problems.append(
                    "programme cover: the comfortable "
                    "threshold must sit above the tight "
                    "threshold, both above zero")
            elif stem == "level_gap" \
                    and not comfort > tight:
                problems.append(
                    "level gap: the comfortable threshold "
                    "must sit above the tight threshold")
    elif family == FAMILY_FRESHNESS:
        windows = values["windows_days"]
        known = set(ingest_rules.SOURCES)
        if not isinstance(windows, dict) \
                or set(windows) != known:
            problems.append(
                "windows_days must state a window for "
                f"exactly the registered sources {sorted(known)}")
        else:
            for source_id, days in windows.items():
                if not isinstance(days, int) \
                        or isinstance(days, bool) or days <= 0:
                    problems.append(
                        f"window for {source_id} must be a "
                        "positive integer number of days")
    elif family == FAMILY_FIELD:
        cap = values["unverified_cap_pct"]
        if not _is_number(cap) or not 0 < cap <= 100:
            problems.append(
                "unverified_cap_pct must be a number in "
                "the range (0, 100]")
    return problems


def diff_values(before: dict, after: dict,
                prefix: str = "") -> list[dict]:
    """The field-by-field diff between two snapshots of
    one family, as data: each changed leaf named by its
    dotted path with its old and new values. Added and
    removed leaves are stated as such (a complete
    snapshot should never produce them, and the
    verifier treats an unexplained one as a defect)."""
    diff: list[dict] = []
    for key in sorted(set(before) | set(after)):
        path = f"{prefix}{key}"
        if key not in before:
            diff.append({"field": path, "change": "added",
                         "from": None, "to": after[key]})
        elif key not in after:
            diff.append({"field": path, "change": "removed",
                         "from": before[key], "to": None})
        elif isinstance(before[key], dict) \
                and isinstance(after[key], dict):
            diff.extend(diff_values(
                before[key], after[key], f"{path}."))
        elif before[key] != after[key]:
            diff.append({"field": path, "change": "changed",
                         "from": before[key], "to": after[key]})
    return diff


def next_label(store_versions: list[dict], family: str) -> str:
    """The label a family's next struck version
    carries: the code label's own sequence,
    patch-incremented past the highest label already
    in the register. The code label itself names
    exactly one version — the seed, struck only by
    the seed path with the code pack's own values —
    so every version struck as a change, including a
    revert to the code values, takes a fresh label
    and a label names one snapshot forever."""
    base = code_label(family)
    stem, _, patch = base.rpartition(".")
    highest = int(patch)
    for version in store_versions:
        try:
            highest = max(
                highest,
                int(version["version_label"].rpartition(".")[2]))
        except ValueError:
            continue
    return f"{stem}.{highest + 1}"
