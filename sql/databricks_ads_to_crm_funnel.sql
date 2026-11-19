-- Databricks SQL (Delta Lake): Ads-to-CRM Revenue, GDPR DOI & Repeat-Purchase Reconciliation
-- Suitable for Databricks SQL Warehouses + Power BI / Tableau / Looker semantic layers

CREATE OR REPLACE TABLE martech.fact_ads_crm_unit_economics
USING DELTA
AS
WITH valid_orders AS (
  SELECT
    LOWER(TRIM(email)) AS email,
    TO_DATE(created_at) AS order_date,
    CAST(total AS DECIMAL(12, 2)) AS net_revenue,
    COALESCE(CAST(discount_amount AS DECIMAL(12, 2)), 0) AS discount_amount,
    DENSE_RANK() OVER (PARTITION BY LOWER(TRIM(email)) ORDER BY TO_DATE(created_at)) AS visit_order_num
  FROM martech.shopify_orders
  WHERE cancelled_at IS NULL
    AND LOWER(COALESCE(financial_status, '')) NOT IN ('refunded', 'voided')
),
customer_orders AS (
  SELECT
    email,
    COUNT(*) AS total_orders,
    MAX(CASE WHEN visit_order_num >= 2 THEN 1 ELSE 0 END) AS reached_second_order,
    SUM(net_revenue) AS total_net_revenue,
    SUM(discount_amount) AS total_discount_burn
  FROM valid_orders
  GROUP BY email
),
crm_attributed AS (
  SELECT
    LOWER(TRIM(c.initial_campaign)) AS campaign_key,
    COUNT(DISTINCT LOWER(TRIM(c.email))) AS crm_matched_leads,
    SUM(CASE WHEN c.consent_state = 'verified_doi' THEN 1 ELSE 0 END) AS verified_doi_leads,
    SUM(CASE WHEN o.total_orders >= 1 THEN 1 ELSE 0 END) AS first_order_customers,
    SUM(CASE WHEN o.reached_second_order = 1 THEN 1 ELSE 0 END) AS second_order_customers,
    COALESCE(SUM(o.total_net_revenue), 0) AS total_net_revenue,
    COALESCE(SUM(o.total_discount_burn), 0) AS total_discount_burn
  FROM martech.crm_contacts_consent c
  LEFT JOIN customer_orders o ON LOWER(TRIM(c.email)) = o.email
  WHERE c.initial_campaign IS NOT NULL
  GROUP BY 1
)
SELECT
  a.campaign_name,
  a.ad_spend,
  a.platform_leads,
  TRY_DIVIDE(a.ad_spend, a.platform_leads) AS platform_cpl,
  COALESCE(c.crm_matched_leads, 0) AS crm_matched_leads,
  COALESCE(c.verified_doi_leads, 0) AS verified_doi_leads,
  ROUND(100 * TRY_DIVIDE(c.verified_doi_leads, c.crm_matched_leads), 1) AS doi_rate_pct,
  TRY_DIVIDE(a.ad_spend, c.verified_doi_leads) AS true_cpvl_doi,
  COALESCE(c.first_order_customers, 0) AS first_order_customers,
  TRY_DIVIDE(a.ad_spend, c.first_order_customers) AS true_cac_1st_order,
  COALESCE(c.second_order_customers, 0) AS second_order_customers,
  ROUND(100 * TRY_DIVIDE(c.second_order_customers, c.first_order_customers), 1) AS repeat_rate_pct,
  TRY_DIVIDE(a.ad_spend, c.second_order_customers) AS true_repeat_cac_2nd_order,
  COALESCE(c.total_net_revenue, 0) AS total_net_revenue,
  TRY_DIVIDE(c.total_net_revenue, a.ad_spend) AS true_crm_mer,
  CASE
    WHEN COALESCE(c.crm_matched_leads, 0) > 0 AND TRY_DIVIDE(c.verified_doi_leads, c.crm_matched_leads) < 0.50 THEN 'FIX_DOI_CONSENT_LEAK'
    WHEN COALESCE(c.first_order_customers, 0) = 0 OR TRY_DIVIDE(c.total_net_revenue, a.ad_spend) < 1.0 THEN 'PAUSE_WASTE'
    WHEN COALESCE(c.second_order_customers, 0) > 0 AND TRY_DIVIDE(c.second_order_customers, c.first_order_customers) >= 0.25 AND TRY_DIVIDE(c.total_net_revenue, a.ad_spend) >= 2.0 THEN 'SCALE_PROVEN_REPEAT'
    WHEN COALESCE(c.first_order_customers, 0) > 0 AND TRY_DIVIDE(c.second_order_customers, c.first_order_customers) < 0.25 THEN 'FIX_POST_PURCHASE_RETENTION'
    ELSE 'MAINTAIN_OPTIMIZE'
  END AS budget_action
FROM martech.meta_ads_spend a
LEFT JOIN crm_attributed c ON LOWER(TRIM(a.campaign_name)) = c.campaign_key;

-- Hashed Meta Custom Audience Seed View
CREATE OR REPLACE VIEW martech.v_meta_high_ltv_seed AS
SELECT
  SHA2(LOWER(TRIM(email)), 256) AS email_sha256,
  COUNT(DISTINCT TO_DATE(created_at)) AS purchase_days,
  SUM(CAST(total AS DECIMAL(12, 2))) AS net_revenue
FROM martech.shopify_orders
WHERE cancelled_at IS NULL
  AND LOWER(COALESCE(financial_status, '')) NOT IN ('refunded', 'voided')
GROUP BY 1
HAVING COUNT(DISTINCT TO_DATE(created_at)) >= 2;
