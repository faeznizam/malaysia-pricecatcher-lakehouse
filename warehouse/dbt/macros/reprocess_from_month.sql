{#-
  The first month an incremental run rebuilds: the latest month already in
  `relation`, minus (reprocess_months - 1). Months are 'YYYY-MM' strings.

  Example with reprocess_months = 2 and 2026-10 already loaded: returns
  '2026-09', so September (whose last days can arrive in early October)
  and October (still growing daily) are rebuilt, plus any newer month.
  An empty table returns '0000-00', which rebuilds everything.
-#}
{% macro reprocess_from_month(relation) %}
    {% set latest = none %}
    {% if execute %}
        {% set latest = run_query('select max(year_month) from ' ~ relation).columns[0].values()[0] %}
    {% endif %}
    {% if not latest %}
        {{ return('0000-00') }}
    {% endif %}
    {% set months = (latest[:4] | int) * 12 + (latest[5:7] | int) - 1 - (var('reprocess_months') - 1) %}
    {{ return('%04d-%02d' % (months // 12, months % 12 + 1)) }}
{% endmacro %}
