-- Every raw price with the helper columns the rules need, and one flag per
-- rule (see macros/dq_rules.sql). fct_price keeps the rows that pass,
-- quarantine keeps the rest, dq_run_log counts them.
--
-- Both windows partition by year_month, so when an incremental run filters
-- on year_month the warehouse can skip older months entirely.
with prices as (
    select * from {{ ref('stg_pricecatcher__prices') }}
),

items as (
    select item_code from {{ ref('stg_pricecatcher__items') }}
),

premises as (
    select premise_code from {{ ref('stg_pricecatcher__premises') }}
),

enriched as (
    select
        p.*,
        median(p.price) over (partition by p.year_month, p.item_code) as item_median,
        row_number() over (
            partition by p.year_month, p.price_date, p.premise_code, p.item_code
            order by p._ingested_at, p.price
        ) as key_rank,
        i.item_code is not null  as known_item,
        pr.premise_code is not null as known_premise
    from prices p
    left join items i on p.item_code = i.item_code
    left join premises pr on p.premise_code = pr.premise_code
)

select
    *,
    {{ dq_flag_columns() }}
from enriched
