{#- Use the folder's schema name as-is (STAGING, MARTS) instead of dbt's
    default "<target schema>_<custom schema>". -#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ (custom_schema_name or target.schema) | trim }}
{%- endmacro %}
