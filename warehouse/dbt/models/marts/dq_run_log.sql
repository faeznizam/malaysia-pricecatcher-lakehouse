-- One row per rule per month per dbt run: how many rows it caught.
-- Append-only, so it builds a history of data quality over time.
{{ config(materialized='incremental', incremental_strategy='append') }}

with checked as (
    select * from {{ ref('int_prices__dq_checked') }}
    {% if is_incremental() %}
    where year_month >= '{{ reprocess_from_month(this) }}'
    {% endif %}
)

{% for rule in dq_rules() %}
select
    '{{ invocation_id }}'          as run_id,
    {{ dbt.current_timestamp() }}  as run_at,
    year_month,
    '{{ rule.name }}'              as check_name,
    '{{ rule.severity }}'          as severity,
    sum(case when fails_{{ rule.name }} then 1 else 0 end) as rows_failed,
    count(*)                       as rows_checked
from checked
group by year_month
{% if not loop.last %}union all{% endif %}
{% endfor %}
