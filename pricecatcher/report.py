"""Report: build a static website from the gold tables.

Writes <site>/index.html (charts and tables, no JavaScript needed) and
<site>/data/*.csv (the analysis tables, for anyone who wants the numbers,
e.g. to load into Tableau or Excel).

Usage:
    python -m pricecatcher.report                # writes to site/
    python -m pricecatcher.report --site public
"""

import argparse
import csv
import html
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pricecatcher.bronze import DEFAULT_LAKE

REPO_URL = "https://github.com/faeznizam/malaysia-pricecatcher-lakehouse"
SOURCE_URL = "https://data.gov.my/data-catalogue/pricecatcher"
MOVERS_PER_SIDE = 8
SPREAD_ITEMS = 10
# An item's price spread is only shown when enough shops sell it.
MIN_SPREAD_PREMISES = 50

STYLE = """
:root {
  --surface: #fcfcfb; --surface-2: #f3f2ef; --border: #e2e1dc;
  --text: #0b0b0b; --text-2: #52514e; --muted: #75746f;
  --up: #d0473a; --down: #2a78d6; --midline: #9a998f; --series: #6b4fbb;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --surface: #1a1a19; --surface-2: #232321; --border: #383835;
    --text: #f0efec; --text-2: #c3c2b7; --muted: #9a998f;
    --up: #e0594b; --down: #3987e5; --midline: #75746f; --series: #9d86e9;
  }
}
:root[data-theme="dark"] {
  --surface: #1a1a19; --surface-2: #232321; --border: #383835;
  --text: #f0efec; --text-2: #c3c2b7; --muted: #9a998f;
  --up: #e0594b; --down: #3987e5; --midline: #75746f; --series: #9d86e9;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--surface); color: var(--text);
  font: 16px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 860px; margin: 0 auto; padding: 32px 16px 64px; }
h1 { font-size: 1.8rem; margin: 0 0 4px; }
h2 { font-size: 1.25rem; margin: 48px 0 4px; }
p.lead, .note { color: var(--text-2); margin: 4px 0 16px; }
.note { font-size: .9rem; }
a { color: var(--down); }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin: 24px 0; }
.tile { background: var(--surface-2); border-radius: 8px; padding: 12px 16px; }
.tile .v { font-size: 1.6rem; font-weight: 650; }
.tile .k { color: var(--text-2); font-size: .85rem; }
svg { width: 100%; height: auto; display: block; }
svg text { fill: var(--text); font-size: 13px; }
svg .label { fill: var(--text-2); }
svg .value { fill: var(--text); font-variant-numeric: tabular-nums; }
svg .bar.up { fill: var(--up); } svg .bar.down { fill: var(--down); }
svg .midline { stroke: var(--midline); stroke-width: 1; }
svg .baseline { stroke: var(--midline); stroke-width: 1; stroke-dasharray: 4 4; }
svg .trend { fill: none; stroke: var(--series); stroke-width: 2; }
svg .dot { fill: var(--series); stroke: var(--surface); stroke-width: 2; }
svg .axis { fill: var(--muted); font-size: 12px; }
svg g.point:hover .dot { r: 6; }
svg g.row:hover .bar { opacity: .8; }
svg g.row:hover text { font-weight: 650; }
.legend { display: flex; gap: 16px; color: var(--text-2); font-size: .85rem; margin: 4px 0 8px; }
.legend span::before { content: ""; display: inline-block; width: 10px; height: 10px;
  border-radius: 2px; margin-right: 6px; vertical-align: -1px; }
.legend .up::before { background: var(--up); } .legend .down::before { background: var(--down); }
details { margin-top: 8px; } summary { cursor: pointer; color: var(--text-2); font-size: .9rem; }
.table-wrap, .chart-wrap { overflow-x: auto; }
.chart-wrap svg { min-width: 560px; }
table { border-collapse: collapse; width: 100%; font-size: .9rem; margin-top: 8px; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border); }
th { color: var(--text-2); font-weight: 600; }
td.n, th.n { text-align: right; font-variant-numeric: tabular-nums; }
footer { margin-top: 56px; color: var(--muted); font-size: .85rem; }
"""


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def fmt(value, digits=1, sign=False) -> str:
    if value is None:
        return "–"
    return f"{value:+,.{digits}f}" if sign else f"{value:,.{digits}f}"


def diverging_bars(rows, baseline: float, value_fmt, tooltip) -> str:
    """Horizontal bars growing left (below baseline) or right (above) from a midline.

    rows: list of (label, value). Each bar has a direct value label and a
    hover tooltip; colour is never the only way to read the sign.
    """
    width, label_w, value_w, row_h = 760, 190, 64, 28
    plot_w = width - label_w - 2 * value_w
    mid = label_w + value_w + plot_w / 2
    span = max((abs(v - baseline) for _, v in rows), default=1) or 1
    scale = (plot_w / 2) / span
    height = row_h * len(rows) + 8

    parts = [f'<div class="chart-wrap"><svg viewBox="0 0 {width} {height}" role="img">']
    for i, (label, value) in enumerate(rows):
        y = 4 + i * row_h
        delta = value - baseline
        length = max(abs(delta) * scale, 2)
        x = mid if delta >= 0 else mid - length
        side = "up" if delta >= 0 else "down"
        text_x = x + length + 6 if delta >= 0 else x - 6
        anchor = "start" if delta >= 0 else "end"
        parts.append(
            f'<g class="row"><title>{esc(tooltip(label, value))}</title>'
            f'<rect x="0" y="{y}" width="{width}" height="{row_h}" fill="transparent"/>'
            f'<text class="label" x="{label_w - 8}" y="{y + 18}" text-anchor="end">{esc(label)}</text>'
            f'<rect class="bar {side}" x="{x:.1f}" y="{y + 6}" width="{length:.1f}" height="{row_h - 12}" rx="3"/>'
            f'<text class="value" x="{text_x:.1f}" y="{y + 18}" text-anchor="{anchor}">{esc(value_fmt(value))}</text>'
            f"</g>"
        )
    parts.append(f'<line class="midline" x1="{mid}" y1="0" x2="{mid}" y2="{height}"/></svg></div>')
    return "".join(parts)


def line_chart(points, baseline: float, value_fmt, tooltip) -> str:
    """One series over time: a 2px line, a dot and a value label per point,
    and a dashed reference line at the baseline. points: list of (label, value)."""
    width, height, left, right, top, bottom = 760, 220, 56, 40, 28, 32
    values = [v for _, v in points] + [baseline]
    low, high = min(values), max(values)
    pad = max((high - low) * 0.15, 0.5)
    low, high = low - pad, high + pad
    step = (width - left - right) / max(len(points) - 1, 1)

    def x(i):
        return left + i * step

    def y(v):
        return top + (high - v) / (high - low) * (height - top - bottom)

    parts = [f'<div class="chart-wrap"><svg viewBox="0 0 {width} {height}" role="img">',
             f'<line class="baseline" x1="{left}" y1="{y(baseline):.1f}" x2="{width - right}" y2="{y(baseline):.1f}"/>',
             f'<text class="axis" x="{left - 10}" y="{y(baseline) + 4:.1f}" text-anchor="end">{esc(value_fmt(baseline))}</text>']
    path = " ".join(f"{'M' if i == 0 else 'L'}{x(i):.1f},{y(v):.1f}" for i, (_, v) in enumerate(points))
    parts.append(f'<path class="trend" d="{path}"/>')
    for i, (label, value) in enumerate(points):
        parts.append(
            f'<g class="point"><title>{esc(tooltip(label, value))}</title>'
            f'<rect x="{x(i) - step / 2:.1f}" y="0" width="{step:.1f}" height="{height}" fill="transparent"/>'
            f'<circle class="dot" cx="{x(i):.1f}" cy="{y(value):.1f}" r="4"/>'
            f'<text class="value" x="{x(i):.1f}" y="{y(value) - 10:.1f}" text-anchor="middle">{esc(value_fmt(value))}</text>'
            f'<text class="axis" x="{x(i):.1f}" y="{height - 10}" text-anchor="middle">{esc(label)}</text></g>'
        )
    parts.append("</svg></div>")
    return "".join(parts)


def table(headers, rows, numeric=()) -> str:
    head = "".join(f'<th class="{"n" if i in numeric else ""}">{esc(h)}</th>' for i, h in enumerate(headers))
    body = "".join(
        "<tr>" + "".join(f'<td class="{"n" if i in numeric else ""}">{esc(c)}</td>' for i, c in enumerate(r)) + "</tr>"
        for r in rows
    )
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def write_csv(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if rows:
            writer.writerow(rows[0].asDict().keys())
            writer.writerows([list(r) for r in rows])


def build(spark, lake: Path, site: Path) -> Path:
    from pyspark.sql import functions as F

    def gold(name):
        return spark.read.format("delta").load(str(lake / "gold" / name))

    fact = gold("fact_price")
    latest_date = fact.agg(F.max("date")).first()[0]
    latest_month = latest_date.strftime("%Y-%m")
    month_fact = fact.filter(F.col("year_month") == latest_month)
    obs = month_fact.count()
    shops = month_fact.select("premise_code").distinct().count()
    items = month_fact.select("item_code").distinct().count()

    # Daily runs may only re-check the newest month, so take each month's latest run.
    log = spark.read.format("delta").load(str(lake / "meta" / "dq_run_log"))
    latest_runs = log.groupBy("year_month").agg(F.max("run_at").alias("run_at"))
    dq = {(r["year_month"], r["check_name"]): r for r in log.join(latest_runs, ["year_month", "run_at"]).collect()}
    # Formatted in Spark, which uses Malaysia time (see spark.py).
    last_checked = log.agg(F.date_format(F.max("run_at"), "dd MMM yyyy, HH:mm")).first()[0]
    months = sorted({m for m, _ in dq})
    checked = dq[(latest_month, "rows_quarantined")]["rows_checked"] if (latest_month, "rows_quarantined") in dq else 0
    quarantined = dq.get((latest_month, "rows_quarantined"))
    missing_days = dq.get((latest_month, "days_without_data"))

    state = gold("mart_state_index").filter(F.col("year_month") == latest_month).orderBy(F.desc("price_index")).collect()
    basket = state[0]["basket_items"] if state else 0

    mom = gold("mart_item_mom").filter((F.col("year_month") == latest_month) & F.col("enough_sample"))
    rises = mom.orderBy(F.desc("matched_change_pct")).limit(MOVERS_PER_SIDE).collect()
    falls = mom.orderBy("matched_change_pct").limit(MOVERS_PER_SIDE).collect()
    movers = sorted({r["item_code"]: r for r in rises + falls}.values(), key=lambda r: -r["matched_change_pct"])
    prev_month = movers[0]["prev_month"] if movers else ""
    gaps = (
        mom.withColumn("gap", F.abs(F.col("naive_change_pct") - F.col("matched_change_pct")))
        .orderBy(F.desc("gap")).limit(10).collect()
    )

    trend = gold("mart_price_trend").collect()
    trend_months = sorted({r["year_month"] for r in trend})
    trend_index = {(r["item_group"], r["year_month"]): r["price_index"] for r in trend}
    overall = [(m, trend_index[("ALL ITEMS", m)]) for m in trend_months if ("ALL ITEMS", m) in trend_index]
    trend_groups = ["ALL ITEMS"] + sorted({r["item_group"] for r in trend} - {"ALL ITEMS"})
    if len(overall) > 1:
        trend_html = (
            line_chart(overall, 100, lambda v: fmt(v), lambda m, v: f"{m}: {v:.1f} ({v - 100:+.1f}% since {overall[0][0]})")
            + "<details><summary>Show as table, by item group</summary>"
            + table(["Item group"] + trend_months,
                    [(g, *[fmt(trend_index.get((g, m))) for m in trend_months]) for g in trend_groups],
                    tuple(range(1, 1 + len(trend_months))))
            + "</details>"
        )
    else:
        trend_html = '<p class="note"><em>Not enough data yet: this needs at least two months.</em></p>'

    shop_types = (gold("mart_premise_type_index").filter(F.col("year_month") == latest_month)
                  .orderBy(F.desc("price_index")).collect())
    groups = (gold("mart_item_group_mom").filter(F.col("year_month") == latest_month)
              .orderBy(F.desc("median_change_pct")).collect())
    spread = (
        gold("mart_item_month")
        .filter((F.col("year_month") == latest_month) & (F.col("premises") >= MIN_SPREAD_PREMISES))
        .orderBy(F.desc("p90_p10_ratio")).limit(SPREAD_ITEMS).collect()
    )

    def item_label(r):
        unit = f" ({r['unit']})" if r["unit"] else ""
        return f"{r['item'] or 'Item ' + str(r['item_code'])}{unit}"

    now = datetime.now(ZoneInfo("Asia/Kuala_Lumpur")).strftime("%d %b %Y, %H:%M")
    rule_rows = ["price_too_high", "price_too_low", "price_not_positive", "duplicate_key", "null_field",
                 "unknown_item", "unknown_premise", "days_without_data"]
    if movers:
        movers_html = (
            '<div class="legend"><span class="up">price rose</span><span class="down">price fell</span></div>'
            + diverging_bars([(item_label(r), r["matched_change_pct"]) for r in movers], 0,
                             lambda v: fmt(v, 1, True) + "%", lambda s, v: f"{s}: {v:+.1f}% month on month")
            + "<details><summary>Show as table</summary>"
            + table(["Item", "Group", "Matched change %", "Shops matched", "Naive change %"],
                    [(item_label(r), r["item_group"], fmt(r["matched_change_pct"], 2, True), r["matched_premises"],
                      fmt(r["naive_change_pct"], 2, True)) for r in movers], (2, 3, 4))
            + "</details>"
        )
    else:
        movers_html = '<p class="note"><em>Not enough data yet: this needs two months with enough shops in both.</em></p>'

    body = f"""
<main>
<h1>Malaysia PriceCatcher: retail prices</h1>
<p class="lead">Data up to <strong>{latest_date:%d %b %Y}</strong>. Built automatically from
<a href="{SOURCE_URL}">data.gov.my PriceCatcher</a> by a PySpark + Delta Lake pipeline.
Page generated {now} (Malaysia time).</p>

<div class="tiles">
  <div class="tile"><div class="v">{obs:,}</div><div class="k">prices recorded in {latest_month}</div></div>
  <div class="tile"><div class="v">{shops:,}</div><div class="k">shops reporting</div></div>
  <div class="tile"><div class="v">{items:,}</div><div class="k">items tracked</div></div>
  <div class="tile"><div class="v">{fmt((quarantined['rows'] / checked * 100) if quarantined and checked else None, 3)}%</div>
    <div class="k">rows quarantined by data quality checks</div></div>
</div>

<h2>How have prices moved{f" since {overall[0][0]}" if len(overall) > 1 else ""}?</h2>
<p class="note">Price index, {overall[0][0] if overall else "first month"} = 100. Each month's change combines the matched
changes of every item sold in at least 20 of the same shops in both months (a geometric mean, the method
statistics offices use for item prices), chained month to month. Items are not weighted by how much people buy them,
so this is not the official CPI.</p>
{trend_html}

<h2>Which states are most expensive?</h2>
<p class="note">Price index for {latest_month} on a basket of {basket} items sold in every state.
Each item's median price in the state is compared with the national median; Malaysia = 100.
Not adjusted for the mix of shop types in each state.</p>
<div class="legend"><span class="up">above national level</span><span class="down">below national level</span></div>
{diverging_bars([(r["state"], r["price_index"]) for r in state], 100, lambda v: fmt(v),
                lambda s, v: f"{s}: {v:.1f} ({v - 100:+.1f} vs Malaysia)")}
<details><summary>Show as table</summary>
{table(["Rank", "State", "Index", "Basket items"],
       [(r["rank_most_expensive"], r["state"], fmt(r["price_index"]), r["basket_items"]) for r in state], (0, 2, 3))}
</details>

<h2>Which types of shop are cheapest?</h2>
<p class="note">Same method as the state index, comparing types of shop instead of states:
{latest_month}, on a basket of {shop_types[0]["basket_items"] if shop_types else 0} items sold in every type of shop.
Malaysia = 100.</p>
<div class="legend"><span class="up">above national level</span><span class="down">below national level</span></div>
{diverging_bars([(r["premise_type"], r["price_index"]) for r in shop_types], 100, lambda v: fmt(v),
                lambda s, v: f"{s}: {v:.1f} ({v - 100:+.1f} vs Malaysia)")}
<details><summary>Show as table</summary>
{table(["Rank", "Type of shop", "Index", "Basket items"],
       [(r["rank_most_expensive"], r["premise_type"], fmt(r["price_index"]), r["basket_items"]) for r in shop_types],
       (0, 2, 3))}
</details>

<h2>Where shopping around pays most</h2>
<p class="note">Items whose price varies most between shops in {latest_month}: the dearest 10% of shops
charge at least this many times what the cheapest 10% charge. Only items sold in at least
{MIN_SPREAD_PREMISES} shops.</p>
{table(["Item", "Shops", "Cheap shops (RM)", "Typical (RM)", "Dear shops (RM)", "Dear / cheap"],
       [(item_label(r), f"{r['premises']:,}", fmt(r["p10_price"], 2), fmt(r["median_price"], 2),
         fmt(r["p90_price"], 2), fmt(r["p90_p10_ratio"], 2) + "x") for r in spread], (1, 2, 3, 4, 5))}

<h2>Which kinds of goods got dearer?</h2>
<p class="note">Typical (median) matched change of the items in each group, {prev_month or "last month"} to
{latest_month}. Only items with at least 20 matched shops.</p>
<div class="legend"><span class="up">prices rose</span><span class="down">prices fell</span></div>
{diverging_bars([(r["item_group"], r["median_change_pct"]) for r in groups], 0, lambda v: fmt(v, 1, True) + "%",
                lambda s, v: f"{s}: {v:+.1f}% (median item)")}
<details><summary>Show as table</summary>
{table(["Item group", "Items", "Median change %", "Items up", "Items down"],
       [(r["item_group"], r["items"], fmt(r["median_change_pct"], 2, True), r["items_up"], r["items_down"])
        for r in groups], (1, 2, 3, 4))}
</details>

<h2>Biggest price changes{f", {prev_month} to {latest_month}" if prev_month else ""}</h2>
<p class="note">Matched change: only shops that reported the item in both months, so the result
isn't moved by which shops happened to report. Items with fewer than 20 matched shops are left out.
{latest_month} may be a partial month.</p>
{movers_html}

<h2>Why "matched" matters</h2>
<p class="note">The naive change compares plain monthly averages. When different shops report each month,
it can show a change that no shop actually made. These items show the biggest gap between the two methods.</p>
{table(["Item", "Naive change %", "Matched change %", "Shops matched"],
       [(item_label(r), fmt(r["naive_change_pct"], 2, True), fmt(r["matched_change_pct"], 2, True),
         r["matched_premises"]) for r in gaps], (1, 2, 3))}

<h2>Data quality</h2>
<p class="note">Rows failing an <em>error</em> rule are quarantined and left out of the figures above.
<em>Warn</em> rows are kept and flagged. Last checked {last_checked} (Malaysia time).</p>
{table(["Check", "Severity"] + months,
       [(name, dq[(months[0], name)]["severity"] if (months and (months[0], name) in dq) else "",
         *[f"{dq[(m, name)]['rows']:,}" if (m, name) in dq else "–" for m in months]) for name in rule_rows],
       tuple(range(2, 2 + len(months))))}

<footer>
Source: Ministry of Domestic Trade and Cost of Living (KPDN) PriceCatcher via
<a href="{SOURCE_URL}">data.gov.my</a>, CC BY 4.0. Code and method: <a href="{REPO_URL}">GitHub</a>.
Download the tables: <a href="data/mart_state_index.csv">state index</a>,
<a href="data/mart_price_trend.csv">price trend</a>, <a href="data/mart_premise_type_index.csv">shop type index</a>, <a href="data/mart_item_group_mom.csv">item group changes</a>,
<a href="data/mart_item_mom.csv">monthly changes</a>, <a href="data/mart_item_month.csv">item prices by month</a>,
<a href="data/dq_run_log.csv">data quality log</a>.
</footer>
</main>"""

    site.mkdir(parents=True, exist_ok=True)
    page = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Malaysia Retail Prices</title>"
        '<meta name="description" content="Daily-refreshed retail price analysis of Malaysia PriceCatcher data.">'
        f"<style>{STYLE}</style></head><body>{body}</body></html>"
    )
    (site / "index.html").write_text(page, encoding="utf-8")

    # The same headline numbers as plain text, for the terminal and for writing up findings.
    summary = [f"Data up to {latest_date:%d %b %Y}. Latest month {latest_month}.", "",
               f"Price trend ({trend_months[0] if trend_months else '-'} = 100):"]
    summary += [f"  {g:<28} " + "  ".join(f"{m} {fmt(trend_index.get((g, m))):>6}" for m in trend_months)
                for g in trend_groups]
    summary += ["",
               "Shop type index (Malaysia = 100):"]
    summary += [f"  {r['premise_type']:<28} {fmt(r['price_index']):>6}" for r in shop_types]
    summary += ["", f"Item groups, median matched change {prev_month} to {latest_month}:"]
    summary += [f"  {r['item_group']:<28} {fmt(r['median_change_pct'], 2, True):>7}%  "
                f"({r['items_up']} up, {r['items_down']} down)" for r in groups]
    summary += ["", "Biggest matched changes:"]
    summary += [f"  {item_label(r):<40} {fmt(r['matched_change_pct'], 2, True):>7}%  "
                f"(naive {fmt(r['naive_change_pct'], 2, True)}%, {r['matched_premises']} shops)" for r in movers]
    summary += ["", "Biggest naive vs matched gaps:"]
    summary += [f"  {item_label(r):<40} naive {fmt(r['naive_change_pct'], 2, True):>7}%  "
                f"matched {fmt(r['matched_change_pct'], 2, True):>7}%" for r in gaps]
    summary += ["", "Widest price spread between shops (p90 / p10):"]
    summary += [f"  {item_label(r):<40} RM{fmt(r['p10_price'], 2)} to RM{fmt(r['p90_price'], 2)}  "
                f"({fmt(r['p90_p10_ratio'], 2)}x)" for r in spread]
    (site / "summary.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")

    for name in ["mart_price_trend", "mart_state_index", "mart_premise_type_index", "mart_item_group_mom", "mart_item_mom",
                 "mart_item_month"]:
        table_df = gold(name)
        write_csv(site / "data" / f"{name}.csv", table_df.orderBy(*table_df.columns[:2]).collect())
    write_csv(site / "data" / "dq_run_log.csv", log.orderBy("run_at", "year_month", "check_name").collect())
    return site / "index.html"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lake", default=DEFAULT_LAKE, help="Lake folder (default: $LAKE_ROOT or lake)")
    parser.add_argument("--site", default="site", help="Output folder (default: site)")
    args = parser.parse_args(argv)
    lake = Path(args.lake)
    if not (lake / "gold" / "fact_price" / "_delta_log").exists():
        print(f"No gold tables in {lake}. Run `make gold` first.", file=sys.stderr)
        return 1

    from pricecatcher.spark import get_spark
    page = build(get_spark("pricecatcher-report"), lake, Path(args.site))
    print((page.parent / "summary.txt").read_text(encoding="utf-8"))
    print(f"Report written to {page}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
