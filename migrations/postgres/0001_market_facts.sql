-- Market data store, round 1: every fact table carries provenance
-- (source, as_of) at the row level. Writes are insert-only; primary
-- keys make a duplicate insert an error, never an overwrite.
CREATE TABLE districts (
    district_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    state TEXT NOT NULL,
    region TEXT NOT NULL
);
CREATE TABLE area_facts (
    district_id TEXT NOT NULL,
    crop_year TEXT NOT NULL,
    season TEXT NOT NULL,
    crop TEXT NOT NULL,
    area_ha DOUBLE PRECISION NOT NULL,
    source TEXT NOT NULL,
    as_of TEXT NOT NULL,
    PRIMARY KEY (district_id, crop_year, season, crop)
);
CREATE TABLE monsoon_facts (
    district_id TEXT NOT NULL,
    crop_year TEXT NOT NULL,
    season TEXT NOT NULL,
    deviation_pct DOUBLE PRECISION NOT NULL,
    source TEXT NOT NULL,
    as_of TEXT NOT NULL,
    PRIMARY KEY (district_id, crop_year, season)
);
CREATE TABLE soil_facts (
    district_id TEXT NOT NULL,
    nutrient TEXT NOT NULL,
    status TEXT NOT NULL,
    source TEXT NOT NULL,
    as_of TEXT NOT NULL,
    PRIMARY KEY (district_id, nutrient)
);
CREATE TABLE application_rates (
    crop TEXT NOT NULL,
    product TEXT NOT NULL,
    rate_kg_ha DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (crop, product)
);
CREATE TABLE consumption_facts (
    district_id TEXT NOT NULL,
    crop_year TEXT NOT NULL,
    season TEXT NOT NULL,
    product TEXT NOT NULL,
    quantity_tonnes DOUBLE PRECISION NOT NULL,
    source TEXT NOT NULL,
    as_of TEXT NOT NULL,
    PRIMARY KEY (district_id, crop_year, season, product)
);
CREATE TABLE price_points (
    series_kind TEXT NOT NULL,
    item TEXT NOT NULL,
    month TEXT NOT NULL,
    price DOUBLE PRECISION NOT NULL,
    unit TEXT NOT NULL,
    source TEXT NOT NULL,
    as_of TEXT NOT NULL,
    PRIMARY KEY (series_kind, item, month)
);
CREATE TABLE import_arrivals (
    shipment_id TEXT PRIMARY KEY,
    product TEXT NOT NULL,
    expected_month TEXT NOT NULL,
    arrived_month TEXT NOT NULL,
    quantity_tonnes DOUBLE PRECISION NOT NULL,
    origin TEXT NOT NULL,
    source TEXT NOT NULL,
    as_of TEXT NOT NULL
);
CREATE TABLE supply_facts (
    product TEXT NOT NULL,
    month TEXT NOT NULL,
    planned_tonnes DOUBLE PRECISION NOT NULL,
    actual_tonnes DOUBLE PRECISION NOT NULL,
    source TEXT NOT NULL,
    as_of TEXT NOT NULL,
    PRIMARY KEY (product, month)
);
CREATE TABLE competitor_points (
    competitor TEXT NOT NULL,
    region TEXT NOT NULL,
    product TEXT NOT NULL,
    month TEXT NOT NULL,
    volume_tonnes DOUBLE PRECISION NOT NULL,
    price DOUBLE PRECISION NOT NULL,
    source TEXT NOT NULL,
    as_of TEXT NOT NULL,
    PRIMARY KEY (competitor, region, product, month)
);
CREATE TABLE policy_events (
    event_id TEXT PRIMARY KEY,
    date TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT NOT NULL,
    expected_impact TEXT NOT NULL,
    impacted_products TEXT NOT NULL,
    source TEXT NOT NULL,
    as_of TEXT NOT NULL
);
CREATE TABLE field_reports (
    report_id TEXT PRIMARY KEY,
    reporter TEXT NOT NULL,
    district_id TEXT NOT NULL,
    date TEXT NOT NULL,
    signal_kind TEXT NOT NULL,
    product TEXT NOT NULL,
    detail TEXT NOT NULL,
    source TEXT NOT NULL,
    as_of TEXT NOT NULL
);
CREATE TABLE generator_manifest (
    id INTEGER PRIMARY KEY,
    manifest TEXT NOT NULL,
    generator_version TEXT NOT NULL
);
