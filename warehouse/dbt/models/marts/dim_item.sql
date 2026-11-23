-- MERGE on item_code: new items are inserted, changed names and groups are
-- updated, and an item the publisher drops from its lookup stays here, so
-- old fact rows still join. _first_seen_at is set once and never updated.
{{ config(
    materialized='incremental',
    incremental_strategy='merge',
    unique_key='item_code',
    merge_update_columns=['item', 'unit', 'item_group', 'item_category', '_last_seen_at'],
) }}

select
    item_code,
    coalesce(item, 'Unknown item')        as item,
    unit,
    coalesce(item_group, 'UNKNOWN')       as item_group,
    coalesce(item_category, 'UNKNOWN')    as item_category,
    {{ dbt.current_timestamp() }}         as _first_seen_at,
    {{ dbt.current_timestamp() }}         as _last_seen_at
from {{ ref('stg_pricecatcher__items') }}
