-- Month-on-month price change per item, two ways.
--
-- naive:   average price this month vs last month, over whichever premises
--          reported. Moves when the MIX of premises changes, even if no
--          price did.
-- matched: only premises that reported the item in both months, each
--          compared with itself. This is how official price indices
--          avoid the mix problem.
with per_premise as (
    select item_code, premise_code, year_month, avg(cast(price as double)) as price
    from {{ ref('fct_price') }}
    group by 1, 2, 3
),

month_pairs as (
    select year_month, lag(year_month) over (order by year_month) as prev_month
    from (select distinct year_month from per_premise) m
),

matched as (
    select
        cur.item_code,
        cur.year_month,
        mp.prev_month,
        count(*) as matched_premises,
        (sum(cur.price) / sum(prev.price) - 1) * 100 as matched_change_pct
    from per_premise cur
    join month_pairs mp on cur.year_month = mp.year_month
    join per_premise prev
      on prev.item_code = cur.item_code
     and prev.premise_code = cur.premise_code
     and prev.year_month = mp.prev_month
    group by 1, 2, 3
),

monthly_avg as (
    select item_code, year_month, avg(cast(price as double)) as avg_price
    from {{ ref('fct_price') }}
    group by 1, 2
),

naive as (
    select
        cur.item_code,
        cur.year_month,
        mp.prev_month,
        (cur.avg_price / prev.avg_price - 1) * 100 as naive_change_pct
    from monthly_avg cur
    join month_pairs mp on cur.year_month = mp.year_month
    join monthly_avg prev on prev.item_code = cur.item_code and prev.year_month = mp.prev_month
)

select
    n.item_code,
    n.year_month,
    n.prev_month,
    round(n.naive_change_pct, 2)                         as naive_change_pct,
    coalesce(m.matched_premises, 0)                      as matched_premises,
    coalesce(m.matched_premises, 0) >= {{ var('min_matched_premises') }} as enough_sample,
    case when coalesce(m.matched_premises, 0) >= {{ var('min_matched_premises') }}
         then round(m.matched_change_pct, 2) end         as matched_change_pct,
    i.item,
    i.unit,
    i.item_group
from naive n
left join matched m
  on n.item_code = m.item_code and n.year_month = m.year_month and n.prev_month = m.prev_month
left join {{ ref('dim_item') }} i on n.item_code = i.item_code
