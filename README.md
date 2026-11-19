# Ads-to-CRM Revenue, Consent & Repeat-Purchase Reconciler

Reconcile **Meta Ads Manager** and **GA4** ad spend directly against verified **GDPR Double Opt-In** consent and real **1st-order / 2nd-order** (or B2B **MQL → SQL → Closed-Won**) revenue in **Klaviyo**, **HubSpot**, and **Shopify**.

**[Launch the browser workbench (zero upload — runs locally via Pyodide)](https://errer441122.github.io/digital-campaign-performance-dashboard/)**

---

## Operational Gap Covered

Ad platforms optimize for surface conversions (cheap Instant Form CPLs, view-through first orders) without visibility into what happens inside the CRM:

- **Vanity CPL vs. True Cost per Verified Opt-In (CPVL):** a Meta Lead Ads campaign can show a low CPL while 80% of leads never confirm GDPR Double Opt-In, arrive as non-compliant single opt-in leaks, or hard bounce.
- **ROAS Inflation vs. Net Repeat Economics:** platform ROAS includes refunded/cancelled orders and heavy coupon burn, and never distinguishes *one-and-done discount hunters* from campaigns that bring full-price **2nd-order repeat buyers**.
- **B2B Lead Quality Drop (Dreamdata / HockeyStack model):** paid campaigns can flood HubSpot with unconfirmed leads or MQLs that never turn into SQLs or Closed-Won pipeline.

---

## Day-1 Native Platform Exports Supported

| Category | Platforms | Native CSV Export Accepted |
| --- | --- | --- |
| **Advertising** | **Meta Business (Ads Manager & Lead Center)** | *Ads Manager > Export table data (.csv)* (`Campaign name`, `Amount spent`, `Leads`, `Purchases`, `Purchase ROAS`) + *Instant Forms > Download Leads (.csv / UTF-16 TSV)* |
| **Web / Product Analytics** | **GA4**, Amplitude, Mixpanel, Adobe Analytics | *GA4 > Traffic/User acquisition > Export CSV* (auto-strips `#` header lines) + generic `email`/`utm_campaign` event attribution adapter |
| **ESP & CRM** | **Klaviyo**, **HubSpot** | *Klaviyo > Lists & Segments > Export CSV* (consent status, timestamp, method, DOI flag, `Initial Campaign`) · *HubSpot > Contacts & Deals Export* (`Lifecycle Stage`, `Double opt-in status`, `Original Traffic Source Drill-Down 1`, `Deal Stage`, `Amount`) |
| **E-commerce** | **Shopify** | *Orders > Export* (multi-line-item folding, exclusion of cancelled/refunded/voided orders, `Discount Amount`, 1st & 2nd distinct-day purchase tracking) |
| **Data Warehouse & BI** | **BigQuery**, **Snowflake**, **Databricks**, **Power BI**, **Tableau**, **Looker** | Star-schema `fact_ads_crm_funnel.csv` + ready-to-deploy SQL models in [`sql/`](sql/) |

---

## Immediate Operational Outputs

1. **`campaign_budget_actions.csv`** — Per-campaign unit economics with explicit operational decision tags:
   - `SCALE_PROVEN_REPEAT` / `SCALE_PIPELINE`
   - `FIX_DOI_CONSENT_LEAK`
   - `FIX_POST_PURCHASE_RETENTION` / `FIX_LEAD_QUALITY_MQL_DROP`
   - `PAUSE_WASTE`
2. **`meta_high_ltv_seed_audience.csv`** — Repeat buyers (2+ orders) or Closed-Won customers with lowercase **SHA-256 hashed emails** ready to upload directly to **Meta Custom Audiences** for high-value Lookalike seeding.
3. **`meta_low_quality_exclusions.csv`** — Non-converting unconfirmed leads, hard bounces, opted-out contacts, and unconfirmed discount-only buyers (SHA-256 hashed) ready to upload as a **Meta Exclusion Audience** to cut retargeting waste.
4. **`crm_unconfirmed_paid_leads.csv`** — Paid leads lacking verified GDPR Double Opt-In proof in Klaviyo/HubSpot for immediate form/webhook audit.
5. **`fact_ads_crm_funnel.csv`** + **`reconciliation_report.html`** + **`sql/*.sql`** — BI-ready star-schema fact table and portable warehouse SQL for BigQuery, Snowflake, and Databricks.

---

## CLI Usage (Pure Python 3.11 Standard Library — Zero Install)

```bash
# B2C E-commerce mode (Meta Ads + Meta Leads + Klaviyo + Shopify + GA4)
python src/reconciler.py --mode b2c \
  --ads fixtures/meta_ads_manager_schema.csv \
  --leads fixtures/meta_lead_ads_schema.csv \
  --crm fixtures/klaviyo_crm_consent_schema.csv \
  --orders fixtures/shopify_orders_schema.csv \
  --ga4 fixtures/ga4_acquisition_schema.csv \
  --out build/b2c_reconcile

# B2B Pipeline mode (Paid Ads + HubSpot Contacts + HubSpot Deals)
python src/reconciler.py --mode b2b \
  --ads fixtures/meta_b2b_ads_schema.csv \
  --crm fixtures/hubspot_b2b_contacts_schema.csv \
  --deals fixtures/hubspot_b2b_deals_schema.csv \
  --out build/b2b_reconcile

# Run unit tests
python -m unittest discover -s tests -v
```

---

## Repository Structure

| Path | Purpose |
| --- | --- |
| `src/ads_crm_io.py` | Native CSV auto-parsers (Meta Ads, Meta Lead Ads UTF-16, GA4, Klaviyo, HubSpot Contacts/Deals, Shopify Orders) + SHA-256 hashing & formula neutralization |
| `src/reconciler.py` | B2C & B2B campaign reconciliation engine, budget action classifier, Meta audience & BI CSV generator |
| `src/web_app.py` & `docs/index.html` | Client-side Pyodide browser workbench (zero server upload) |
| `sql/` | Portable Data Warehouse SQL models for **BigQuery**, **Snowflake**, and **Databricks Delta** |
| `fixtures/` | Minimal platform schema test fixtures (`example.com` only — no public UCI dataset, no fake case studies) |
| `tests/` | Automated unit tests covering B2C, B2B, UTF-16 exports, ROAS inflation, SHA-256 hashing, and browser bridge |

> *Repository note:* Earlier versions of this repository contained an exploratory exercise on the public UCI Online Retail II dataset. That exercise was removed and replaced with this operational Ads-to-CRM reconciliation toolkit while keeping the repository URL intact.

## License

MIT. See [LICENSE](LICENSE).
