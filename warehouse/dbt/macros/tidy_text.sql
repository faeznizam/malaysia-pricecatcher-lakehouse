{#-
  Collapse runs of whitespace (including non-breaking, zero-width and BOM
  characters) and trim, so 'Pasar Basah' and 'Pasar Basah ' group together.
  Missing or blank becomes 'Unknown'. Same as tidy() in pricecatcher/gold.py.

  Regex functions differ between warehouses (Snowflake replaces every match
  and reads '\\s' in a string literal; DuckDB needs the 'g' flag and a single
  backslash), so this dispatches to one version per adapter.
-#}
{% macro tidy_text(column) %}
    {{ return(adapter.dispatch('tidy_text', 'pricecatcher')(column)) }}
{% endmacro %}

{% macro _odd_spaces_to_space(column) -%}
    replace(replace(replace({{ column }}, chr(160), ' '), chr(8203), ' '), chr(65279), ' ')
{%- endmacro %}

{% macro default__tidy_text(column) -%}
    coalesce(nullif(trim(regexp_replace({{ _odd_spaces_to_space(column) }}, '\\s+', ' ')), ''), 'Unknown')
{%- endmacro %}

{% macro duckdb__tidy_text(column) -%}
    coalesce(nullif(trim(regexp_replace({{ _odd_spaces_to_space(column) }}, '\s+', ' ', 'g')), ''), 'Unknown')
{%- endmacro %}
