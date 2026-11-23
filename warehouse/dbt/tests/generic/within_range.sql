{#- Fails for every row where `column_name` is outside [min_value, max_value]. -#}
{% test within_range(model, column_name, min_value, max_value) %}
select * from {{ model }}
where {{ column_name }} < {{ min_value }} or {{ column_name }} > {{ max_value }}
{% endtest %}
