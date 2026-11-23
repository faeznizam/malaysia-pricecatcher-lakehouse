-- Raw prices with clear names and types. No rows are dropped here; the data
-- quality rules run in int_prices__dq_checked.
select
    cast(date as date)          as price_date,
    cast(premise_code as bigint) as premise_code,
    cast(item_code as bigint)    as item_code,
    cast(price as double)        as price,
    year_month,
    _source_file,
    _ingested_at
from {{ source('pricecatcher', 'prices') }}
