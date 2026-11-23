-- One row per clean price observation (date, premise, item).
--
-- Incremental, one month at a time: each run deletes the months it rebuilds
-- and inserts them fresh (delete+insert on year_month), like Delta's
-- replaceWhere in the PySpark path. A row-level MERGE would be wrong here:
-- a row that a fixed rule now quarantines would never be removed.
--
-- Codes missing from the lookups map to the -1 "unknown" member, so every
-- fact row joins its dimensions. The published codes are kept as source_*.
{{ config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key='year_month',
    on_schema_change='fail',
    cluster_by=['year_month'],
) }}

with clean as (
    select * from {{ ref('int_prices__dq_checked') }}
    where not is_quarantined
    {% if is_incremental() %}
      and year_month >= '{{ reprocess_from_month(this) }}'
    {% endif %}
)

select
    c.price_date,
    coalesce(p.premise_code, -1)     as premise_code,
    coalesce(i.item_code, -1)        as item_code,
    cast(c.price as decimal(10, 2))  as price,
    c.premise_code                   as source_premise_code,
    c.item_code                      as source_item_code,
    c.fails_unknown_item or c.fails_unknown_premise as has_dq_warning,
    c.year_month,
    c._source_file,
    c._ingested_at,
    {{ dbt.current_timestamp() }}    as _processed_at
from clean c
left join {{ ref('dim_item') }} i on c.item_code = i.item_code
left join {{ ref('dim_premise') }} p on c.premise_code = p.premise_code
