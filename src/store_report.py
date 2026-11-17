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

Files saved again by Excel work too: comma, semicolon or tab separators,
decimal commas, DD/MM/YYYY dates. The browser page (docs/app.html) runs this
same code on a file the user picks. Values stay in the store's currency.
Nothing leaves the machine. The files hold customer emails, so report/ is
gitignored.

Pure standard library.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
from datetime import date, datetime
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
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y")
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")  # same rule as build_dashboard.py
MIN_CUSTOMERS = 100  # below this, quintiles and repeat rates are too jumpy to act on
CUSTOMER_HEADER = ["customer", "country", "orders", "spend", "last_order", "days_since_last_order",
                   "rfm_segment", "segment_flow", "lifecycle_stage", "stage_action"]


def read_csv(path: Path) -> csv.DictReader:
    """Rows of a CSV as real tools save it: comma, semicolon (Italian Excel) or
    tab as separator, with or without the byte-order mark Excel adds."""
    text = path.read_text(encoding="utf-8-sig")
    header = text.split("\n", 1)[0]
    return csv.DictReader(io.StringIO(text, newline=""), delimiter=max(",;\t", key=header.count))


def parse_day(text: str | None) -> date | None:
    """Date from "2026-05-20", "2026-05-20 14:03:00 +0200" or "20/05/2026"; None if empty."""
    text = (text or "").strip()
    if not text:
        return None
    head = text.split()[0].split("T")[0]
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(head, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"date {text!r} is neither YYYY-MM-DD nor DD/MM/YYYY")


def parse_amount(text: str | None) -> float:
    """Number from "49.90", "49,90", "1.234,56" or "1,234.56" (currency signs ignored)."""
    t = "".join(ch for ch in (text or "") if ch.isdigit() or ch in ",.-")
    if not t:
        return 0.0
    if "," in t and "." in t:  # the separator that comes last is the decimal one
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    else:
        t = t.replace(",", ".")
    return float(t)


def _shopify(reader):
    """One (customer, order, date text, value, country) per order; line items
    folded, cancelled, refunded and voided orders left out."""
    orders: dict[str, dict] = {}
    for row in reader:
        order = orders.setdefault(row["Name"], {})
        for k, v in row.items():
            if v and not order.get(k):
                order[k] = v
    for name, o in orders.items():
        if o.get("Cancelled at") or o.get("Financial Status", "").lower() in NOT_A_SALE:
            continue
        yield (o.get("Email"), name, o.get("Created at"), o.get("Total"),
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
    reader = read_csv(path)
    columns = set(reader.fieldnames or ())
    rows = list(_shopify(reader) if SHOPIFY_COLUMNS <= columns else _simple(reader, columns))

    orders: list[dict[str, object]] = []
    for customer, order_id, day, value, country in rows:
        customer = (customer or "").strip().lower()
        try:
            when = parse_day(day)
            amount = parse_amount(value)
        except ValueError as e:
            raise SystemExit(f"Order {order_id}: {e}.") from None
        if not customer or when is None:
            continue
        orders.append({"customer_id": customer, "order_id": order_id, "order_date": when,
                       # the key says gbp because the UCI data is in pounds; here it is the store's currency
                       "order_value_gbp": amount, "country": country.strip()})

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


def make_report(path: Path, store: str = "your store", currency: str = "EUR",
                source_name: str | None = None) -> dict:
    """Everything the report consists of, as text: what main() writes to disk and
    what the browser page offers for download."""
    orders = read_store_orders(path)
    if not orders:
        raise SystemExit("No orders with a customer and a date in this file.")
    name = source_name or path.name
    crm = cr.run(orders)
    crm["dataset"] = name
    life = crm_lifecycle.run(orders)
    life["dataset"] = name

    today = date.today().isoformat()
    code = currency.upper()
    customers = crm["rfm"]["total_customers"]
    small = (f" Only {customers:,} customers: segments and repeat rates move a lot with each one, "
             f"so read them as a first sketch.") if customers < MIN_CUSTOMERS else ""
    meta = {
        "title": f"{store}: retention report",
        "name": store,
        "eyebrow": f"Retention report, {today}",
        "who": f"customers of {store}",
        "symbol": SYMBOLS.get(code, code + " "),
        "currency_note": f"in {code}",
        "lifecycle_note": "The same rules the Klaviyo win-back in lifecycle-automation-lab uses as its trigger.",
        "next_title": "What to do next",
        "next_note": "Recommendations from this store's order history. Test each one against a group that does not receive it.",
        "footer": (f"<p>Generated on {today} from {escape(name)}. "
                   f"Figures describe past orders; they are not forecasts.{escape(small)}</p>"),
        "public": False,
        "app_link": "",
    }
    rows = customer_rows(orders)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CUSTOMER_HEADER)
    w.writerows(rows)
    return {
        "html": page.build(crm, life, meta),
        "customers_csv": buf.getvalue(),
        "summary_json": json.dumps({"retention": crm, "lifecycle": life}, indent=2, sort_keys=True, default=str) + "\n",
        "customers": customers,
        "orders": len(orders),
        "warning": small.strip(),
        "header": CUSTOMER_HEADER,
        "top_customers": rows[:25],
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--orders", type=Path, required=True, help="Shopify orders export, or a simple orders CSV")
    p.add_argument("--store", default="your store", help="store name shown on the page")
    p.add_argument("--currency", default="EUR", help="ISO code of the store's currency")
    p.add_argument("--out", type=Path, default=Path("report"))
    args = p.parse_args(argv)

    report = make_report(args.orders, args.store, args.currency)
    if report["warning"]:
        print(report["warning"])
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "index.html").write_text(report["html"], encoding="utf-8", newline="\n")
    (args.out / "customers.csv").write_text(report["customers_csv"], encoding="utf-8", newline="\n")
    (args.out / "summary.json").write_text(report["summary_json"], encoding="utf-8", newline="\n")
    print(f"{report['customers']:,} customers, {report['orders']:,} orders -> "
          f"{args.out / 'index.html'}, customers.csv, summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
