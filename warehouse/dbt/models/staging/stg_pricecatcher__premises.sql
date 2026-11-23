select
    cast(premise_code as bigint) as premise_code,
    premise,
    address,
    {{ tidy_text('premise_type') }} as premise_type,
    {{ tidy_text('state') }}        as state,
    {{ tidy_text('district') }}     as district,
    _ingested_at
from {{ source('pricecatcher', 'lookup_premise') }}
-- One row per code, so the MERGE into dim_premise never sees a key twice.
qualify row_number() over (partition by premise_code order by premise) = 1
