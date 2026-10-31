"""The master-data rule pack — versioned data for
the admin master-data register (R19, roadmap
F21-AD1).

Districts, crops, products, season windows and the
application-rate table are the system's master data:
the facts every engine reasons over. Until this
round they lived as code constants and as one
stored table the generator seeds once — correct,
but administered by whoever could edit code or the
seed. This pack states them as registers instead:
named, versioned snapshots struck by named editors
with effective dates and diffs, under the same
resolution discipline as the pack-configuration
register (F21-AD2) — in force by date at strike
time, by name at verification.

- **The application-rate table is the wired
  register.** The demand engine resolves its rates
  through the register: an estimate struck at a
  date runs under the rate version in force at
  that date and names it on its face, where the
  ``rate_table_version`` field has always stood.
  A rate change therefore takes effect for new
  estimates from its date, and prior estimates
  keep their original version — safe by the
  engine's own construction, since an estimate
  records every rate it consumed on its base
  line and its verifier re-performs from those
  recorded inputs, never from the live table.
  The seeded table the generator loads is the
  seed version's content, kept as its storage.
- **The season calendar, districts, products and
  crops are registers of record.** Their seed
  versions are graded field-for-field against
  the code and the store they describe, and every
  later change lands here first as a versioned
  act with its diff — the audit trail of the
  administered data. Their consumers read the
  underlying tables and constants directly in
  this release; the rate table is the register
  the engines resolve, and the pack says so
  rather than pretending otherwise.
- **Versions are never backdated and never
  no-ops**, under the same rules as F21-AD2:
  effective dates strictly increase within a
  register, and a version that changes nothing
  is refused.
"""

from __future__ import annotations

from . import demand_rules
from .configuration_rules import diff_values

RULES_VERSION = "2026.10.1"

# -- registers --------------------------------------------------------------
REGISTER_RATES = "application_rates"
REGISTER_CALENDAR = "season_calendar"
REGISTER_DISTRICTS = "districts"
REGISTER_PRODUCTS = "products"
REGISTER_CROPS = "crops"
REGISTERS = (REGISTER_RATES, REGISTER_CALENDAR,
             REGISTER_DISTRICTS, REGISTER_PRODUCTS,
             REGISTER_CROPS)

# The label each register's seed carries. The rate
# table's seed is the demand pack's own rate-table
# label — the value estimates have named since R2.
SEED_LABELS = {
    REGISTER_RATES: demand_rules.RATE_TABLE_VERSION,
    REGISTER_CALENDAR: RULES_VERSION,
    REGISTER_DISTRICTS: RULES_VERSION,
    REGISTER_PRODUCTS: RULES_VERSION,
    REGISTER_CROPS: RULES_VERSION,
}

# The register the demand engine resolves at
# estimate time.
WIRED_REGISTERS = (REGISTER_RATES,)


def seed_label(register: str) -> str:
    return SEED_LABELS[register]


def base_content(store, register: str) -> dict:
    """The register's baseline content, read from
    the code and the store it describes — what the
    seed version must equal, field for field."""
    if register == REGISTER_RATES:
        return {"rates": [
            {"crop": row["crop"], "product": row["product"],
             "rate_kg_ha": row["rate_kg_ha"]}
            for row in store.application_rates()]}
    if register == REGISTER_CALENDAR:
        return {"season_starts": {
            season: demand_rules.season_start_month(
                "2025-26", season)[5:7]
            for season in ("kharif", "rabi")}}
    if register == REGISTER_DISTRICTS:
        return {"districts": [
            {"district_id": d["district_id"],
             "name": d["name"], "state": d["state"],
             "region": d["region"]}
            for d in store.list_districts()]}
    if register == REGISTER_PRODUCTS:
        from .generator import PRODUCTS
        return {"products": list(PRODUCTS)}
    if register == REGISTER_CROPS:
        crops = {row["crop"] for row in store.application_rates()}
        crops |= {row["crop"] for row in store.area_facts()}
        return {"crops": sorted(crops)}
    raise ValueError(f"unknown master register: {register!r}")


def validate_content(register: str, content) -> list[str]:
    """Fail-closed validation of one register's
    complete snapshot. Returns the problems found."""
    problems: list[str] = []
    if not isinstance(content, dict):
        return ["content must be an object"]
    if register == REGISTER_RATES:
        if set(content) != {"rates"} \
                or not isinstance(content["rates"], list) \
                or not content["rates"]:
            return ["content must carry a non-empty "
                    "rates list and nothing else"]
        seen = set()
        for row in content["rates"]:
            if not isinstance(row, dict) \
                    or set(row) != {"crop", "product",
                                    "rate_kg_ha"}:
                problems.append(
                    f"rate row {row!r} must state exactly "
                    "crop, product and rate_kg_ha")
                continue
            key = (row["crop"], row["product"])
            if key in seen:
                problems.append(
                    f"duplicate rate for {key[0]} on "
                    f"{key[1]}")
            seen.add(key)
            rate = row["rate_kg_ha"]
            if not isinstance(rate, (int, float)) \
                    or isinstance(rate, bool) or rate <= 0:
                problems.append(
                    f"rate for {key[0]} on {key[1]} must "
                    "be a positive number")
    elif register == REGISTER_CALENDAR:
        if set(content) != {"season_starts"} \
                or not isinstance(content["season_starts"], dict) \
                or set(content["season_starts"]) != {"kharif", "rabi"}:
            return ["content must state season_starts "
                    "for exactly kharif and rabi"]
        for season, month in content["season_starts"].items():
            if not (isinstance(month, str)
                    and len(month) == 2
                    and month.isdigit()
                    and 1 <= int(month) <= 12):
                problems.append(
                    f"season start for {season} must be "
                    "a two-digit month, 01-12")
    elif register == REGISTER_DISTRICTS:
        if set(content) != {"districts"} \
                or not isinstance(content["districts"], list) \
                or not content["districts"]:
            return ["content must carry a non-empty "
                    "districts list and nothing else"]
        seen = set()
        for row in content["districts"]:
            if not isinstance(row, dict) \
                    or set(row) != {"district_id", "name",
                                    "state", "region"}:
                problems.append(
                    f"district row {row!r} must state "
                    "exactly district_id, name, state "
                    "and region")
                continue
            if row["district_id"] in seen:
                problems.append(
                    f"duplicate district {row['district_id']}")
            seen.add(row["district_id"])
    elif register in (REGISTER_PRODUCTS, REGISTER_CROPS):
        key = "products" if register == REGISTER_PRODUCTS \
            else "crops"
        if set(content) != {key} \
                or not isinstance(content[key], list) \
                or not content[key] \
                or not all(isinstance(v, str) and v
                           for v in content[key]):
            return [f"content must carry a non-empty "
                    f"{key} list of names and nothing else"]
        if len(set(content[key])) != len(content[key]):
            problems.append(f"duplicate entries in {key}")
    else:
        problems.append(f"unknown master register: {register!r}")
    return problems


# The diff machinery is the configuration register's
# own, shared rather than restated: a change is a
# change, whichever register records it.
diff_content = diff_values


def next_label(store_versions: list[dict], register: str) -> str:
    """The label a register's next struck version
    carries: its seed label's sequence,
    patch-incremented past the highest struck."""
    base = SEED_LABELS[register]
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
