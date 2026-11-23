-- The real data quarantines well under 0.01% of rows. If a month suddenly
-- quarantines 1% or more, a rule or the source has changed: stop and look.
with counts as (
    select year_month, count(*) as clean_rows, 0 as bad_rows from {{ ref('fct_price') }} group by 1
    union all
    select year_month, 0, count(*) from {{ ref('quarantine') }} group by 1
)

select year_month, sum(bad_rows) * 1.0 / sum(clean_rows + bad_rows) as quarantine_rate
from counts
group by year_month
having sum(bad_rows) * 1.0 / sum(clean_rows + bad_rows) >= 0.01
