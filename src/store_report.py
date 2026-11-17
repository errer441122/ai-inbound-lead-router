"""Retention report for your own store, from its orders export.

    python src/store_report.py --orders orders_export.csv --store "Torrefazione Nord" --currency EUR

Reads the orders export straight from Shopify (Orders > Export) or a simple CSV
with one row per order, runs the same analysis as the public page (RFM
segments, lifecycle stages, repeat purchases, time to second order, value by
market) and writes three files into --out (default: report/):

- index.html     the same page as the live dashboard, for this store
- customers.csv  one row per customer: segment, lifecycle stage and the action
                 for each, most valuable first. The list a CRM team works from;
                 check consent before mailing anyone (lifecycle-automation-lab
                 does that before it writes to Klaviyo)
- summary.json   every number on the page

Values stay in the store's currency. Nothing leaves the machine. The files
hold customer emails, so report/ is gitignored.

Pure standard library.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from html import escape
from pathlib import Path

import build_web_dashboard as page
import crm_lifecycle
import crm_retention as cr

SHOPIFY_COLUMNS = {"Name", "Email", "Created at", "Total"}
NOT_A_SALE = {"refunded", "voided"}  # Shopify "Financial Status" values
# Simple format: the first of these column names the file has.
CUSTOMER_COLUMNS = ("email", "customer_id", "customer")
VALUE_COLUMNS = ("order_value", "value", "total", "order_value_eur", "order_value_gbp")
SYMBOLS = {"EUR": "€", "GBP": "£", "USD": "$"}
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")  # same rule as build_dashboard.py
MIN_CUSTOMERS = 100  # below this, quintiles and repeat rates are too jumpy to act on


def _shopify(reader):
    """One (customer, order, day, value, country) per order; line items folded,
    cancelled, refunded and voided orders left out."""
    orders: dict[str, dict] = {}
    for row in reader:
        order = orders.setdefault(row["Name"], {})
        for k, v in row.items():
            if v and not order.get(k):
                order[k] = v
    for name, o in orders.items():
        if o.get("Cancelled at") or o.get("Financial Status", "").lower() in NOT_A_SALE:
            continue
        yield (o.get("Email"), name, (o.get("Created at") or "")[:10], o.get("Total"),
               o.get("Billing Country") or o.get("Shipping Country") or "Unknown")


def _simple(reader, columns: set[str]):
    customer = next((c for c in CUSTOMER_COLUMNS if c in columns), None)
    value = next((c for c in VALUE_COLUMNS if c in columns), None)
    if not customer or "order_date" not in columns:
        raise SystemExit(
            "Unrecognised file: expected a Shopify orders export, or a CSV with a customer column "
            f"({', '.join(CUSTOMER_COLUMNS)}) and order_date. See the README."
        )
    for i, row in enumerate(reader, start=1):
        yield (row.get(customer), row.get("order_id") or str(i), row.get("order_date"),
               row.get(value) if value else 0, row.get("country") or "Unknown")


def read_store_orders(path: Path) -> list[dict[str, object]]:
    """Orders in the shape crm_retention expects, from either file format."""
    with path.open(newline="", encoding="utf-8-sig") as fh:  # -sig: Excel adds a BOM
        reader = csv.DictReader(fh)
        columns = set(reader.fieldnames or ())
        rows = list(_shopify(reader) if SHOPIFY_COLUMNS <= columns else _simple(reader, columns))

    orders: list[dict[str, object]] = []
    for customer, order_id, day, value, country in rows:
        customer = (customer or "").strip().lower()
        if not customer or not day:
            continue
        try:
            when = date.fromisoformat(day.strip())
        except ValueError:
            raise SystemExit(f"Order {order_id}: date {day!r} is not YYYY-MM-DD.") from None
        orders.append({"customer_id": customer, "order_id": order_id, "order_date": when,
                       # the key says gbp because the UCI data is in pounds; here it is the store's currency
                       "order_value_gbp": float(value or 0), "country": country.strip()})

    first: dict[str, date] = {}
    for o in orders:
        cid = o["customer_id"]
        if cid not in first or o["order_date"] < first[cid]:
            first[cid] = o["order_date"]
    for o in orders:
        o["signup_date"] = first[o["customer_id"]]
        o["cohort_month"] = o["signup_date"].strftime("%Y-%m")
    return orders


def _safe(text: str) -> str:
    """A cell Excel would read as a formula gets a leading apostrophe."""
    return "'" + text if text.startswith(FORMULA_START) else text


def customer_rows(orders: list[dict[str, object]]) -> list[list[object]]:
    as_of = cr.reference_date(orders)
    by_customer = cr.rfm(orders, as_of)["_by_customer"]
    stage = crm_lifecycle.lifecycle(orders)
    rows = []
    for cid, c in sorted(by_customer.items(), key=lambda kv: -kv[1]["monetary"]):
        s = stage[cid]
        rows.append([_safe(cid), _safe(str(c["country"])), c["orders"], round(c["monetary"], 2),
                     c["last"].isoformat(), s["recency_days"], c["segment"], cr.AUTOMATION[c["segment"]][0],
                     s["stage"], crm_lifecycle.STAGE_ACTION[s["stage"]]])
    return rows


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--orders", type=Path, required=True, help="Shopify orders export, or a simple orders CSV")
    p.add_argument("--store", default="your store", help="store name shown on the page")
    p.add_argument("--currency", default="EUR", help="ISO code of the store's currency")
    p.add_argument("--out", type=Path, default=Path("report"))
    args = p.parse_args(argv)

    orders = read_store_orders(args.orders)
    if not orders:
        print("No orders with a customer and a date in this file.")
        return 1
    crm = cr.run(orders)
    crm["dataset"] = args.orders.name
    life = crm_lifecycle.run(orders)
    life["dataset"] = args.orders.name

    today = date.today().isoformat()
    code = args.currency.upper()
    customers = crm["rfm"]["total_customers"]
    small = (f" Only {customers:,} customers: segments and repeat rates move a lot with each one, "
             f"so read them as a first sketch.") if customers < MIN_CUSTOMERS else ""
    if small:
        print(small.strip())
    meta = {
        "title": f"{args.store}: retention report",
        "name": args.store,
        "eyebrow": f"Retention report, {today}",
        "who": f"customers of {args.store}",
        "symbol": SYMBOLS.get(code, code + " "),
        "currency_note": f"in {code}",
        "lifecycle_note": "The same rules the Klaviyo win-back in lifecycle-automation-lab uses as its trigger.",
        "next_title": "What to do next",
        "next_note": "Recommendations from this store's order history. Test each one against a group that does not receive it.",
        "footer": (f"<p>Generated on {today} by store_report.py from {escape(args.orders.name)}. "
                   f"Figures describe past orders; they are not forecasts.{escape(small)}</p>"),
        "public": False,
    }

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "index.html").write_text(page.build(crm, life, meta), encoding="utf-8", newline="\n")
    rows = customer_rows(orders)
    with (args.out / "customers.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["customer", "country", "orders", "spend", "last_order", "days_since_last_order",
                    "rfm_segment", "segment_flow", "lifecycle_stage", "stage_action"])
        w.writerows(rows)
    (args.out / "summary.json").write_text(
        json.dumps({"retention": crm, "lifecycle": life}, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8", newline="\n")
    print(f"{len(rows):,} customers, {len(orders):,} orders -> "
          f"{args.out / 'index.html'}, customers.csv, summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
