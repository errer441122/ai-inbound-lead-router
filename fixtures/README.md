# Schema Test Fixtures

Minimal platform schema fixtures (`example.com` addresses only) used to test the native CSV parsers, B2C & B2B reconciliation logic, SHA-256 Meta audience generation, and browser UI in CI. They are **not** real ad accounts or performance case studies.

| Fixture | Platform Export Schema Tested |
| --- | --- |
| `meta_ads_manager_schema.csv` / `meta_b2b_ads_schema.csv` | Meta Ads Manager → *Export table data (.csv)* |
| `meta_lead_ads_schema.csv` | Meta Lead Center / Instant Forms → *Download Leads (.csv)* |
| `klaviyo_crm_consent_schema.csv` | Klaviyo → *Lists & Segments > Export CSV* |
| `shopify_orders_schema.csv` | Shopify Admin → *Orders > Export* |
| `ga4_acquisition_schema.csv` | GA4 → *Traffic acquisition > Export CSV* (with `#` header lines) |
| `hubspot_b2b_contacts_schema.csv` | HubSpot → *CRM > Contacts > Export* |
| `hubspot_b2b_deals_schema.csv` | HubSpot → *CRM > Deals > Export* |
