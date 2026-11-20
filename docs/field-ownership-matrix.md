# HubSpot Field Ownership & Conflict Prevention Matrix

One of the fastest ways an automation breaks a CRM is **blindly overwriting human Sales notes, deal stages, or original attribution data** when an existing contact fills out a second form.

Every HubSpot write node in [`workflows/ai-inbound-lead-router.n8n.json`](../workflows/ai-inbound-lead-router.n8n.json) enforces this Field Ownership Matrix:

| HubSpot Property | System of Record (Owner) | Overwrite Policy | Business Rationale |
| --- | --- | --- | --- |
| `email` | Contact / Form | **Primary key (Upsert match)** | Prevents duplicate contact records across repeat form submits |
| `first_touch_utm_source` / `first_touch_utm_campaign` | Marketing Ops (Automation) | **Fill if blank ONLY** | Preserves true original acquisition channel forever — a returning lead clicking a newsletter link must never erase the paid campaign that first acquired them |
| `last_touch_utm_source` / `last_touch_utm_campaign` | Marketing Ops (Automation) | **Always overwrite** | Captures the most recent campaign that drove high-intent conversion |
| `icp_tier` | AI Qualification Node | **Fill if blank, or update if `needs_human_review`** | Prevents an automation from downgrading a contact already manually qualified by Sales |
| `ai_icp_reasoning` & `ai_personalized_hook` | AI Qualification Node | **Always refresh on new inbound message** | Keeps the latest inbound context visible to Sales without touching core CRM status |
| `ai_confidence_score` | AI Qualification Node | **Always refresh** | Gives Ops visibility into prompt reliability and auditability |
| `routing_status` | Marketing Ops (Automation) | **Set only if Sales has not claimed lead** | Stops automation from re-routing an active opportunity |
| `lifecyclestage` (SQL / Opportunity / Customer) | **Sales Team** | **NEVER overwrite backwards** | If an existing Customer or SQL fills out a form, automation must never reset them to `Lead` or `MQL` |
| `hubspot_owner_id` (Account Executive) | **Sales / RevOps** | **NEVER overwrite if populated** | Existing accounts always stay with their assigned rep |

---

## Duplicate & Re-Submission Rule

Before writing to HubSpot, Node 5 (`HubSpot: Search Existing Contact`) inspects the existing record:
- **New contact:** writes both `first_touch_utm_*` and `last_touch_utm_*`, scores ICP, and routes.
- **Returning contact:** preserves `first_touch_utm_*`, updates `last_touch_utm_*` and `ai_personalized_hook`, and notifies the existing owner rather than creating a duplicate contact or re-assigning ownership.
