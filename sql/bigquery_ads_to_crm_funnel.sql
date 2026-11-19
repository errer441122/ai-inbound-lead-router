-- BigQuery Standard SQL: Ads-to-CRM Funnel, GDPR Double Opt-In & 2nd-Order Repeat Economics
-- Target BI layer: Looker Studio / Looker / Power BI / Tableau
-- Inputs:
--   `martech.meta_ads_spend`        (campaign_name, ad_spend, platform_leads, platform_reported_revenue)
--   `martech.crm_contacts_consent`  (email, initial_campaign, consent_state, consent_source, consent_timestamp)
--   `martech.shopify_orders`        (order_id, email, order_date, total_net, discount_amount, financial_status, cancelled_at)

CREATE OR REPLACE TABLE `martech.fact_ads_crm_unit_economics` AS
WITH valid_orders AS (
  SELECT
    LOWER(TRIM(email)) AS email,
    DATE(created_at) AS order_date,
    CAST(total AS NUMERIC) AS net_revenue,
    COALESCE(CAST(discount_amount AS NUMERIC), 0) AS discount_amount,
    DENSE_RANK() OVER (PARTITION BY LOWER(TRIM(email)) ORDER BY DATE(created_at)) AS visit_order_num
  FROM `martech.shopify_orders`
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
    COUNTIF(c.consent_state = 'verified_doi') AS verified_doi_leads,
    COUNTIF(o.total_orders >= 1) AS first_order_customers,
    COUNTIF(o.reached_second_order = 1) AS second_order_customers,
    COALESCE(SUM(o.total_net_revenue), 0) AS total_net_revenue,
    COALESCE(SUM(o.total_discount_burn), 0) AS total_discount_burn
  FROM `martech.crm_contacts_consent` c
  LEFT JOIN customer_orders o
    ON LOWER(TRIM(c.email)) = o.email
  WHERE c.initial_campaign IS NOT NULL
  GROUP BY 1
)
SELECT
  a.campaign_name,
  a.ad_spend,
  a.platform_leads,
  SAFE_DIVIDE(a.ad_spend, a.platform_leads) AS platform_cpl,
  COALESCE(c.crm_matched_leads, 0) AS crm_matched_leads,
  COALESCE(c.verified_doi_leads, 0) AS verified_doi_leads,
  ROUND(100 * SAFE_DIVIDE(c.verified_doi_leads, c.crm_matched_leads), 1) AS doi_rate_pct,
  SAFE_DIVIDE(a.ad_spend, c.verified_doi_leads) AS true_cpvl_doi,
  COALESCE(c.first_order_customers, 0) AS first_order_customers,
  SAFE_DIVIDE(a.ad_spend, c.first_order_customers) AS true_cac_1st_order,
  COALESCE(c.second_order_customers, 0) AS second_order_customers,
  ROUND(100 * SAFE_DIVIDE(c.second_order_customers, c.first_order_customers), 1) AS repeat_rate_pct,
  SAFE_DIVIDE(a.ad_spend, c.second_order_customers) AS true_repeat_cac_2nd_order,
  COALESCE(c.total_net_revenue, 0) AS total_net_revenue,
  COALESCE(c.total_discount_burn, 0) AS total_discount_burn,
  SAFE_DIVIDE(c.total_net_revenue, a.ad_spend) AS true_crm_mer,
  CASE
    WHEN COALESCE(c.crm_matched_leads, 0) > 0 AND SAFE_DIVIDE(c.verified_doi_leads, c.crm_matched_leads) < 0.50 THEN 'FIX_DOI_CONSENT_LEAK'
    WHEN COALESCE(c.first_order_customers, 0) = 0 OR SAFE_DIVIDE(c.total_net_revenue, a.ad_spend) < 1.0 THEN 'PAUSE_WASTE'
    WHEN COALESCE(c.second_order_customers, 0) > 0 AND SAFE_DIVIDE(c.second_order_customers, c.first_order_customers) >= 0.25 AND SAFE_DIVIDE(c.total_net_revenue, a.ad_spend) >= 2.0 THEN 'SCALE_PROVEN_REPEAT'
    WHEN COALESCE(c.first_order_customers, 0) > 0 AND SAFE_DIVIDE(c.second_order_customers, c.first_order_customers) < 0.25 THEN 'FIX_POST_PURCHASE_RETENTION'
    ELSE 'MAINTAIN_OPTIMIZE'
  END AS budget_action
FROM `martech.meta_ads_spend` a
LEFT JOIN crm_attributed c
  ON LOWER(TRIM(a.campaign_name)) = c.campaign_key;

-- Meta Custom Audience Lookalike Seed (hashed SHA-256 repeat buyers)
CREATE OR REPLACE VIEW `martech.v_meta_high_ltv_seed` AS
SELECT
  TO_HEX(SHA256(LOWER(TRIM(email)))) AS email_sha256,
  COUNT(DISTINCT DATE(created_at)) AS purchase_days,
  SUM(CAST(total AS NUMERIC)) AS net_revenue
FROM `martech.shopify_orders`
WHERE cancelled_at IS NULL
  AND LOWER(COALESCE(financial_status, '')) NOT IN ('refunded', 'voided')
GROUP BY 1
HAVING COUNT(DISTINCT DATE(created_at)) >= 2;
