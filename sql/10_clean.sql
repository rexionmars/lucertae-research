-- Cleaning layer over the br schema (ONS/ANEEL data).
-- Does not modify br: everything lives in the clean schema. Idempotent — can be re-run.
--   psql -h localhost -d terra_br -v ON_ERROR_STOP=1 -f sql/10_clean.sql
--
-- Conventions:
--   *_raw   original value from the source
--   *_flag  reason the value was nulled ('ok' when valid)
--   Physically impossible values become NULL; nothing is imputed here.

create schema if not exists clean;

drop view if exists clean.quality_summary;
drop materialized view if exists clean.pv_detail_quality_monthly;
drop materialized view if exists clean.cluster_halfhour;
drop materialized view if exists clean.pv_detail_day_flag cascade;
drop view if exists clean.pv_detail;
drop view if exists clean.pv_curtail;
drop view if exists clean.plant;
drop view if exists clean.transmission_line;

-- Physical limits used in the filters
create or replace function clean.max_poa_wm2() returns real language sql immutable as 'select 1500::real';
create or replace function clean.max_gen_over_capacity() returns real language sql immutable as 'select 1.5::real';

-- ---------------------------------------------------------------------------
-- ANEEL plant register
-- ---------------------------------------------------------------------------
create view clean.plant as
select
    ceg_core,
    name,
    kind,
    uf,
    municipality,
    case when capacity_kw > 0 then capacity_kw end                    as capacity_kw,
    case when operation_start <> date '1900-01-03' then operation_start end as operation_start,
    case when st_intersects(geom, st_makeenvelope(-74, -34, -34, 6, 4326)) then geom end as geom,
    capacity_kw                                   as capacity_kw_raw,
    operation_start                               as operation_start_raw,
    not coalesce(capacity_kw > 0, false)          as capacity_missing,
    operation_start = date '1900-01-03'           as operation_start_sentinel,
    geom is null
      or not st_intersects(geom, st_makeenvelope(-74, -34, -34, 6, 4326)) as geom_missing
from br.plant;

-- ---------------------------------------------------------------------------
-- Transmission network: published length vs. straight-line distance
-- ---------------------------------------------------------------------------
create view clean.transmission_line as
select
    l.*,
    l.published_length_km / nullif(l.straight_length_km, 0) as length_ratio,
    case
        when l.published_length_km is null or l.published_length_km = 0 then 'missing'
        when l.published_length_km < l.straight_length_km * 0.9          then 'shorter_than_straight'
        when l.published_length_km > l.straight_length_km * 3            then 'over_3x_straight'
        else 'ok'
    end as length_flag
from br.transmission_line l;

-- ---------------------------------------------------------------------------
-- Curtailment by cluster, 30 min
-- ---------------------------------------------------------------------------
-- curtailed_mw is only counted when the ONS recorded a reason and the reference is
-- usable; reference = 0 with generation > 1 MW is treated as a missing reference.
create view clean.pv_curtail as
select
    c.id_ons,
    c.cluster_key,
    c.instante,
    c.uf,
    coalesce(u.subsystem, c.subsystem)                   as subsystem,
    c.subsystem                                          as subsystem_raw,
    coalesce(u.name, c.plant_name)                       as name,
    u.capacity_mw,
    c.generation,
    c.availability,
    c.reference,
    c.reason_code,
    c.origin_code,
    c.reason_code is not null                            as is_curtailed,
    not (c.reference <= 0 and c.generation > 1)          as reference_valid,
    case
        when c.reason_code is null                       then 0
        when c.reference <= 0 and c.generation > 1       then null
        else greatest(c.reference - c.generation, 0)
    end::real                                            as curtailed_mw
from br.pv_curtail c
left join br.ons_unit u using (id_ons);

-- ---------------------------------------------------------------------------
-- Check by plant × day (series stuck or flattened at the source)
-- ---------------------------------------------------------------------------
-- flat_poa       irradiance with <= 2 distinct values between 8h and 16h
-- stuck_poa      >= 4 night intervals with irradiance > 20 (fill value)
-- flat_verified  verified generation with <= 2 distinct values in >= 10 positive
--                intervals between 8h and 16h (daily total spread evenly)
-- verified_night verified generation > 0.5 MW before 05h
create materialized view clean.pv_detail_day_flag as
select
    ceg_core,
    instante::date as day,
    count(distinct irradiance_poa) filter (where extract(hour from instante) between 8 and 16) <= 2 as flat_poa,
    count(*) filter (where (extract(hour from instante) < 5 or extract(hour from instante) >= 20)
                       and irradiance_poa > 20) >= 4                                       as stuck_poa,
    count(*) filter (where extract(hour from instante) between 8 and 16 and gen_verified > 0.1) >= 10
      and count(distinct gen_verified) filter (where extract(hour from instante) between 8 and 16
                                                 and gen_verified > 0.1) <= 2               as flat_verified,
    coalesce(max(gen_verified) filter (where extract(hour from instante) < 5) > 0.5, false) as verified_night
from br.pv_detail
group by 1, 2;

create unique index pv_detail_day_flag_pk on clean.pv_detail_day_flag (ceg_core, day);

-- ---------------------------------------------------------------------------
-- Detail by plant, 30 min
-- ---------------------------------------------------------------------------
-- irr_flag (priority): negative > above_max > night_nonzero > stuck_day > source_bad > ok
-- Only the first four null irradiance_poa; source_bad (ONS irradiance_bad)
-- is exposed but does not null, because the source semantics are not documented.
-- "Night" = before 05h or from 20h on (source local time).
create view clean.pv_detail as
with base as (
    select
        d.*,
        p.capacity_kw / 1000.0 as capacity_mw,
        case
            when d.irradiance_poa < 0                                           then 'negative'
            when d.irradiance_poa > clean.max_poa_wm2()                         then 'above_max'
            when (extract(hour from d.instante) < 5 or extract(hour from d.instante) >= 20)
                 and d.irradiance_poa > 20                                      then 'night_nonzero'
            when f.flat_poa or f.stuck_poa                                      then 'stuck_day'
            when d.irradiance_bad                                               then 'source_bad'
            else 'ok'
        end as irr_flag,
        case
            when d.gen_verified < 0                                             then 'negative'
            when d.gen_verified > p.capacity_kw / 1000.0 * clean.max_gen_over_capacity() then 'above_capacity'
            when f.flat_verified or f.verified_night                            then 'flat_day'
            else 'ok'
        end as gen_flag
    from br.pv_detail d
    left join clean.plant p using (ceg_core)
    left join clean.pv_detail_day_flag f on f.ceg_core = d.ceg_core and f.day = d.instante::date
)
select
    id_ons,
    ceg_core,
    instante,
    uf,
    subsystem,
    cluster_name,
    capacity_mw,
    case when irr_flag in ('ok', 'source_bad') then irradiance_poa end            as irradiance_poa,
    case when gen_estimated <= coalesce(capacity_mw * clean.max_gen_over_capacity(), 'infinity')
         then gen_estimated end                                                  as gen_estimated,
    case when gen_flag = 'ok' then gen_verified end                               as gen_verified,
    irradiance_poa as irradiance_poa_raw,
    gen_estimated  as gen_estimated_raw,
    gen_verified   as gen_verified_raw,
    irradiance_bad as irradiance_bad_source,
    irr_flag,
    gen_flag
from base;

-- ---------------------------------------------------------------------------
-- Aggregate by cluster × 30 min (links plants to the cluster by validity period)
-- ---------------------------------------------------------------------------
create materialized view clean.cluster_halfhour as
select
    pc.cluster_key,
    d.instante,
    count(*)                                        as n_plants,
    sum(d.capacity_mw)                              as capacity_mw,
    count(d.irradiance_poa)                         as n_poa_valid,
    avg(d.irradiance_poa)::real                     as poa_mean,
    min(d.irradiance_poa)::real                     as poa_min,
    max(d.irradiance_poa)::real                     as poa_max,
    sum(d.gen_estimated)::real                      as gen_estimated_mw,
    sum(d.gen_verified)::real                       as gen_verified_mw,
    count(*) filter (where d.irr_flag <> 'ok')      as n_irr_flagged
from clean.pv_detail d
join br.plant_cluster pc
  on pc.ceg_core = d.ceg_core
 and d.instante between pc.valid_from and pc.valid_to
group by pc.cluster_key, d.instante;

create unique index cluster_halfhour_pk on clean.cluster_halfhour (cluster_key, instante);

-- ---------------------------------------------------------------------------
-- Quality by plant × month (basis for detecting bad sensors)
-- ---------------------------------------------------------------------------
create materialized view clean.pv_detail_quality_monthly as
select
    ceg_core,
    id_ons,
    date_trunc('month', instante)::date                                       as month,
    count(*)                                                                  as n,
    count(*) filter (where extract(hour from instante) between 9 and 15)     as n_day,
    count(*) filter (where irr_flag = 'negative')                             as irr_negative,
    count(*) filter (where irr_flag = 'above_max')                            as irr_above_max,
    count(*) filter (where irr_flag = 'night_nonzero')                        as irr_night_nonzero,
    count(*) filter (where irr_flag = 'stuck_day')                            as irr_stuck_day,
    count(*) filter (where irr_flag = 'source_bad')                           as irr_source_bad,
    count(*) filter (where irr_flag = 'source_bad'
                       and extract(hour from instante) between 9 and 15)      as irr_source_bad_day,
    count(*) filter (where gen_flag = 'negative')                             as gen_negative,
    count(*) filter (where gen_flag = 'above_capacity')                       as gen_above_capacity,
    count(*) filter (where gen_flag = 'flat_day')                             as gen_flat_day,
    count(*) filter (where gen_verified_raw > gen_estimated_raw * 1.05 + 0.5
                       and extract(hour from instante) between 9 and 15)      as ver_above_est_day,
    count(*) filter (where gen_estimated_raw = 0 and irradiance_poa > 300)    as est_zero_sunny
from clean.pv_detail
group by 1, 2, 3;

create unique index pv_detail_quality_monthly_pk on clean.pv_detail_quality_monthly (ceg_core, id_ons, month);

-- ---------------------------------------------------------------------------
-- Issue summary (one row per check)
-- ---------------------------------------------------------------------------
create view clean.quality_summary as
select 'plant' as source, 'operation_start = 1900-01-03' as issue, count(*) filter (where operation_start_sentinel) as n from clean.plant
union all select 'plant', 'capacity_kw null or <= 0', count(*) filter (where capacity_missing) from clean.plant
union all select 'plant', 'geometry missing or outside Brazil', count(*) filter (where geom_missing) from clean.plant
union all select 'transmission_line', 'length ' || length_flag, count(*) from clean.transmission_line where length_flag <> 'ok' group by length_flag
union all select 'transmission_line', 'capacity_mva null', count(*) from br.transmission_line where capacity_mva is null
union all select 'pv_curtail', 'id_ons not registered in ons_unit', count(distinct id_ons) from br.pv_curtail where id_ons not in (select id_ons from br.ons_unit)
union all select 'pv_curtail', 'cluster_key null (rows)', count(*) from br.pv_curtail where cluster_key is null
union all select 'pv_curtail', 'subsystem differs from ons_unit (rows)', count(*) from clean.pv_curtail where subsystem <> subsystem_raw
union all select 'pv_curtail', 'reference = 0 with generation > 1 MW (rows)', count(*) from clean.pv_curtail where not reference_valid
union all select 'pv_curtail', 'reference_final null (rows)', count(*) from br.pv_curtail where reference_final is null
union all select 'pv_detail', 'plant not linked in plant_cluster', count(distinct ceg_core) from clean.pv_detail_quality_monthly where ceg_core not in (select ceg_core from br.plant_cluster)
union all select 'pv_detail', 'irradiance ' || f.flag || ' (rows)', f.n
  from (select 'negative' flag, sum(irr_negative) n from clean.pv_detail_quality_monthly
        union all select 'above_max', sum(irr_above_max) from clean.pv_detail_quality_monthly
        union all select 'night_nonzero', sum(irr_night_nonzero) from clean.pv_detail_quality_monthly
        union all select 'stuck_day', sum(irr_stuck_day) from clean.pv_detail_quality_monthly
        union all select 'source_bad', sum(irr_source_bad) from clean.pv_detail_quality_monthly) f
union all select 'pv_detail', 'verified generation negative (rows)', sum(gen_negative) from clean.pv_detail_quality_monthly
union all select 'pv_detail', 'verified generation > 1.5x capacity (rows)', sum(gen_above_capacity) from clean.pv_detail_quality_monthly
union all select 'pv_detail', 'verified generation flat/nighttime in the day (rows)', sum(gen_flat_day) from clean.pv_detail_quality_monthly
union all select 'pv_detail', 'plant-days with stuck irradiance', count(*) filter (where flat_poa or stuck_poa) from clean.pv_detail_day_flag
union all select 'pv_detail', 'plant-days with flat or nighttime generation', count(*) filter (where flat_verified or verified_night) from clean.pv_detail_day_flag
union all select 'pv_detail', 'verified > estimated, 9:00-15:59 (rows)', sum(ver_above_est_day) from clean.pv_detail_quality_monthly
union all select 'pv_detail', 'estimated = 0 with POA > 300 (rows)', sum(est_zero_sunny) from clean.pv_detail_quality_monthly;
