-- One row per calendar day from the first to the last price date.
with days as (
    {{ dbt.date_spine(
        'day',
        "(select min(price_date) from " ~ ref('stg_pricecatcher__prices') ~ ")",
        "(select max(price_date) + 1 from " ~ ref('stg_pricecatcher__prices') ~ ")"
    ) }}
)

select
    cast(date_day as date)                      as date_day,
    extract(year from date_day)                 as year,
    extract(month from date_day)                as month,
    cast(extract(year from date_day) as varchar) || '-'
        || lpad(cast(extract(month from date_day) as varchar), 2, '0') as year_month,
    extract(day from date_day)                  as day,
    extract(dayofweek from date_day) in (0, 6)  as is_weekend
from days
