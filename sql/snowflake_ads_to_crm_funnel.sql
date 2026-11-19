-- Snowflake SQL: Ads-to-CRM Funnel, GDPR Double Opt-In & 2nd-Order Repeat Economics
-- Ready for Power BI / Tableau / Looker DirectQuery or reverse ETL (Hightouch / Census)

CREATE OR REPLACE TABLE MARTECH.FACT_ADS_CRM_UNIT_ECONOMICS AS
WITH valid_orders AS (
  SELECT
    LOWER(TRIM(email)) AS email,
    TO_DATE(created_at) AS order_date,
    TRY_TO_DECIMAL(total, 12, 2) AS net_revenue,
    COALESCE(TRY_TO_DECIMAL(discount_amount, 12, 2), 0) AS discount_amount,
    DENSE_RANK() OVER (PARTITION BY LOWER(TRIM(email)) ORDER BY TO_DATE(created_at)) AS visit_order_num
  FROM MARTECH.SHOPIFY_ORDERS
  WHERE cancelled_at IS NULL
    AND LOWER(COALESCE(financial_status, '')) NOT IN ('refunded', 'voided')
),
customer_orders AS (
  SELECT
    email,
    COUNT(*) AS total_orders,
    MAX(IFF(visit_order_num >= 2, 1, 0)) AS reached_second_order,
    SUM(net_revenue) AS total_net_revenue,
    SUM(discount_amount) AS total_discount_burn
  FROM valid_orders
  GROUP BY email
),
crm_attributed AS (
  SELECT
    LOWER(TRIM(c.initial_campaign)) AS campaign_key,
    COUNT(DISTINCT LOWER(TRIM(c.email))) AS crm_matched_leads,
    COUNT_IF(c.consent_state = 'verified_doi') AS verified_doi_leads,
    COUNT_IF(o.total_orders >= 1) AS first_order_customers,
    COUNT_IF(o.reached_second_order = 1) AS second_order_customers,
    COALESCE(SUM(o.total_net_revenue), 0) AS total_net_revenue,
    COALESCE(SUM(o.total_discount_burn), 0) AS total_discount_burn
  FROM MARTECH.CRM_CONTACTS_CONSENT c
  LEFT JOIN customer_orders o ON LOWER(TRIM(c.email)) = o.email
  WHERE c.initial_campaign IS NOT NULL
  GROUP BY 1
)
SELECT
  a.campaign_name,
  a.ad_spend,
  a.platform_leads,
  DIV0(a.ad_spend, a.platform_leads) AS platform_cpl,
  COALESCE(c.crm_matched_leads, 0) AS crm_matched_leads,
  COALESCE(c.verified_doi_leads, 0) AS verified_doi_leads,
  ROUND(100 * DIV0(c.verified_doi_leads, c.crm_matched_leads), 1) AS doi_rate_pct,
  DIV0(a.ad_spend, c.verified_doi_leads) AS true_cpvl_doi,
  COALESCE(c.first_order_customers, 0) AS first_order_customers,
  DIV0(a.ad_spend, c.first_order_customers) AS true_cac_1st_order,
  COALESCE(c.second_order_customers, 0) AS second_order_customers,
  ROUND(100 * DIV0(c.second_order_customers, c.first_order_customers), 1) AS repeat_rate_pct,
  DIV0(a.ad_spend, c.second_order_customers) AS true_repeat_cac_2nd_order,
  COALESCE(c.total_net_revenue, 0) AS total_net_revenue,
  DIV0(c.total_net_revenue, a.ad_spend) AS true_crm_mer,
  CASE
    WHEN COALESCE(c.crm_matched_leads, 0) > 0 AND DIV0(c.verified_doi_leads, c.crm_matched_leads) < 0.50 THEN 'FIX_DOI_CONSENT_LEAK'
    WHEN COALESCE(c.first_order_customers, 0) = 0 OR DIV0(c.total_net_revenue, a.ad_spend) < 1.0 THEN 'PAUSE_WASTE'
    WHEN COALESCE(c.second_order_customers, 0) > 0 AND DIV0(c.second_order_customers, c.first_order_customers) >= 0.25 AND DIV0(c.total_net_revenue, a.ad_spend) >= 2.0 THEN 'SCALE_PROVEN_REPEAT'
    WHEN COALESCE(c.first_order_customers, 0) > 0 AND DIV0(c.second_order_customers, c.first_order_customers) < 0.25 THEN 'FIX_POST_PURCHASE_RETENTION'
    ELSE 'MAINTAIN_OPTIMIZE'
  END AS budget_action
FROM MARTECH.META_ADS_SPEND a
LEFT JOIN crm_attributed c ON LOWER(TRIM(a.campaign_name)) = c.campaign_key;

-- Hashed Meta Custom Audience Seed View
CREATE OR REPLACE VIEW MARTECH.V_META_HIGH_LTV_SEED AS
SELECT
  SHA2(LOWER(TRIM(email)), 256) AS email_sha256,
  COUNT(DISTINCT TO_DATE(created_at)) AS purchase_days,
  SUM(TRY_TO_DECIMAL(total, 12, 2)) AS net_revenue
FROM MARTECH.SHOPIFY_ORDERS
WHERE cancelled_at IS NULL
  AND LOWER(COALESCE(financial_status, '')) NOT IN ('refunded', 'voided')
GROUP BY 1
HAVING COUNT(DISTINCT TO_DATE(created_at)) >= 2;
