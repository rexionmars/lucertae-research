-- Clean layer for the system variables (load, wind, ONS daily schedule).
-- Depends on sql/05_ons_system.sql loaded by terra_energy_research.ons.
--   psql -h localhost -d terra_br -v ON_ERROR_STOP=1 -f sql/20_clean_system.sql
--
-- Temporal availability:
--   *_programmed, *_forecast, plan_*  published the day ahead (~23h on D-1) -> ex-ante
--   *_verified                        measured                              -> ex-post
-- The schedule files may have been revised after publication; the history
-- downloaded today is not guaranteed to be the exact version that existed on D-1.

drop view if exists clean.wind_curtail;
drop materialized view if exists clean.system_halfhour;
drop materialized view if exists clean.unit_plan;

-- ---------------------------------------------------------------------------
-- ONS day-ahead (D-1) plan by cluster (solar or wind): forecast vs. scheduled
-- ---------------------------------------------------------------------------
create materialized view clean.unit_plan as
select
    u.id_ons,
    r.instante,
    sum(r.forecast_mw)::real                                          as plan_forecast_mw,
    sum(r.programmed_mw)::real                                        as plan_programmed_mw,
    sum(greatest(coalesce(r.forecast_mw, 0) - coalesce(r.programmed_mw, 0), 0))::real as plan_cut_mw,
    count(*)                                                          as n_pdp_units
from br.renewable_program r
join br.program_unit u using (cod_pdp)
where u.id_ons is not null
group by 1, 2;

create unique index unit_plan_pk on clean.unit_plan (id_ons, instante);

-- ---------------------------------------------------------------------------
-- System by subsystem × 30 min
-- ---------------------------------------------------------------------------
create materialized view clean.system_halfhour as
with load as (
    select
        case area when 'SECO' then 'SE' else area end as subsystem,
        instante,
        load_programmed,
        load_verified,
        load_mmgd
    from br.load_halfhour
),
program as (
    select
        instante,
        subsystem,
        sum(programmed_mw) filter (where gen_type = 'EÓLICA')                           as wind_programmed,
        sum(programmed_mw) filter (where gen_type = 'SOLAR' and modality <> 'TIPO III')  as solar_central_programmed,
        sum(programmed_mw) filter (where gen_type = 'SOLAR' and modality = 'TIPO III')   as solar_distributed_programmed,
        sum(programmed_mw) filter (where gen_type = 'HIDRÁULICA')                       as hydro_programmed,
        sum(programmed_mw) filter (where gen_type = 'TÉRMICA')                          as thermal_programmed
    from br.program_daily_agg
    group by 1, 2
),
renewable as (
    select
        r.instante,
        u.subsystem,
        sum(r.forecast_mw) filter (where u.gen_type = 'EÓLICA')                         as wind_forecast,
        sum(greatest(coalesce(r.forecast_mw, 0) - coalesce(r.programmed_mw, 0), 0))
            filter (where u.gen_type = 'EÓLICA')                                        as wind_plan_cut,
        sum(r.forecast_mw) filter (where u.gen_type = 'SOLAR')                          as solar_forecast,
        sum(greatest(coalesce(r.forecast_mw, 0) - coalesce(r.programmed_mw, 0), 0))
            filter (where u.gen_type = 'SOLAR')                                         as solar_plan_cut
    from br.renewable_program r
    join br.program_unit u using (cod_pdp)
    group by 1, 2
),
cmo as (
    select subsystem, instante, cmo from br.cmo_halfhour
),
balance as (
    -- hourly -> replicated into the two 30-min intervals of the hour
    select b.subsystem, b.instante + h.offset_ as instante,
           b.wind as wind_verified, b.solar as solar_verified, b.hydro as hydro_verified,
           b.thermal as thermal_verified, b.load as load_balance_verified
    from br.subsystem_balance_hourly b
    cross join (values (interval '0 minutes'), (interval '30 minutes')) as h(offset_)
    where b.subsystem <> 'SIN'
)
select
    l.subsystem,
    l.instante,
    l.load_programmed::real,
    l.load_verified::real,
    l.load_mmgd::real,
    p.wind_programmed::real,
    p.solar_central_programmed::real,
    p.solar_distributed_programmed::real,
    p.hydro_programmed::real,
    p.thermal_programmed::real,
    r.wind_forecast::real,
    r.wind_plan_cut::real,
    r.solar_forecast::real,
    r.solar_plan_cut::real,
    -- scheduled net load: what is left for hydro/thermal after variable renewables
    (l.load_programmed - coalesce(p.wind_programmed, 0) - coalesce(p.solar_central_programmed, 0)
                       - coalesce(p.solar_distributed_programmed, 0))::real        as net_load_programmed,
    c.cmo::real,
    b.wind_verified::real,
    b.solar_verified::real,
    b.hydro_verified::real,
    b.thermal_verified::real,
    (l.load_verified - coalesce(b.wind_verified, 0) - coalesce(b.solar_verified, 0))::real as net_load_verified
from load l
left join program p   on p.subsystem = l.subsystem and p.instante = l.instante
left join renewable r on r.subsystem = l.subsystem and r.instante = l.instante
left join cmo c       on c.subsystem = l.subsystem and c.instante = l.instante
left join balance b   on b.subsystem = l.subsystem and b.instante = l.instante;

create unique index system_halfhour_pk on clean.system_halfhour (subsystem, instante);

-- ---------------------------------------------------------------------------
-- Curtailment at wind clusters, 30 min (mirrors clean.pv_curtail)
-- ---------------------------------------------------------------------------
create view clean.wind_curtail as
select
    w.id_ons,
    w.instante,
    w.uf,
    coalesce(u.subsystem, w.subsystem)                   as subsystem,
    w.subsystem                                          as subsystem_raw,
    coalesce(u.name, w.plant_name)                       as name,
    u.capacity_mw,
    w.generation,
    w.availability,
    w.reference,
    w.reason_code,
    w.origin_code,
    w.minutes_restriction,
    w.reason_code is not null                            as is_curtailed,
    not (w.reference <= 0 and w.generation > 1)          as reference_valid,
    case
        when w.reason_code is null                       then 0
        when w.reference <= 0 and w.generation > 1       then null
        else greatest(w.reference - w.generation, 0)
    end::real                                            as curtailed_mw
from br.wind_curtail w
left join br.ons_unit u using (id_ons);
