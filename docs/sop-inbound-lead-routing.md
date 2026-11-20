# Standard Operating Procedure (SOP): AI Inbound Lead Routing

**Owner:** Marketing Operations / RevOps  
**Tools:** n8n · HubSpot CRM (Free tier compatible) · OpenAI / Gemini API · Slack  
**Workflow file:** [`workflows/ai-inbound-lead-router.n8n.json`](../workflows/ai-inbound-lead-router.n8n.json)

---

## 1. Initial Setup (10 Minutes, No Custom Coding)

1. **Create custom contact properties in HubSpot** (*Settings → Properties → Contact*):
   - `icp_tier` (Dropdown: `Tier 1`, `Tier 2`, `Tier 3`, `Tier 3 - Free Email`)
   - `routing_status` (Dropdown: `sales_fast_track`, `marketing_nurture`, `self_serve_nurture`, `needs_human_review`)
   - `ai_confidence_score` (Number)
   - `ai_icp_reasoning` (Multi-line text)
   - `ai_personalized_hook` (Multi-line text)
   - `first_touch_utm_source`, `first_touch_utm_campaign`, `last_touch_utm_source`, `last_touch_utm_campaign` (Single-line text)
2. **Import the workflow into n8n:** *Workflows → Import from File* → select `workflows/ai-inbound-lead-router.n8n.json`.
3. **Connect credentials inside n8n:** HubSpot Private App token (Contacts Read/Write), OpenAI/Gemini API key, and Slack Bot token (`#inbound-tier1-leads` and `#martech-alerts`).
4. **Point your website/landing form webhook** (HubSpot Form, Typeform, Webflow, Tally) to the n8n Production Webhook URL, passing hidden UTM fields (`utm_source`, `utm_medium`, `utm_campaign`).

---

## 2. Daily & Weekly Operational Routine

| Cadence | Action | Goal |
| --- | --- | --- |
| **Real-time (automated)** | Monitor `#inbound-tier1-leads` & `#martech-alerts` | Sales responds to Tier 1 leads in minutes; Ops catches any API/webhook failure immediately |
| **Daily (5 min)** | Review HubSpot Active List `routing_status = needs_human_review` | Manually classify leads where a website blocked fetching or AI confidence fell below 80% |
| **Monthly (20 min)** | Sample 30 scored leads and compare AI tier vs. human judgment | Measure agreement rate, identify recurring prompt misclassifications, and tighten the ICP rubric in [`prompts/icp-scoring-prompt.md`](../prompts/icp-scoring-prompt.md) |

---

## 3. Failure & Incident Playbook

- **Website returns 403 / times out:** `HTTP: Fetch Public Homepage Context` has `continueOnFail = true`. The prompt instructs the model to set `confidence_score <= 70`, which automatically routes the contact to `needs_human_review` — **zero lost leads**.
- **AI provider rate limit (429) or outage:** The global `Error Trigger` posts the failed node and error message directly to `#martech-alerts` so Ops can replay the execution from n8n's Execution History once the provider recovers.
- **Returning existing customer submits form:** Node 5 checks HubSpot first; `first_touch_utm_*` and Sales-owned fields are preserved per the [Field Ownership Matrix](field-ownership-matrix.md).
