{#-
  How expensive each group of premises is, on the same basket of items
  (Malaysia = 100). `by` is a dim_premise column, e.g. state or premise_type.

  For each month, the basket is the items sold in every group. For each item,
  a group's median price is divided by the national median; the group's index
  is the average of those ratios x 100. Same method as build_price_index() in
  pricecatcher/gold.py.
-#}
{% macro price_index(by) %}
with prices as (
    select f.year_month, f.item_code, p.{{ by }} as grp, cast(f.price as double) as price
    from {{ ref('fct_price') }} f
    join {{ ref('dim_premise') }} p on f.premise_code = p.premise_code
    where p.{{ by }} <> 'Unknown'
),
group_item as (
    select year_month, grp, item_code, median(price) as group_median
    from prices group by 1, 2, 3
),
national as (
    select year_month, item_code, median(price) as national_median
    from prices group by 1, 2
),
groups_per_month as (
    select year_month, count(distinct grp) as n_groups from prices group by 1
),
basket as (
    select gi.year_month, gi.item_code
    from group_item gi
    join groups_per_month g on gi.year_month = g.year_month
    group by gi.year_month, gi.item_code, g.n_groups
    having count(distinct gi.grp) = g.n_groups
),
indexed as (
    select gi.year_month, gi.grp as {{ by }},
           count(*) as basket_items,
           round(avg(gi.group_median / n.national_median) * 100, 1) as price_index
    from group_item gi
    join basket b on gi.year_month = b.year_month and gi.item_code = b.item_code
    join national n on gi.year_month = n.year_month and gi.item_code = n.item_code
    group by 1, 2
)
select *, rank() over (partition by year_month order by price_index desc) as rank_most_expensive
from indexed
{% endmacro %}
