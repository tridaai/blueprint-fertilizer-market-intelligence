"""The collaboration rule pack — versioned data for
annotations and assigned follow-ups (R15, roadmap
F21-CA2).

The desk coordinates today by phone and memory: a
figure looks wrong, someone means to check it, the
season moves on. This pack states the terms under
which a comment or a task may pin to an artefact, as
data with a version, so the vocabulary a closing act
must speak is a pack change, not a code change.

- **Pins are to versions, not to topics.** An
  annotation names an artefact kind, its id and the
  fingerprint of the exact stored version it was
  written against. When a successor supersedes that
  version, the annotation stays pinned where it was
  written and reads flagged as pinned to a superseded
  version — it is never silently moved onto the new
  version, because the comment was about the old
  number.
- **Only three kinds take pins in this round:**
  demand estimates, supply gaps and price alerts —
  the artefacts the desk argues about. Alerts fold
  state rather than superseding, so an alert pin is
  never flagged superseded; that difference is stated
  here, not discovered.
- **A follow-up's state is a fold of acts.** Assign,
  complete, close — each a named, attributed act.
  Closing speaks a reason from the vocabulary below;
  a free-text shrug closes nothing.
"""

from __future__ import annotations

RULES_VERSION = "2026.10.1"

# -- pinnable artefact kinds --------------------------------
KIND_ESTIMATE = "demand_estimate"
KIND_GAP = "supply_gap"
KIND_ALERT = "price_alert"
TARGET_KINDS = (KIND_ESTIMATE, KIND_GAP, KIND_ALERT)

# -- follow-up acts -------------------------------------------
ACT_ASSIGN = "assign"
ACT_COMPLETE = "complete"
ACT_CLOSE = "close"
ACTS = (ACT_ASSIGN, ACT_COMPLETE, ACT_CLOSE)

# Task states, derived from the fold of acts: open until
# a complete or a close, terminal from either.
STATE_OPEN = "open"
STATE_COMPLETED = "completed"
STATE_CLOSED = "closed"
TERMINAL_STATES = (STATE_COMPLETED, STATE_CLOSED)

# -- the closing vocabulary -----------------------------------
CLOSE_REASONS = {
    "no_longer_relevant": "the question the task raised "
                          "no longer bears on the season",
    "overtaken_by_events": "a successor artefact or a "
                           "season event answered it",
    "raised_in_error": "the task was raised against the "
                       "wrong artefact and should not "
                       "have existed",
}
