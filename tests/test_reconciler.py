"""Unit tests for Ads-to-CRM Revenue, Consent & Repeat-Purchase Reconciler."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import ads_crm_io as io_mod  # noqa: E402
import reconciler as rec  # noqa: E402
import web_app  # noqa: E402

FIX = ROOT / "fixtures"


class TestB2CReconciliation(unittest.TestCase):
    def setUp(self):
        self.res = rec.reconcile_b2c(
            FIX / "meta_ads_manager_schema.csv",
            FIX / "klaviyo_crm_consent_schema.csv",
            FIX / "shopify_orders_schema.csv",
            leads_path=FIX / "meta_lead_ads_schema.csv",
            ga4_path=FIX / "ga4_acquisition_schema.csv",
        )
        self.by_camp = {c["campaign_name"]: c for c in self.res["summary"]["campaigns"]}

    def test_detects_all_four_campaign_operational_archetypes(self):
        # 1. High DOI + 2nd order repeat winner -> SCALE_PROVEN_REPEAT
        win = self.by_camp["meta_prospecting_quiz_doi"]
        self.assertEqual(win["action"], "SCALE_PROVEN_REPEAT")
        self.assertEqual(win["verified_doi_leads"], 4)
        self.assertEqual(win["first_order_customers"], 3)
        self.assertEqual(win["second_order_customers"], 2)
        self.assertAlmostEqual(win["total_net_revenue"], 1045.00)
        self.assertAlmostEqual(win["ga4_revenue"], 920.00)

        # 2. Cheap Meta CPL but 4 of 5 leads unconfirmed / single opt-in / bounced -> FIX_DOI_CONSENT_LEAK
        leak = self.by_camp["meta_instantform_cheap_cpl"]
        self.assertEqual(leak["action"], "FIX_DOI_CONSENT_LEAK")
        self.assertEqual(leak["verified_doi_leads"], 1)
        self.assertEqual(leak["doi_rate_pct"], 20.0)
        # Refunded order #5007 must be excluded from net revenue
        self.assertEqual(leak["first_order_customers"], 1)
        self.assertAlmostEqual(leak["total_net_revenue"], 95.00)

        # 3. 100% 1st order via 30% coupon, 0% repeat -> FIX_POST_PURCHASE_RETENTION
        promo = self.by_camp["meta_flash_coupon_30off"]
        self.assertEqual(promo["action"], "FIX_POST_PURCHASE_RETENTION")
        self.assertEqual(promo["second_order_customers"], 0)
        self.assertAlmostEqual(promo["discount_burn"], 132.00)

        # 4. Zero orders -> PAUSE_WASTE
        waste = self.by_camp["meta_broad_unqualified"]
        self.assertEqual(waste["action"], "PAUSE_WASTE")
        self.assertEqual(waste["first_order_customers"], 0)

    def test_generates_sha256_meta_seed_and_exclusion_audiences(self):
        seed_emails = [r[0] for r in self.res["seed_rows"]]
        self.assertEqual(sorted(seed_emails), ["repeat.winner1@example.com", "repeat.winner2@example.com"])
        expected_hash = hashlib.sha256(b"repeat.winner1@example.com").hexdigest()
        self.assertEqual(self.res["seed_rows"][0][1], expected_hash)

        excl_emails = [r[0] for r in self.res["exclusion_rows"]]
        self.assertIn("leak.lead1@example.com", excl_emails)
        self.assertIn("waste.lead3@example.com", excl_emails)
        self.assertNotIn("repeat.winner1@example.com", excl_emails)

    def test_exposes_meta_roas_inflation_gap(self):
        # Meta reported revenue (450*3.4 + 300*1.8 + 240*2.1 = 2574) vs real net CRM revenue (1450)
        self.assertGreater(self.res["summary"]["totals"]["roas_inflation_gap"], 1000.0)

    def test_cli_writes_all_outputs_and_bi_fact_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "out"
            code = rec.main([
                "--mode", "b2c",
                "--ads", str(FIX / "meta_ads_manager_schema.csv"),
                "--leads", str(FIX / "meta_lead_ads_schema.csv"),
                "--crm", str(FIX / "klaviyo_crm_consent_schema.csv"),
                "--orders", str(FIX / "shopify_orders_schema.csv"),
                "--ga4", str(FIX / "ga4_acquisition_schema.csv"),
                "--out", str(out_dir),
            ])
            self.assertEqual(code, 0)
            for fname in (
                "campaign_budget_actions.csv",
                "meta_high_ltv_seed_audience.csv",
                "meta_low_quality_exclusions.csv",
                "crm_unconfirmed_paid_leads.csv",
                "fact_ads_crm_funnel.csv",
                "reconciliation_summary.json",
                "reconciliation_report.html",
            ):
                self.assertTrue((out_dir / fname).exists(), fname)


class TestB2BPipelineMode(unittest.TestCase):
    def test_hubspot_contacts_and_deals_reconciliation(self):
        res = rec.reconcile_b2b(
            FIX / "meta_b2b_ads_schema.csv",
            FIX / "hubspot_b2b_contacts_schema.csv",
            FIX / "hubspot_b2b_deals_schema.csv",
        )
        by_camp = {c["campaign_name"]: c for c in res["summary"]["campaigns"]}
        self.assertEqual(by_camp["b2b_demo_webinar_q2"]["action"], "SCALE_PIPELINE")
        self.assertEqual(by_camp["b2b_demo_webinar_q2"]["closed_won_revenue"], 4800.0)
        self.assertEqual(by_camp["b2b_demo_webinar_q2"]["open_pipeline"], 3500.0)
        self.assertEqual(by_camp["b2b_whitepaper_gated"]["action"], "FIX_LEAD_QUALITY_MQL_DROP")
        self.assertEqual(by_camp["b2b_cold_ebook_promo"]["action"], "FIX_DOI_CONSENT_LEAK")


class TestBrowserBridgeAndEdgeCases(unittest.TestCase):
    def test_utf16_meta_lead_ads_and_european_excel_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "leads_utf16.csv"
            p.write_text("email\tcampaign_name\na@example.com\tCamp_One\n", encoding="utf-16")
            _fmt, leads = io_mod.read_lead_capture(p)
            self.assertIn("a@example.com", leads)
            self.assertEqual(leads["a@example.com"]["campaign_key"], "camp_one")

    def test_web_app_b2c_and_b2b_return_clean_json(self):
        b2c = json.loads(web_app.run_b2c(
            str(FIX / "meta_ads_manager_schema.csv"),
            str(FIX / "klaviyo_crm_consent_schema.csv"),
            str(FIX / "shopify_orders_schema.csv"),
            str(FIX / "meta_lead_ads_schema.csv"),
            str(FIX / "ga4_acquisition_schema.csv"),
        ))
        self.assertEqual(b2c["summary"]["mode"], "b2c_ecommerce")
        self.assertTrue(b2c["campaign_budget_actions_csv"].startswith("campaign_name,action,"))

        b2b = json.loads(web_app.run_b2b(
            str(FIX / "meta_b2b_ads_schema.csv"),
            str(FIX / "hubspot_b2b_contacts_schema.csv"),
            str(FIX / "hubspot_b2b_deals_schema.csv"),
        ))
        self.assertEqual(b2b["summary"]["mode"], "b2b_pipeline")

    def test_formula_neutralization_in_outputs(self):
        self.assertEqual(io_mod.safe_cell("=HYPERLINK(\"http://evil\")"), "'=HYPERLINK(\"http://evil\")")

    def test_sql_warehouse_files_exist_and_are_non_empty(self):
        for fname in (
            "bigquery_ads_to_crm_funnel.sql",
            "snowflake_ads_to_crm_funnel.sql",
            "databricks_ads_to_crm_funnel.sql",
        ):
            text = (ROOT / "sql" / fname).read_text(encoding="utf-8")
            self.assertIn("fact_ads_crm_unit_economics", text.lower())


if __name__ == "__main__":
    unittest.main()
