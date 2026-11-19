"""Ads-to-CRM Revenue, Consent & Repeat-Purchase Reconciler.

Bridges the operational gap between Ad Platforms (Meta Ads Manager, GA4) and
CRM/E-commerce systems (Klaviyo, HubSpot, Shopify):

Ad platforms report surface leads and self-attributed first-order ROAS. They do
not know:
  1. How many paid leads actually confirm GDPR Double Opt-In in the CRM
  2. What the True Cost per Verified Opt-In Lead (CPVL) is
  3. How many paid leads become net paying customers and reach a 2nd order
     (or SQL / Closed-Won deal in B2B mode)
  4. Which campaigns look cheap on Meta CPL while burning budget on unconfirmed
     leads or one-and-done discount hunters

Operational outputs generated:
  - campaign_budget_actions.csv      -> SCALE / FIX_DOI_LEAK / FIX_RETENTION / PAUSE_WASTE
  - meta_high_ltv_seed_audience.csv  -> Repeat / Closed-Won customers (email + Meta SHA-256)
  - meta_low_quality_exclusions.csv  -> Unconfirmed/bounced/junk leads (email + Meta SHA-256)
  - crm_unconfirmed_paid_leads.csv   -> Paid leads missing verified GDPR DOI for form/webhook audit
  - fact_ads_crm_funnel.csv          -> BI star-schema fact table (Power BI / Looker / Tableau)
  - reconciliation_report.html       -> Executive summary report

Pure Python standard library.
"""

from __future__ import annotations

import argparse
import json
import sys
from html import escape
from pathlib import Path

import ads_crm_io as io_mod

B2C_HEADER = [
    "campaign_name",
    "action",
    "ad_spend",
    "platform_leads",
    "platform_cpl",
    "crm_matched_leads",
    "verified_doi_leads",
    "doi_rate_pct",
    "true_cpvl_doi",
    "first_order_customers",
    "true_cac_1st_order",
    "second_order_customers",
    "repeat_rate_pct",
    "true_repeat_cac_2nd_order",
    "total_net_revenue",
    "discount_burn",
    "platform_roas",
    "true_crm_mer",
    "ga4_revenue",
    "action_reason",
]

B2B_HEADER = [
    "campaign_name",
    "action",
    "ad_spend",
    "platform_leads",
    "platform_cpl",
    "crm_matched_leads",
    "verified_doi_leads",
    "doi_rate_pct",
    "true_cpvl_doi",
    "mql_count",
    "sql_count",
    "cost_per_sql",
    "closed_won_deals",
    "closed_won_revenue",
    "open_pipeline",
    "realized_roi_x",
    "action_reason",
]

AUDIENCE_HEADER = ["email", "email_sha256", "campaign_name", "reason", "net_revenue_or_deals"]
UNCONFIRMED_HEADER = ["email", "campaign_name", "crm_consent_state", "consent_source", "consent_timestamp"]
BI_FACT_HEADER = [
    "email_sha256",
    "campaign_name",
    "mode",
    "crm_consent_state",
    "is_verified_doi",
    "orders_or_won_deals",
    "reached_second_order_or_won",
    "net_revenue",
    "discount_burn",
]


def _div(num: float, den: float) -> float | None:
    return round(num / den, 2) if den > 0 else None


def _pct(num: float, den: float) -> float:
    return round((num / den) * 100.0, 1) if den > 0 else 0.0


def _classify_b2c(c: dict) -> tuple[str, str]:
    matched = c["crm_matched_leads"]
    spend = c["ad_spend"]
    doi_rate = c["doi_rate_pct"]
    repeat_rate = c["repeat_rate_pct"]
    mer = c["true_crm_mer"] or 0.0

    if matched < 2 and spend < 100:
        return "MONITOR_LOW_VOLUME", "Too few matched leads to act on yet"
    if matched > 0 and doi_rate < 50.0:
        return (
            "FIX_DOI_CONSENT_LEAK",
            f"Only {doi_rate:.0f}% of paid leads confirmed GDPR DOI in CRM — audit form/webhook before scaling",
        )
    if c["first_order_customers"] == 0 or (spend > 0 and mer < 1.0):
        return (
            "PAUSE_WASTE",
            f"True CRM return is {mer:.2f}x on {spend:,.0f} spend — pause and reallocate budget",
        )
    if c["second_order_customers"] > 0 and repeat_rate >= 25.0 and mer >= 2.0:
        return (
            "SCALE_PROVEN_REPEAT",
            f"{doi_rate:.0f}% DOI, {repeat_rate:.0f}% repeat rate, {mer:.2f}x true CRM MER — scale & build lookalike seed",
        )
    if c["first_order_customers"] > 0 and repeat_rate < 25.0:
        return (
            "FIX_POST_PURCHASE_RETENTION",
            f"Converts 1st orders (true CAC {c['true_cac_1st_order']}) but only {repeat_rate:.0f}% reach 2nd order — check discount dependency & onboarding",
        )
    return "MAINTAIN_OPTIMIZE", f"Positive net return ({mer:.2f}x CRM MER); optimize creative & post-purchase timing"


def _classify_b2b(c: dict) -> tuple[str, str]:
    matched = c["crm_matched_leads"]
    doi_rate = c["doi_rate_pct"]
    roi = c["realized_roi_x"] or 0.0
    if matched > 0 and doi_rate < 50.0:
        return "FIX_DOI_CONSENT_LEAK", f"Only {doi_rate:.0f}% verified marketing opt-in — fix lead capture consent"
    if c["closed_won_deals"] > 0 and roi >= 2.0:
        return "SCALE_PIPELINE", f"{c['closed_won_deals']} Closed-Won ({roi:.2f}x realized ROI) — scale campaign"
    if c["mql_count"] > 0 and c["sql_count"] == 0:
        return "FIX_LEAD_QUALITY_MQL_DROP", "Generates MQLs that stall before SQL — tighten audience targeting & qualification"
    if c["sql_count"] == 0 and c["open_pipeline"] == 0:
        return "PAUSE_WASTE", "Zero MQLs, SQLs or pipeline generated — pause spend"
    return "NURTURE_PIPELINE", f"Open pipeline {c['open_pipeline']:,.0f} active — monitor SQL-to-Won velocity"


def reconcile_b2c(
    ads_path: Path,
    crm_path: Path,
    orders_path: Path,
    *,
    leads_path: Path | None = None,
    ga4_path: Path | None = None,
) -> dict:
    ads_fmt, campaigns = io_mod.read_ads_spend(ads_path)
    crm_fmt, crm_contacts = io_mod.read_crm_contacts(crm_path)
    orders_fmt, orders_by_email = io_mod.read_shopify_orders(orders_path)

    leads_fmt = None
    lead_map: dict[str, dict] = {}
    if leads_path is not None:
        leads_fmt, lead_map = io_mod.read_lead_capture(leads_path)

    ga4_by_camp = io_mod.read_ga4_campaigns(ga4_path) if ga4_path is not None else {}

    # Build unified lead -> campaign mapping from Meta Lead Ads export + CRM Initial Campaign.
    attributed: dict[str, str] = {}
    for email, rec in lead_map.items():
        attributed[email] = rec["campaign_key"]
    for email, c in crm_contacts.items():
        if email not in attributed and c["campaign_key"]:
            attributed[email] = c["campaign_key"]

    # Ensure every attributed campaign exists even if spend row is missing (spend=0).
    for email, ckey in attributed.items():
        if ckey not in campaigns:
            cname = (lead_map.get(email) or crm_contacts.get(email) or {}).get("campaign_name") or ckey
            campaigns[ckey] = {
                "campaign_key": ckey,
                "campaign_name": cname,
                "ad_spend": 0.0,
                "impressions": 0,
                "clicks": 0,
                "platform_leads": 0,
                "platform_purchases": 0,
                "platform_reported_revenue": 0.0,
            }

    per_camp_emails: dict[str, list[str]] = {k: [] for k in campaigns}
    for email, ckey in sorted(attributed.items()):
        per_camp_emails.setdefault(ckey, []).append(email)

    seed_rows: list[list[object]] = []
    exclusion_rows: list[list[object]] = []
    unconfirmed_rows: list[list[object]] = []
    fact_rows: list[list[object]] = []
    table_rows: list[list[object]] = []
    campaign_metrics: list[dict] = []

    totals = {
        "ad_spend": 0.0,
        "platform_leads": 0,
        "crm_matched_leads": 0,
        "verified_doi_leads": 0,
        "first_order_customers": 0,
        "second_order_customers": 0,
        "total_net_revenue": 0.0,
        "platform_reported_revenue": 0.0,
        "discount_burn": 0.0,
    }

    for ckey, c in sorted(campaigns.items(), key=lambda kv: -kv[1]["ad_spend"]):
        emails = per_camp_emails.get(ckey, [])
        verified = 0
        first_buyers = 0
        second_buyers = 0
        net_rev = 0.0
        disc_burn = 0.0

        for email in emails:
            crm_rec = crm_contacts.get(email, {})
            state = crm_rec.get("consent_state", "missing_from_crm")
            is_doi = state == "verified_doi"
            if is_doi:
                verified += 1
            else:
                unconfirmed_rows.append([
                    email,
                    c["campaign_name"],
                    state,
                    crm_rec.get("consent_source", ""),
                    crm_rec.get("consent_timestamp", ""),
                ])

            ord_rec = orders_by_email.get(email)
            if ord_rec:
                first_buyers += 1
                net_rev += ord_rec["total_net_revenue"]
                disc_burn += ord_rec["total_discount_burn"]
                if ord_rec["has_second_order"]:
                    second_buyers += 1
                    seed_rows.append([
                        email,
                        io_mod.sha256_email(email),
                        c["campaign_name"],
                        "repeat_customer_2plus_orders",
                        ord_rec["total_net_revenue"],
                    ])
                elif ord_rec["discount_only_buyer"] and not is_doi:
                    exclusion_rows.append([
                        email,
                        io_mod.sha256_email(email),
                        c["campaign_name"],
                        "unconfirmed_discount_only_buyer",
                        ord_rec["total_net_revenue"],
                    ])
            else:
                if state in {"hard_bounce", "opted_out", "unconfirmed", "single_optin_unconfirmed", "missing_from_crm"}:
                    exclusion_rows.append([
                        email,
                        io_mod.sha256_email(email),
                        c["campaign_name"],
                        f"non_converting_{state}",
                        0.0,
                    ])

            fact_rows.append([
                io_mod.sha256_email(email),
                c["campaign_name"],
                "b2c_ecommerce",
                state,
                str(is_doi).lower(),
                ord_rec["orders"] if ord_rec else 0,
                str(bool(ord_rec and ord_rec["has_second_order"])).lower(),
                ord_rec["total_net_revenue"] if ord_rec else 0.0,
                ord_rec["total_discount_burn"] if ord_rec else 0.0,
            ])

        net_rev = round(net_rev, 2)
        disc_burn = round(disc_burn, 2)
        spend = c["ad_spend"]
        plat_leads = c["platform_leads"]
        matched = len(emails)
        ga4_rev = ga4_by_camp.get(ckey, {}).get("ga4_revenue", 0.0)

        metric = {
            "campaign_name": c["campaign_name"],
            "ad_spend": spend,
            "platform_leads": plat_leads,
            "platform_cpl": _div(spend, plat_leads),
            "crm_matched_leads": matched,
            "verified_doi_leads": verified,
            "doi_rate_pct": _pct(verified, matched),
            "true_cpvl_doi": _div(spend, verified),
            "first_order_customers": first_buyers,
            "true_cac_1st_order": _div(spend, first_buyers),
            "second_order_customers": second_buyers,
            "repeat_rate_pct": _pct(second_buyers, first_buyers),
            "true_repeat_cac_2nd_order": _div(spend, second_buyers),
            "total_net_revenue": net_rev,
            "discount_burn": disc_burn,
            "platform_roas": _div(c["platform_reported_revenue"], spend),
            "true_crm_mer": _div(net_rev, spend),
            "ga4_revenue": ga4_rev,
        }
        action, reason = _classify_b2c(metric)
        metric["action"] = action
        metric["action_reason"] = reason
        campaign_metrics.append(metric)

        table_rows.append([
            metric["campaign_name"],
            action,
            spend,
            plat_leads,
            metric["platform_cpl"] if metric["platform_cpl"] is not None else "",
            matched,
            verified,
            metric["doi_rate_pct"],
            metric["true_cpvl_doi"] if metric["true_cpvl_doi"] is not None else "",
            first_buyers,
            metric["true_cac_1st_order"] if metric["true_cac_1st_order"] is not None else "",
            second_buyers,
            metric["repeat_rate_pct"],
            metric["true_repeat_cac_2nd_order"] if metric["true_repeat_cac_2nd_order"] is not None else "",
            net_rev,
            disc_burn,
            metric["platform_roas"] if metric["platform_roas"] is not None else "",
            metric["true_crm_mer"] if metric["true_crm_mer"] is not None else "",
            ga4_rev,
            reason,
        ])

        totals["ad_spend"] = round(totals["ad_spend"] + spend, 2)
        totals["platform_leads"] += plat_leads
        totals["crm_matched_leads"] += matched
        totals["verified_doi_leads"] += verified
        totals["first_order_customers"] += first_buyers
        totals["second_order_customers"] += second_buyers
        totals["total_net_revenue"] = round(totals["total_net_revenue"] + net_rev, 2)
        totals["platform_reported_revenue"] = round(totals["platform_reported_revenue"] + c["platform_reported_revenue"], 2)
        totals["discount_burn"] = round(totals["discount_burn"] + disc_burn, 2)

    totals["overall_doi_rate_pct"] = _pct(totals["verified_doi_leads"], totals["crm_matched_leads"])
    totals["overall_repeat_rate_pct"] = _pct(totals["second_order_customers"], totals["first_order_customers"])
    totals["overall_true_crm_mer"] = _div(totals["total_net_revenue"], totals["ad_spend"])
    totals["overall_platform_roas"] = _div(totals["platform_reported_revenue"], totals["ad_spend"])
    totals["roas_inflation_gap"] = (
        round(totals["platform_reported_revenue"] - totals["total_net_revenue"], 2)
        if totals["platform_reported_revenue"] > 0
        else 0.0
    )

    summary = {
        "mode": "b2c_ecommerce",
        "sources": {"ads": ads_fmt, "leads": leads_fmt, "crm": crm_fmt, "orders": orders_fmt, "ga4": bool(ga4_by_camp)},
        "totals": totals,
        "campaigns": campaign_metrics,
        "counts": {
            "seed_audience": len(seed_rows),
            "exclusion_audience": len(exclusion_rows),
            "unconfirmed_paid_leads": len(unconfirmed_rows),
        },
    }

    return {
        "summary": summary,
        "actions_header": B2C_HEADER,
        "actions_rows": table_rows,
        "campaign_budget_actions_csv": io_mod.to_csv_text(B2C_HEADER, table_rows),
        "meta_seed_csv": io_mod.to_csv_text(AUDIENCE_HEADER, seed_rows),
        "meta_exclusions_csv": io_mod.to_csv_text(AUDIENCE_HEADER, exclusion_rows),
        "unconfirmed_leads_csv": io_mod.to_csv_text(UNCONFIRMED_HEADER, unconfirmed_rows),
        "bi_fact_csv": io_mod.to_csv_text(BI_FACT_HEADER, fact_rows),
        "seed_rows": seed_rows,
        "exclusion_rows": exclusion_rows,
        "unconfirmed_rows": unconfirmed_rows,
    }


def reconcile_b2b(ads_path: Path, contacts_path: Path, deals_path: Path) -> dict:
    """B2B Paid-to-Pipeline reconciliation (HubSpot Contacts + Deals, Dreamdata/HockeyStack model)."""
    ads_fmt, campaigns = io_mod.read_ads_spend(ads_path)
    crm_fmt, contacts = io_mod.read_crm_contacts(contacts_path)
    deals = io_mod.read_hubspot_deals(deals_path)

    per_camp: dict[str, list[str]] = {k: [] for k in campaigns}
    for email, c in sorted(contacts.items()):
        ckey = c["campaign_key"]
        if not ckey:
            continue
        if ckey not in campaigns:
            campaigns[ckey] = {
                "campaign_key": ckey,
                "campaign_name": c["campaign_name"],
                "ad_spend": 0.0,
                "platform_leads": 0,
                "platform_reported_revenue": 0.0,
            }
        per_camp.setdefault(ckey, []).append(email)

    table_rows: list[list[object]] = []
    seed_rows: list[list[object]] = []
    exclusion_rows: list[list[object]] = []
    unconfirmed_rows: list[list[object]] = []
    fact_rows: list[list[object]] = []
    campaign_metrics: list[dict] = []

    totals = {"ad_spend": 0.0, "verified_doi_leads": 0, "mql_count": 0, "sql_count": 0, "closed_won_deals": 0, "closed_won_revenue": 0.0, "open_pipeline": 0.0}

    mql_stages = {"marketingqualifiedlead", "mql", "salesqualifiedlead", "sql", "opportunity", "customer"}
    sql_stages = {"salesqualifiedlead", "sql", "opportunity", "customer"}

    for ckey, c in sorted(campaigns.items(), key=lambda kv: -kv[1]["ad_spend"]):
        emails = per_camp.get(ckey, [])
        verified = mql = sql = won_deals = 0
        won_rev = open_pipe = 0.0

        for email in emails:
            rec = contacts[email]
            state = rec["consent_state"]
            is_doi = state == "verified_doi"
            if is_doi:
                verified += 1
            else:
                unconfirmed_rows.append([email, c["campaign_name"], state, rec["consent_source"], rec["consent_timestamp"]])

            st = rec["lifecycle_stage"]
            if st in mql_stages:
                mql += 1
            if st in sql_stages:
                sql += 1

            d = deals.get(email, {"closed_won_deals": 0, "closed_won_revenue": 0.0, "open_pipeline": 0.0})
            won_deals += d["closed_won_deals"]
            won_rev += d["closed_won_revenue"]
            open_pipe += d["open_pipeline"]

            if d["closed_won_deals"] > 0:
                seed_rows.append([email, io_mod.sha256_email(email), c["campaign_name"], "closed_won_b2b", d["closed_won_revenue"]])
            elif state in {"hard_bounce", "opted_out", "unconfirmed", "non_marketing_contact"}:
                exclusion_rows.append([email, io_mod.sha256_email(email), c["campaign_name"], f"b2b_{state}", 0.0])

            fact_rows.append([
                io_mod.sha256_email(email),
                c["campaign_name"],
                "b2b_pipeline",
                state,
                str(is_doi).lower(),
                d["closed_won_deals"],
                str(d["closed_won_deals"] > 0).lower(),
                d["closed_won_revenue"],
                0.0,
            ])

        spend = c["ad_spend"]
        won_rev = round(won_rev, 2)
        open_pipe = round(open_pipe, 2)
        metric = {
            "campaign_name": c["campaign_name"],
            "ad_spend": spend,
            "platform_leads": c["platform_leads"],
            "platform_cpl": _div(spend, c["platform_leads"]),
            "crm_matched_leads": len(emails),
            "verified_doi_leads": verified,
            "doi_rate_pct": _pct(verified, len(emails)),
            "true_cpvl_doi": _div(spend, verified),
            "mql_count": mql,
            "sql_count": sql,
            "cost_per_sql": _div(spend, sql),
            "closed_won_deals": won_deals,
            "closed_won_revenue": won_rev,
            "open_pipeline": open_pipe,
            "realized_roi_x": _div(won_rev, spend),
        }
        action, reason = _classify_b2b(metric)
        metric["action"] = action
        metric["action_reason"] = reason
        campaign_metrics.append(metric)

        table_rows.append([
            metric["campaign_name"], action, spend, c["platform_leads"],
            metric["platform_cpl"] or "", len(emails), verified, metric["doi_rate_pct"],
            metric["true_cpvl_doi"] or "", mql, sql, metric["cost_per_sql"] or "",
            won_deals, won_rev, open_pipe, metric["realized_roi_x"] or "", reason,
        ])

        totals["ad_spend"] = round(totals["ad_spend"] + spend, 2)
        totals["verified_doi_leads"] += verified
        totals["mql_count"] += mql
        totals["sql_count"] += sql
        totals["closed_won_deals"] += won_deals
        totals["closed_won_revenue"] = round(totals["closed_won_revenue"] + won_rev, 2)
        totals["open_pipeline"] = round(totals["open_pipeline"] + open_pipe, 2)

    totals["overall_realized_roi_x"] = _div(totals["closed_won_revenue"], totals["ad_spend"])
    summary = {
        "mode": "b2b_pipeline",
        "sources": {"ads": ads_fmt, "crm": crm_fmt, "deals": "hubspot_deals"},
        "totals": totals,
        "campaigns": campaign_metrics,
        "counts": {
            "seed_audience": len(seed_rows),
            "exclusion_audience": len(exclusion_rows),
            "unconfirmed_paid_leads": len(unconfirmed_rows),
        },
    }
    return {
        "summary": summary,
        "actions_header": B2B_HEADER,
        "actions_rows": table_rows,
        "campaign_budget_actions_csv": io_mod.to_csv_text(B2B_HEADER, table_rows),
        "meta_seed_csv": io_mod.to_csv_text(AUDIENCE_HEADER, seed_rows),
        "meta_exclusions_csv": io_mod.to_csv_text(AUDIENCE_HEADER, exclusion_rows),
        "unconfirmed_leads_csv": io_mod.to_csv_text(UNCONFIRMED_HEADER, unconfirmed_rows),
        "bi_fact_csv": io_mod.to_csv_text(BI_FACT_HEADER, fact_rows),
        "seed_rows": seed_rows,
        "exclusion_rows": exclusion_rows,
        "unconfirmed_rows": unconfirmed_rows,
    }


def render_report_html(result: dict) -> str:
    s = result["summary"]
    t = s["totals"]
    rows_html = "".join(
        "<tr>" + "".join(f"<td>{escape(str(cell))}</td>" for cell in row) + "</tr>"
        for row in result["actions_rows"]
    )
    head_html = "".join(f"<th>{escape(h)}</th>" for h in result["actions_header"])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Ads-to-CRM Reconciliation Report</title>
<style>
body{{font-family:system-ui,-apple-system,sans-serif;max-width:1180px;margin:28px auto;padding:0 20px;color:#111827}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:18px 0}}
.card{{border:1px solid #d1d5db;border-radius:10px;padding:12px 14px}}
.card b{{display:block;font-size:24px}}
table{{border-collapse:collapse;width:100%;font-size:13px;margin-top:14px}}
th,td{{border-bottom:1px solid #e5e7eb;padding:7px 8px;text-align:left;white-space:nowrap}}
</style></head><body>
<h1>Ads-to-CRM Reconciliation Report ({escape(s['mode'])})</h1>
<div class="grid">
  <div class="card"><span>Total Ad Spend</span><b>{t['ad_spend']:,.2f}</b></div>
  <div class="card"><span>Verified DOI Leads</span><b>{t['verified_doi_leads']}</b></div>
  <div class="card"><span>Net CRM / Won Revenue</span><b>{t.get('total_net_revenue', t.get('closed_won_revenue', 0.0)):,.2f}</b></div>
  <div class="card"><span>True Return (MER / ROI)</span><b>{t.get('overall_true_crm_mer') or t.get('overall_realized_roi_x') or 0}x</b></div>
</div>
<div style="overflow-x:auto"><table><thead><tr>{head_html}</tr></thead><tbody>{rows_html}</tbody></table></div>
</body></html>
"""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Ads-to-CRM Revenue, Consent & Repeat-Purchase Reconciler.")
    p.add_argument("--mode", choices=("b2c", "b2b"), default="b2c")
    p.add_argument("--ads", type=Path, required=True, help="Meta Ads Manager (or paid ads) CSV export")
    p.add_argument("--crm", type=Path, required=True, help="Klaviyo List Export or HubSpot Contacts CSV")
    p.add_argument("--orders", type=Path, help="Shopify Orders export (required in b2c mode)")
    p.add_argument("--leads", type=Path, help="Optional Meta Lead Ads / Analytics CSV mapping email -> campaign")
    p.add_argument("--ga4", type=Path, help="Optional GA4 Traffic Acquisition CSV")
    p.add_argument("--deals", type=Path, help="HubSpot Deals export (required in b2b mode)")
    p.add_argument("--out", type=Path, default=Path("build/reconcile"))
    args = p.parse_args(argv)

    if args.mode == "b2c":
        if not args.orders:
            sys.exit("--orders is required in b2c mode.")
        res = reconcile_b2c(args.ads, args.crm, args.orders, leads_path=args.leads, ga4_path=args.ga4)
    else:
        if not args.deals:
            sys.exit("--deals is required in b2b mode.")
        res = reconcile_b2b(args.ads, args.crm, args.deals)

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "campaign_budget_actions.csv").write_text(res["campaign_budget_actions_csv"], encoding="utf-8", newline="\n")
    (args.out / "meta_high_ltv_seed_audience.csv").write_text(res["meta_seed_csv"], encoding="utf-8", newline="\n")
    (args.out / "meta_low_quality_exclusions.csv").write_text(res["meta_exclusions_csv"], encoding="utf-8", newline="\n")
    (args.out / "crm_unconfirmed_paid_leads.csv").write_text(res["unconfirmed_leads_csv"], encoding="utf-8", newline="\n")
    (args.out / "fact_ads_crm_funnel.csv").write_text(res["bi_fact_csv"], encoding="utf-8", newline="\n")
    (args.out / "reconciliation_summary.json").write_text(json.dumps(res["summary"], indent=2) + "\n", encoding="utf-8")
    (args.out / "reconciliation_report.html").write_text(render_report_html(res), encoding="utf-8", newline="\n")

    print(json.dumps(res["summary"]["totals"], indent=2))
    print(f"\nOperational files written to {args.out}/")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
