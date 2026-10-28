"""The demand rule pack — versioned data, shared by the generator
and the demand engine.

Every number the demand engine produces traces to a rule stated
here: the soil-status factors, the monsoon response bands, the
price elasticities, the carry-in stock bands, and the calendar
windows those rules read. The pack is data with a version, not
scattered constants: an estimate artefact names the pack version
it was computed under, and the verifier re-performs the estimate
from the same pack, so a rule change is a new pack version and
old estimates stay reproducible under theirs.

The dataset generator imports its soil/monsoon rules from here
too — there is exactly one statement of each rule in the repo.
"""

from __future__ import annotations

RULES_VERSION = "2026.10.1"

# The stored application-rate table (migration 0001, populated by
# the generator) carries this pack label; estimates record it so a
# rate-table revision is visible on the artefact.
RATE_TABLE_VERSION = "2026.10.1"

# Soil nutrient status -> demand factor. A district whose soil
# tests low on the nutrient a product supplies applies more of it.
SOIL_FACTOR = {"low": 1.10, "medium": 1.00, "high": 0.92}

# Which soil nutrient primarily drives each product's adjustment.
# Agrochemicals have no soil-nutrient driver.
PRODUCT_NUTRIENT = {
    "UREA": "nitrogen",
    "DAP": "phosphorus",
    "NPK_10_26_26": "potassium",
    "MOP": "potassium",
    "GLYPHOSATE": None,
    "CHLORPYRIFOS": None,
}


def monsoon_factor(season: str, deviation_pct: float) -> float:
    """Stated rule: kharif application responds to the monsoon; rabi
    runs on residual moisture/irrigation and is held at 1.0."""
    if season != "kharif":
        return 1.0
    if deviation_pct <= -15:
        return 0.92
    if deviation_pct <= -5:
        return 0.96
    if deviation_pct < 5:
        return 1.00
    if deviation_pct < 15:
        return 1.03
    return 1.05


# Price elasticity of demand by product: the proportional demand
# response to a proportional season-window price change. Urea's
# retail price is statutory, so its demand barely responds; potash
# is the most discretionary of the majors.
PRICE_ELASTICITY = {
    "UREA": -0.05,
    "DAP": -0.30,
    "NPK_10_26_26": -0.25,
    "MOP": -0.35,
    "GLYPHOSATE": -0.20,
    "CHLORPYRIFOS": -0.15,
}

# A price window (current or prior-year) must hold at least this
# many of its six months of price points before a mean is taken;
# below that the price driver is missing, never interpolated.
MIN_WINDOW_MONTHS = 4

# Carry-in stock: trailing domestic production vs plan over the
# twelve months before the season starts. A surplus carried into
# the season depresses fresh demand; a deficit lifts it.
CARRY_IN_WINDOW_MONTHS = 12
CARRY_IN_SURPLUS_SHARE = 0.02
CARRY_IN_DEFICIT_SHARE = -0.02
CARRY_IN_SURPLUS_FACTOR = 0.97
CARRY_IN_DEFICIT_FACTOR = 1.03
CARRY_IN_NEUTRAL_FACTOR = 1.00


def stock_factor(surplus_share: float) -> float:
    """Band the (actual - planned) / planned share into a factor."""
    if surplus_share >= CARRY_IN_SURPLUS_SHARE:
        return CARRY_IN_SURPLUS_FACTOR
    if surplus_share <= CARRY_IN_DEFICIT_SHARE:
        return CARRY_IN_DEFICIT_FACTOR
    return CARRY_IN_NEUTRAL_FACTOR


# -- calendar windows ---------------------------------------------------


def _shift_month(month: str, delta: int) -> str:
    year, mon = int(month[:4]), int(month[5:7])
    index = year * 12 + (mon - 1) + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def month_window(start_month: str, count: int) -> list[str]:
    return [_shift_month(start_month, i) for i in range(count)]


def season_start_month(crop_year: str, season: str) -> str:
    """Kharif sowing starts in June of the crop year's first
    calendar year; rabi sowing starts that November."""
    first_year = int(crop_year[:4])
    return f"{first_year:04d}-06" if season == "kharif" else f"{first_year:04d}-11"


def season_price_window(crop_year: str, season: str) -> list[str]:
    """The six months the season's price level is read over:
    kharif June–November; rabi November–April."""
    return month_window(season_start_month(crop_year, season), 6)


def prior_price_window(crop_year: str, season: str) -> list[str]:
    """The same six months one year earlier."""
    return [_shift_month(m, -12) for m in season_price_window(crop_year, season)]


def carry_in_window(crop_year: str, season: str) -> list[str]:
    """The twelve months ending the month before the season starts."""
    start = _shift_month(season_start_month(crop_year, season), -CARRY_IN_WINDOW_MONTHS)
    return month_window(start, CARRY_IN_WINDOW_MONTHS)
