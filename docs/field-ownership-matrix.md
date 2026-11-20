# HubSpot Field Ownership & Conflict Prevention Matrix

One of the fastest ways an automation breaks a CRM is **blindly overwriting human Sales notes, deal stages, or original attribution data** when an existing contact fills out a second form.

The HubSpot write nodes in [`workflows/ai-inbound-lead-router.n8n.json`](../workflows/ai-inbound-lead-router.n8n.json) follow this matrix. One gate decides most of it: **`Guard: Owned by Sales?`** checks whether the contact already has an owner (`hubspot_owner_id`). If it has one, Sales owns the contact and the workflow only refreshes the last-touch UTMs.

| HubSpot Property | System of Record (Owner) | Overwrite Policy | Business Rationale |
| --- | --- | --- | --- |
| `email` | Contact / Form | **Primary key (Upsert match)** | Prevents duplicate contact records across repeat form submits |
| `first_touch_utm_source` / `_medium` / `_campaign` | Marketing Ops (Automation) | **Fill if blank ONLY** (every write node keeps the value HubSpot already has) | Preserves the original acquisition channel: a returning lead clicking a newsletter link must never erase the paid campaign that first acquired them |
| `last_touch_utm_source` / `_medium` / `_campaign` | Marketing Ops (Automation) | **Always overwrite**, owned contacts included | Captures the most recent campaign that brought the lead back |
| `icp_tier` | AI Qualification Node | **Written only while the contact has no owner** | Once Sales owns a contact, automation never re-scores or downgrades it |
| `routing_status` | Marketing Ops (Automation) | **Written only while the contact has no owner** | Stops automation from re-routing a lead Sales is already working |
| `ai_icp_reasoning` & `ai_personalized_hook` | AI Qualification Node | **Refreshed each time the workflow scores the lead** (contacts without an owner) | Keeps the latest inbound context visible to Sales |
| `ai_confidence_score` | AI Qualification Node | **Refreshed each time the workflow scores the lead** | Gives Ops visibility into prompt reliability |
| `lifecyclestage` (SQL / Opportunity / Customer) | **Sales Team** | **Never written by this workflow** | An existing Customer or SQL who fills out a form is never reset to `Lead` or `MQL` |
| `hubspot_owner_id` (Account Executive) | **Sales / RevOps** | **Never written by this workflow**; only read by the owner gate | Existing accounts always stay with their assigned rep |

---

## Duplicate & Re-Submission Rule

Before any write, `HubSpot: Search Existing Contact` reads the record, then `Guard: Owned by Sales?` checks the owner:
- **New contact:** writes first and last touch, scores the ICP and routes.
- **Returning contact, no owner yet:** keeps `first_touch_utm_*`, refreshes `last_touch_utm_*`, scores and routes again.
- **Returning contact with an owner:** only `last_touch_utm_*` changes. No AI call; `icp_tier` and `routing_status` stay as Sales left them. `Slack: Tell the Owner (Returning Lead)` posts the new message and the owner ID in `#inbound-tier1-leads`.

If your team marks ownership another way (for example a lifecycle stage without an owner), change the condition in `Guard: Owned by Sales?`.
