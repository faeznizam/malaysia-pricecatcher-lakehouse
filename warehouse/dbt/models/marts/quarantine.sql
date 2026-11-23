-- Rows that failed an error rule: kept unchanged, never deleted, with the
-- rules they failed. If a rule turns out to be wrong, fix it and re-run;
-- the rows move back into fct_price.
{{ config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key='year_month',
) }}

select
    price_date,
    premise_code,
    item_code,
    price,
    item_median,
    {{ dq_failed_rule_names('error') }} as dq_errors,
    {{ dq_failed_rule_names('warn') }}  as dq_warnings,
    year_month,
    _source_file,
    _ingested_at,
    {{ dbt.current_timestamp() }} as _processed_at
from {{ ref('int_prices__dq_checked') }}
where is_quarantined
{% if is_incremental() %}
  and year_month >= '{{ reprocess_from_month(this) }}'
{% endif %}
