-- Same MERGE pattern as dim_item.
{{ config(
    materialized='incremental',
    incremental_strategy='merge',
    unique_key='premise_code',
    merge_update_columns=['premise', 'address', 'premise_type', 'state', 'district', '_last_seen_at'],
) }}

select
    premise_code,
    premise,
    address,
    premise_type,
    state,
    district,
    {{ dbt.current_timestamp() }} as _first_seen_at,
    {{ dbt.current_timestamp() }} as _last_seen_at
from {{ ref('stg_pricecatcher__premises') }}
