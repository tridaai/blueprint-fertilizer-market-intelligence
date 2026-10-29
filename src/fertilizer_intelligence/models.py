"""Fact models for the market data store.

Every fact carries provenance at the row level — ``source`` (where
the figure came from) and ``as_of`` (the date the figure describes
or was reported) — because Law 3 of the blueprint is provenance per
figure: a number without its source and date is not renderable, so
the store refuses to hold one.

Facts are insert-only. There is no update path anywhere in this
codebase: a corrected figure is a new fact under a new ``as_of``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Fact(BaseModel):
    """Base class: provenance is mandatory on every stored fact."""

    source: str = Field(min_length=1)
    as_of: str = Field(min_length=1)  # ISO date the figure describes


class District(BaseModel):
    district_id: str
    name: str
    state: str
    region: str  # north / south / east / west / central


class AreaFact(Fact):
    district_id: str
    crop_year: str  # e.g. "2024-25"
    season: str  # kharif / rabi
    crop: str
    area_ha: float


class MonsoonFact(Fact):
    district_id: str
    crop_year: str
    season: str
    deviation_pct: float  # vs long-period average; negative = deficit


class SoilFact(Fact):
    district_id: str
    nutrient: str  # nitrogen / phosphorus / potassium
    status: str  # low / medium / high


class ApplicationRate(BaseModel):
    """Stated kg/ha application rates — data, so consumption can be
    re-derived from stored inputs alone (see evals)."""

    crop: str
    product: str
    rate_kg_ha: float


class ConsumptionFact(Fact):
    district_id: str
    crop_year: str
    season: str
    product: str
    quantity_tonnes: float


class PricePoint(Fact):
    series_kind: str  # product / feedstock
    item: str  # UREA, DAP, ... / NATURAL_GAS, AMMONIA, ...
    month: str  # YYYY-MM
    price: float
    unit: str  # INR/tonne, USD/tonne, USD/MMBtu ...


class ImportArrival(Fact):
    shipment_id: str
    product: str
    expected_month: str  # YYYY-MM
    arrived_month: str  # YYYY-MM
    quantity_tonnes: float
    origin: str


class SupplyFact(Fact):
    """Domestic production vs plan, per product per month."""

    product: str
    month: str
    planned_tonnes: float
    actual_tonnes: float


class CompetitorPoint(Fact):
    competitor: str
    region: str
    product: str
    month: str
    volume_tonnes: float
    price: float  # INR/tonne


class PolicyEvent(Fact):
    event_id: str
    date: str  # ISO date
    kind: str  # subsidy_change / mrp_notification / import_policy / state_scheme
    title: str
    detail: str
    # The event's expected impact, stated as data at record time —
    # never invented commentary added later.
    expected_impact: str
    impacted_products: list[str]


class SeasonActual(Fact):
    """A season-close actual (R11): what was really consumed
    or dispatched in a district-season, imported after the
    season closed. A distinct fact class — an actual is
    never an estimate and never overwrites one; estimates
    are scored against actuals by natural key in a later
    round."""

    district_id: str
    crop_year: str
    season: str
    product: str
    actual_kind: str  # consumption / dispatch
    quantity_tonnes: float


class FieldReport(Fact):
    report_id: str
    reporter: str  # named field officer / dealer — signals stay attributed
    district_id: str
    date: str  # ISO date
    signal_kind: str  # stock_out / discounting / pest_outbreak / demand_surge / demand_slump
    product: str
    detail: str
