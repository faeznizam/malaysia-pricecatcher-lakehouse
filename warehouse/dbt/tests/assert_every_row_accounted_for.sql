-- Every raw row ends up in exactly one place: fct_price or quarantine.
-- Nothing is silently dropped or duplicated between layers.
with raw_counts as (
    select year_month, count(*) as n from {{ ref('stg_pricecatcher__prices') }} group by 1
),
out_counts as (
    select year_month, count(*) as n from (
        select year_month from {{ ref('fct_price') }}
        union all
        select year_month from {{ ref('quarantine') }}
    ) x
    group by 1
)

select r.year_month, r.n as raw_rows, o.n as output_rows
from raw_counts r
left join out_counts o on r.year_month = o.year_month
where o.n is null or o.n <> r.n
