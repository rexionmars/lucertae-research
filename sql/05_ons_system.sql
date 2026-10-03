-- Raw ONS system tables (load, energy balance and daily schedule).
-- Loaded by: uv run python -m lucertae.corte.ons load
-- Idempotent: only creates what does not exist. Lineage in br.source_file, like the rest of the br schema.
--
-- Time convention: `instante` is the START of the interval, in Brasília time (UTC-3),
-- same as br.pv_curtail / br.pv_detail.

-- Half-hourly load by area (API apicarga.ons.org.br)
--   cargaprogramada: used in the daily schedule/DESSEM, published the day ahead
--   cargaverificada: measured
create table if not exists br.load_halfhour (
    area                   text      not null,   -- SECO, S, NE, N
    instante               timestamp not null,
    load_programmed        real,
    load_verified          real,                 -- val_cargaglobal
    load_verified_cons     real,                 -- val_cargaglobalcons
    load_verified_no_mmgd  real,                 -- val_cargaglobalsmmgd
    load_mmgd              real,                 -- val_cargammgd (distributed micro- and mini-generation)
    load_supervised        real,
    load_unsupervised      real,
    source_programmed_id   bigint references br.source_file (source_id) on delete set null,
    source_verified_id     bigint references br.source_file (source_id) on delete set null,
    primary key (area, instante)
);

-- Verified energy balance by subsystem, hourly (MWmed)
create table if not exists br.subsystem_balance_hourly (
    subsystem    text      not null,   -- N, NE, S, SE, SIN
    instante     timestamp not null,
    hydro        real,
    thermal      real,
    wind         real,
    solar        real,
    load         real,
    interchange  real,
    source_id    bigint not null references br.source_file (source_id) on delete cascade,
    primary key (subsystem, instante)
);

-- Schedule units: links the PDP code (programacao_x_previsao) to the display code
-- (programacao_diaria), which carries type, subsystem and UF. The link is made
-- by comparing the series of 48 scheduled-generation steps in the two files.
create table if not exists br.program_unit (
    cod_pdp         text primary key,
    name_pdp        text,
    cod_exibicao    text,
    name            text,
    gen_type        text,       -- SOLAR, EÓLICA
    modality        text,       -- TIPO I, TIPO II-B, TIPO II-C
    subsystem       text,
    uf              text,
    id_ons          text,       -- cluster from br.pv_curtail, when available
    days_matched    integer,
    days_seen       integer
);

-- Daily schedule aggregated by subsystem × type × modality, 30 min
create table if not exists br.program_daily_agg (
    instante         timestamp not null,
    subsystem        text      not null,
    gen_type         text      not null,
    modality         text      not null,
    programmed_mw    real,
    availability_mw  real,
    n_units          integer,
    source_id        bigint not null references br.source_file (source_id) on delete cascade,
    primary key (instante, subsystem, gen_type, modality)
);

-- Forecast vs. scheduled for wind and solar by PDP unit, 30 min
create table if not exists br.renewable_program (
    cod_pdp        text      not null,
    instante       timestamp not null,
    forecast_mw    real,
    programmed_mw  real,
    source_id      bigint not null references br.source_file (source_id) on delete cascade,
    primary key (cod_pdp, instante)
);

create index if not exists renewable_program_time_brin on br.renewable_program using brin (instante);
create index if not exists program_daily_agg_time_brin on br.program_daily_agg using brin (instante);

-- Daily hydrology by subsystem: natural inflow energy (ENA) and stored energy (EAR)
create table if not exists br.hydro_daily (
    subsystem         text not null,
    day               date not null,
    ena_mwmed         real,
    ena_pct_mlt       real,     -- % of long-term average
    ear_mwmes         real,
    ear_pct           real,     -- % of maximum capacity
    source_id         bigint references br.source_file (source_id) on delete set null,
    primary key (subsystem, day)
);

-- Verified interchange between subsystems, hourly (MWmed; positive = origin -> destination)
create table if not exists br.interchange_hourly (
    origin       text      not null,
    destination  text      not null,
    instante     timestamp not null,
    flow_mw      real,
    source_id    bigint not null references br.source_file (source_id) on delete cascade,
    primary key (origin, destination, instante)
);

-- Archived weather forecasts (Open-Meteo Previous Runs API, ECMWF IFS 0.25°)
-- loaded by: uv run python -m lucertae.corte.weather
create table if not exists br.weather_cell (
    cell_id    text primary key,          -- 'lat_lon' rounded to 0.25°
    latitude   double precision not null,
    longitude  double precision not null
);

-- unit (ONS solar or wind cluster) -> grid cell
create table if not exists br.weather_cell_unit (
    id_ons       text not null,
    kind         text not null,           -- solar, wind
    subsystem    text,
    capacity_mw  double precision,
    cell_id      text not null references br.weather_cell (cell_id),
    primary key (id_ons, kind)
);

-- instante = start of the hour (Brasília time); lead_day = lead time of the run (1 = 24h before)
-- ghi is the hourly mean; cloud_cover and wind_speed_100m, mean of the instantaneous values at the start and end of the hour
create table if not exists br.weather_forecast (
    cell_id          text      not null references br.weather_cell (cell_id),
    model            text      not null,
    lead_day         smallint  not null,
    instante         timestamp not null,
    ghi              real,     -- W/m²
    cloud_cover      real,     -- %
    wind_speed_100m  real,     -- km/h
    source_id        bigint references br.source_file (source_id) on delete set null,
    primary key (cell_id, model, lead_day, instante)
);

-- Half-hourly marginal operating cost (CMO) by subsystem, estimated by DESSEM (R$/MWh).
-- Used only lagged (D-1, D-2): the publication date of the consolidated version is not guaranteed.
create table if not exists br.cmo_halfhour (
    subsystem  text      not null,
    instante   timestamp not null,
    cmo        real,
    source_id  bigint references br.source_file (source_id) on delete set null,
    primary key (subsystem, instante)
);

-- Constrained-off operating curtailment at wind plants (clusters), 30 min.
-- Same structure as br.pv_curtail, with the minutes tallied by reason.
create table if not exists br.wind_curtail (
    id_ons                text      not null,
    instante              timestamp not null,
    ceg                   text,
    subsystem             text,
    uf                    text,
    plant_name            text,
    connection_code       text,
    operator              text,
    generation            real,
    generation_limited    real,
    availability          real,
    reference             real,
    reference_final       real,
    unrealized_mw         real,
    reason_code           text,
    origin_code           text,
    minutes_rel           integer,
    minutes_cnf           integer,
    minutes_ene           integer,
    minutes_restriction   integer,
    source_id             bigint not null references br.source_file (source_id) on delete cascade,
    primary key (id_ons, instante)
);

create index if not exists wind_curtail_time_brin on br.wind_curtail using brin (instante);
create index if not exists wind_curtail_reason_idx on br.wind_curtail (reason_code, origin_code);
