"""The store report: same numbers as the published analysis, and safe on a store's own files."""

from __future__ import annotations

import contextlib
import csv
import io
import json
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import build_web_dashboard as page  # noqa: E402
import crm_lifecycle  # noqa: E402
import crm_retention as cr  # noqa: E402
import store_report as sr  # noqa: E402

SHOPIFY = ROOT / "data" / "shopify_orders_example.csv"


def _normalised(obj):
    return json.loads(json.dumps(obj, sort_keys=True, default=str))


def test_reproduces_the_published_analysis_on_the_real_orders() -> None:
    # The store path and the UCI pipeline are the same analysis: on the
    # 36,969 real orders every published number must come out unchanged.
    orders = sr.read_store_orders(ROOT / "data" / "online_retail_orders.csv")
    published = json.loads((ROOT / "analysis/crm_retention_metrics.json").read_text(encoding="utf-8"))
    assert _normalised(cr.run(orders)) == published
    stages = json.loads((ROOT / "analysis/crm_lifecycle_metrics.json").read_text(encoding="utf-8"))["stages"]
    assert _normalised(crm_lifecycle.run(orders))["stages"] == stages


def test_reads_a_shopify_export_as_it_comes() -> None:
    orders = sr.read_store_orders(SHOPIFY)
    by_customer = {}
    for o in orders:
        by_customer.setdefault(o["customer_id"], []).append(o["order_id"])
    # #1001 has two line items but is one order; #1005 voided and #1007 refunded are left out.
    assert sorted(by_customer["repeat@example.com"]) == ["#1001", "#1002", "#1003"]
    assert by_customer["atrisk@example.com"] == ["#1004"]
    assert by_customer["new@example.com"] == ["#1006"]
    assert len(orders) == 7


def test_a_small_store_gets_a_page_without_empty_sections(tmp_path: Path) -> None:
    out = tmp_path / "report"
    with contextlib.redirect_stdout(io.StringIO()):
        assert sr.main(["--orders", str(SHOPIFY), "--store", "Torrefazione Nord", "--out", str(out)]) == 0
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "Torrefazione Nord" in html and "€" in html and "£" not in html
    assert 'id="markets"' not in html  # no market has 30 customers
    assert 'id="second-order"' not in html  # nobody has a year of history
    assert "first sketch" in html  # the small-sample warning reaches the page
    rows = list(csv.DictReader((out / "customers.csv").open(encoding="utf-8")))
    assert rows[0]["customer"] == "repeat@example.com"  # most valuable first
    assert {r["lifecycle_stage"] for r in rows} <= set(crm_lifecycle.LIFECYCLE_ORDER)


def test_customer_list_cannot_carry_a_spreadsheet_formula() -> None:
    assert sr._safe("=HYPERLINK(\"http://x\")") == "'=HYPERLINK(\"http://x\")"
    assert sr._safe("anna@example.com") == "anna@example.com"


def test_a_date_in_the_wrong_format_is_a_clear_error() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "orders.csv"
        bad.write_text("email,order_date,order_value\na@example.com,May 20,10\n", encoding="utf-8")
        with pytest.raises(SystemExit, match="neither YYYY-MM-DD nor DD/MM/YYYY"):
            sr.read_store_orders(bad)


def test_a_file_saved_by_italian_excel(tmp_path: Path) -> None:
    # Semicolons, decimal commas, day-first dates and the BOM Excel adds.
    f = tmp_path / "ordini.csv"
    f.write_text("email;order_date;order_value;country\n"
                 "a@example.com;20/05/2026;1.234,50;IT\n"
                 "a@example.com;2026-05-25 10:00;49,90;IT\n", encoding="utf-8-sig")
    orders = sr.read_store_orders(f)
    assert [o["order_value_gbp"] for o in orders] == [1234.5, 49.9]
    assert orders[0]["cohort_month"] == "2026-05"


def test_the_page_entry_point_returns_the_report_or_a_message(tmp_path: Path) -> None:
    import web_app
    out = json.loads(web_app.report(str(SHOPIFY), "Torrefazione Nord", "EUR", "export.csv"))
    assert out["customers"] == 5 and out["orders"] == 7
    assert "Torrefazione Nord" in out["html"] and out["customers_csv"].startswith("customer,country,")
    bad = tmp_path / "x.csv"
    bad.write_text("a,b\n1,2\n", encoding="utf-8")
    assert "Unrecognised file" in json.loads(web_app.report(str(bad)))["error"]


def test_the_public_page_is_unchanged_by_the_store_options() -> None:
    assert page.build() == page.build(meta=page.PUBLIC_PAGE)
