"""Data quality rules for silver, one per line.

Each rule is a condition that is TRUE when a row FAILS the rule.
Severity decides what happens to a failing row:

    error  the row goes to quarantine and is left out of analysis
    warn   the row stays in silver, tagged with the rule's name

The evidence behind each rule is in docs/data_profile.md.

Columns available to rules (added by pricecatcher/silver.py):
    date, premise_code, item_code, price   from bronze
    item_median     median price of the same item in the same month
    key_rank        1 for the first row of a (date, premise, item) key, 2+ for repeats
    known_item      True if item_code is in lookup_item
    known_premise   True if premise_code is in lookup_premise
"""

import warnings
from dataclasses import dataclass
from typing import Callable

from pyspark.sql import Column
from pyspark.sql import functions as F

# How far from its item's median a price may be before we treat it as a typo.
# The profile found mistyped prices at 10x and 100x the median.
TOO_FAR = 10


@dataclass(frozen=True)
class Rule:
    name: str
    severity: str  # "error" or "warn"
    description: str
    fails: Callable[[], Column]


RULES = [
    Rule("null_field", "error", "date, premise_code, item_code or price is missing",
         lambda: F.col("date").isNull() | F.col("premise_code").isNull()
         | F.col("item_code").isNull() | F.col("price").isNull()),
    Rule("duplicate_key", "error", "repeat of an earlier row for the same date, premise and item",
         lambda: F.col("key_rank") > 1),
    Rule("price_not_positive", "error", "price is zero or negative",
         lambda: F.col("price") <= 0),
    Rule("price_too_high", "error", f"price is {TOO_FAR}x or more its item's median (missing decimal point)",
         lambda: F.col("price") >= F.col("item_median") * TOO_FAR),
    Rule("price_too_low", "error", f"price is 1/{TOO_FAR} or less of its item's median",
         # YOUR TURN (Faez): replace the line below with the condition that is
         # True when the price is TOO_FAR times smaller than the item's median,
         # or less. Look at price_too_high just above: it is almost the mirror.
         lambda: _not_written_yet("price_too_low")),
    Rule("unknown_item", "warn", "item_code is not in lookup_item yet",
         lambda: ~F.col("known_item")),
    Rule("unknown_premise", "warn", "premise_code is not in lookup_premise yet",
         lambda: ~F.col("known_premise")),
]


def _not_written_yet(name: str) -> Column:
    """Placeholder: the rule catches nothing until it is written."""
    warnings.warn(f"Rule {name!r} is not written yet, so it catches nothing (see pricecatcher/dq.py)", stacklevel=2)
    return F.lit(False)
