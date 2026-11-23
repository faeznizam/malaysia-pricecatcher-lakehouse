select
    cast(item_code as bigint) as item_code,
    item,
    unit,
    item_group,
    item_category,
    _ingested_at
from {{ source('pricecatcher', 'lookup_item') }}
-- One row per code, so the MERGE into dim_item never sees a key twice
-- (Snowflake refuses a MERGE with duplicate source keys).
qualify row_number() over (partition by item_code order by item) = 1
