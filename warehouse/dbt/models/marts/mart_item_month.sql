-- Price level and spread across premises, per item per month.
with stats as (
    select
        item_code,
        year_month,
        count(*)                       as observations,
        count(distinct premise_code)   as premises,
        round(median(cast(price as double)), 2) as median_price,
        round(avg(cast(price as double)), 2)    as avg_price,
        min(price)                     as min_price,
        max(price)                     as max_price,
        round(percentile_cont(0.1) within group (order by cast(price as double)), 2) as p10_price,
        round(percentile_cont(0.9) within group (order by cast(price as double)), 2) as p90_price
    from {{ ref('fct_price') }}
    group by 1, 2
)

select
    s.*,
    round(s.p90_price / nullif(s.p10_price, 0), 2) as p90_p10_ratio,
    i.item,
    i.unit,
    i.item_group
from stats s
left join {{ ref('dim_item') }} i on s.item_code = i.item_code
