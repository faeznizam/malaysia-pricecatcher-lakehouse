{#-
  Data quality rules for prices, one per entry: the SQL version of pricecatcher/dq.py.

  `fails` is a condition that is TRUE when a row FAILS the rule.
  Severity decides what happens to a failing row:
      error  the row goes to quarantine and is left out of fct_price
      warn   the row stays, flagged
  Adding a rule here adds its flag column, its quarantine logic and its
  line in dq_run_log; nothing else needs to change.

  Columns the rules can use (from int_prices__dq_checked):
      price_date, premise_code, item_code, price
      item_median     median price of the same item in the same month
      key_rank        1 for the first row of a (date, premise, item) key, 2+ for repeats
      known_item      true if item_code is in the item lookup
      known_premise   true if premise_code is in the premise lookup
-#}
{% macro dq_rules() %}
    {% set too_far = var('dq_too_far') %}
    {{ return([
        {'name': 'null_field', 'severity': 'error',
         'fails': 'price_date is null or premise_code is null or item_code is null or price is null'},
        {'name': 'duplicate_key', 'severity': 'error', 'fails': 'key_rank > 1'},
        {'name': 'price_not_positive', 'severity': 'error', 'fails': 'price <= 0'},
        {'name': 'price_too_high', 'severity': 'error', 'fails': 'price >= item_median * ' ~ too_far},
        {'name': 'price_too_low', 'severity': 'error', 'fails': 'price <= item_median / ' ~ too_far},
        {'name': 'unknown_item', 'severity': 'warn', 'fails': 'not known_item'},
        {'name': 'unknown_premise', 'severity': 'warn', 'fails': 'not known_premise'},
    ]) }}
{% endmacro %}


{#- One boolean column per rule (fails_<rule>), plus is_quarantined = fails any error rule.
    A rule on a null value (e.g. price <= 0 when price is null) counts as not failed;
    null_field catches those rows. -#}
{% macro dq_flag_columns() %}
    {%- set errors = [] -%}
    {%- for rule in dq_rules() %}
    coalesce({{ rule.fails }}, false) as fails_{{ rule.name }},
        {%- if rule.severity == 'error' %}{% do errors.append('fails_' ~ rule.name) %}{% endif %}
    {%- endfor %}
    {{ errors | join(' or ') }} as is_quarantined
{%- endmacro %}


{#- A readable list of the rules a row failed, e.g. 'duplicate_key price_too_high'. -#}
{% macro dq_failed_rule_names(severity) %}
    trim(
    {%- for rule in dq_rules() if rule.severity == severity %}
        case when fails_{{ rule.name }} then '{{ rule.name }} ' else '' end {%- if not loop.last %} ||{% endif %}
    {%- endfor %}
    )
{%- endmacro %}
