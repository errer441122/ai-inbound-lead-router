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
   - `first_touch_utm_source`, `first_touch_utm_medium`, `first_touch_utm_campaign`, `last_touch_utm_source`, `last_touch_utm_medium`, `last_touch_utm_campaign` (Single-line text)
2. **Import both workflows into n8n:** *Workflows → Import from File* → select `workflows/ai-inbound-lead-router.n8n.json` and `workflows/error-notifier.n8n.json`, then in the main workflow open **Settings → Error Workflow** and select the Error Notifier.
3. **Connect credentials inside n8n:** HubSpot Private App token (Contacts Read/Write), OpenAI/Gemini API key, and Slack Bot token (`#inbound-tier1-leads` and `#martech-alerts`).
4. **Turn on n8n's SSRF protection** on the machine that runs n8n (`N8N_SSRF_PROTECTION_ENABLED=true`, [n8n docs](https://docs.n8n.io/deploy/host-n8n/configure-n8n/security/enable-ssrf-protection)). The workflow opens the website in the sender's email domain. It refuses IP addresses and internal names by itself, but only n8n can refuse a public name that resolves or redirects to an internal address.
5. **Point your website/landing form webhook** (HubSpot Form, Typeform, Webflow, Tally) to the n8n Production Webhook URL, passing hidden UTM fields (`utm_source`, `utm_medium`, `utm_campaign`).

---

## 2. Daily & Weekly Operational Routine

| Cadence | Action | Goal |
| --- | --- | --- |
| **Real-time (automated)** | Monitor `#inbound-tier1-leads` & `#martech-alerts` | Sales responds to Tier 1 leads in minutes; Ops catches any API/webhook failure immediately |
| **Daily (5 min)** | Review HubSpot Active List `routing_status = needs_human_review` | Manually classify leads where a website blocked fetching, AI confidence fell below 80%, or the AI's tier and the request it quotes disagree |
| **Monthly (20 min)** | Sample 30 scored leads and compare AI tier vs. human judgment | Measure agreement rate, identify recurring prompt misclassifications, and tighten the ICP rubric in [`prompts/icp-scoring-prompt.md`](../prompts/icp-scoring-prompt.md) |

---

## 3. Failure & Incident Playbook

- **Website fetch fails or returns no readable text:** the parser checks the fetch result before accepting the model's tier. It sends the record to review if the fetch failed, the excerpt is empty, the tier is unknown, or the confidence score is missing, non-integer or outside 0–100. Read `ai_icp_reasoning` for the reason. A page with readable but misleading text still needs human judgment.
- **The AI is sure but the message asks for nothing:** Tier 1 reaches Sales only if the words that ask for work are in the message; a lower tier with a quoted request goes to review too. `ai_icp_reasoning` says which of the two happened. If your form has a "what do you need" field, use that field instead of the quote.
- **AI provider rate limit (429) or outage:** the AI node also has `continueOnFail = true`, so the run does not stop: the parser reads the score as 0 and the lead goes to `needs_human_review`. Check the review list for a sudden spike.
- **HubSpot or Slack returns an error:** these nodes do not continue on error, so the run fails and the standalone Error Notifier posts the failed node and the error to `#martech-alerts`. Ops replays the execution from n8n's execution history once the service recovers.
- **Returning contact submits the form:** `HubSpot: Search Existing Contact` runs first. If the contact has an owner, only the last-touch UTMs change and the owner is told in Slack; otherwise first touch is kept and the lead is scored again. See the [Field Ownership Matrix](field-ownership-matrix.md).
