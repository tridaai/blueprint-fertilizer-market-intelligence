"""The alert rule pack — versioned data for the price watch (R3).

Every alert the price watch fires traces to a rule stated here:
the movement windows, the band thresholds per series class, the
spike rule and its event window, and the sustained-move rule. The
pack is data with a version, not scattered constants: a movement
and an alert artefact both name the pack version they were
computed under, and the verifier re-performs them from the same
pack, so a threshold change is a new pack version and old alerts
stay reproducible under theirs.

The thresholds are stated against the behaviour of the tracked
series: ordinary month-to-month noise in these markets runs inside
roughly ±1.5%, so the watch bands sit well clear of it, and the
spike band sits at a move no ordinary month produces.
"""

from __future__ import annotations

RULES_VERSION = "2026.10.1"

# -- movement windows ---------------------------------------------------
# A movement is computed for every month that has a predecessor:
# the month-on-month change, and the change against the trailing
# baseline — the mean of the up-to-six preceding months. The
# baseline needs at least three preceding months before a mean is
# stated at all; below that the movement records no baseline.
BASELINE_WINDOW_MONTHS = 6
BASELINE_MIN_MONTHS = 3

# -- band thresholds, absolute percent ----------------------------------
# Per series class: (watch, alert) for the month-on-month rule and
# the baseline rule. A rule fires at the highest band its figure
# reaches; below watch it does not fire.
MOM_BANDS = {
    "product": {"watch": 5.0, "alert": 12.0},
    "feedstock": {"watch": 4.0, "alert": 9.0},
}
BASELINE_BANDS = {
    "product": {"watch": 8.0, "alert": 15.0},
    "feedstock": {"watch": 7.0, "alert": 14.0},
}

# -- the spike rule -------------------------------------------------------
# A single month moving at least this far is a spike, whichever
# direction, and fires at the alert band. A spike is an *event*,
# not a monthly condition: the months that follow it are the event
# unwinding (a spike up decays back; a spike down recovers), so the
# spike rule does not fire again for the same series within the
# event window — the following two months. The unwind still fires
# the ordinary movement rules on its own figures.
SPIKE_PCT = 20.0
SPIKE_EVENT_WINDOW_MONTHS = 2

# -- the sustained-move rule ----------------------------------------------
# Three consecutive months moving the same direction, each by at
# least the per-month floor, adding up to at least the cumulative
# floor, is a drift worth watching even though no single month is
# remarkable. It fires once per unbroken run, at the first month
# the trailing three qualify; a month that breaks the run (too
# small, or the other direction) resets it.
SUSTAINED_MONTHS = 3
SUSTAINED_MIN_MONTHLY_PCT = 0.75
SUSTAINED_CUMULATIVE_PCT = 2.5
SUSTAINED_BAND = "watch"

# -- alert lifecycle --------------------------------------------------------
# An alert is closed with a stated reason from this vocabulary —
# never a free-text shrug. The reasons are data so the vocabulary
# can grow by pack version, not by code edit.
CLOSING_REASONS = {
    "explained_by_event": "an identified market event explains the move",
    "passed_no_action": "the move has passed and no action is needed",
    "actioned_supply_response": "a supply or pricing response was actioned",
    "watch_continues_elsewhere": "monitoring continues under a newer alert",
}

BAND_RANK = {"none": 0, "watch": 1, "alert": 2}


def band_for(series_kind: str, rule: str, abs_pct: float) -> str | None:
    """The band a single movement figure earns under its rule, or
    None when it does not reach the watch band."""
    table = MOM_BANDS[series_kind] if rule == "mom_move" else BASELINE_BANDS[series_kind]
    if abs_pct >= table["alert"]:
        return "alert"
    if abs_pct >= table["watch"]:
        return "watch"
    return None
