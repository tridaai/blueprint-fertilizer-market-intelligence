"""The season-close scoring pack — versioned data (R12).

How a struck demand estimate is graded once the season has
closed and the actuals are on record. Every rule the scorer
applies is stated here, as data with a version:

- A **cell** is one head estimate (district × product ×
  crop year × season) graded against one season-close
  actual row of the same natural key. An actual row's kind
  (consumption / dispatch) is part of the cell: the two
  kinds are graded separately, never blended.
- **Error** is signed: ``actual − estimate`` tonnes. A
  positive error means the engine under-estimated the
  season. **Bias** is the mean signed error across a run's
  scored cells — the systematic direction of the engine,
  stated separately from the mean absolute percentage
  error, which measures size alone.
- **Percentage error** is the signed error over the actual
  quantity, × 100, rounded to 4 decimals. An actual of
  exactly zero has no percentage error: the field is null
  and the cell is named ``zero_actual`` — never a
  fabricated 0% or an infinity.
- **Driver attribution**: the total signed error is
  attributed across the estimate's own contribution lines
  in proportion to each line's signed share of the
  estimate total — ``attributed_i = error × delta_i /
  total`` — where a line's delta is its recorded
  ``delta_tonnes`` (the base line's delta is the base
  itself). Attributed errors therefore sum to the total
  error exactly, up to the tonne rounding. Lines recorded
  missing or not applicable carry a zero delta and so a
  zero attribution: the method cannot blame a driver that
  never moved the estimate.
- The **most-wrong line** is the line with the largest
  absolute attributed error. Ties break to the lowest
  line number, so the answer is deterministic. When the
  estimate total is zero the shares are undefined: the
  run records ``attribution: not_attributable`` on the
  cell and names no most-wrong line, rather than dividing
  by zero or inventing shares.
- Tonnes round to 3 decimals at every step, the repo's
  standing discipline; attribution re-performance allows
  the rounding of summed parts.

A rule change is a new pack version; old score runs stay
reproducible under theirs, exactly as estimates do under
the demand pack.
"""

from __future__ import annotations

SCORING_VERSION = "2026.10.1"

ATTRIBUTION_METHOD = "proportional_to_signed_contribution_share"

# Tonnes are rounded to 3 decimals at every step; the
# attribution identity (attributed errors sum to the total
# error) is allowed the rounding of its summed parts: at
# most half a milli-tonne per line, capped here.
TONNE_TOL = 0.002
ATTRIBUTION_TOL = 0.01

# Percentage figures carry 4 decimals, the repo's stated
# precision for programme cover and share movement alike.
PCT_DECIMALS = 4
