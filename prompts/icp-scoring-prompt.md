# Structured AI ICP Qualification Prompt & Hallucination Guardrails

This prompt powers the node `AI: Structured ICP Qualification (JSON)` inside [`workflows/ai-inbound-lead-router.n8n.json`](../workflows/ai-inbound-lead-router.n8n.json). The workflow embeds a condensed version with the same rules and JSON keys.

---

## 1. Ideal Customer Profile (ICP) Business Rubric

Scenario: A European **MarTech & CRM Growth Consultancy** targeting digital-native D2C e-commerce brands and mid-market B2B SaaS teams with active marketing automation / lifecycle needs.

| Tier | Qualification Criteria | Operational Action |
| --- | --- | --- |
| **Tier 1 (High Fit)** | Digital-native D2C e-commerce or B2B SaaS in Europe with clear repeat-purchase / subscription / CRM lifecycle motion AND explicit intent in the inbound message (migration, retention, automation, attribution, paid-to-CRM) | Fast-track to HubSpot + instant Slack alert in `#inbound-tier1-leads` with 1-sentence factual hook |
| **Tier 2 (Medium Fit)** | Legitimate B2B/e-commerce company in target geography, but either early-stage, non-core vertical (e.g., consumer marketplace/fintech giant unlikely to hire a boutique consultancy), or vague inquiry ("just exploring") | Upsert to HubSpot (`MQL`) and enroll in segmented educational nurture |
| **Tier 3 (Low Fit / Disqualified)** | Personal free email (`gmail.com`, `libero.it`), student/job-seeker inquiry, unrelated offline local service, or spam | Route to self-serve resources; keep Sales inbox completely noise-free |

---

## 2. System Prompt (Low Temperature = `0.1`, JSON Mode Enforced)

```text
You are a Marketing Operations ICP qualification assistant.
Classify the inbound lead strictly using the provided corporate domain, public
homepage excerpt, and inbound form message.

Rules (non-negotiable):
1. Never invent employee counts, revenue figures, or tech stacks not present in the input.
2. If the homepage excerpt is empty, blocked, or ambiguous, set confidence_score below 75
   and add "insufficient_website_context" to risk_flags.
3. The personalized_hook must reference ONE verifiable product or positioning fact
   visible in the homepage excerpt or inbound message — never generic flattery.
4. request_quote must be the exact words of the inbound message that ask for work for the
   sender's company (a project, a quote, a demo, help with a specific problem), copied without
   changes. Use an empty string if they ask for none: newsletter, download, reading, general
   information, student, job, another agency selling, invoice, thanks, complaint.
5. Output strictly valid JSON matching the schema below and nothing else.

JSON Schema:
{
  "icp_tier": "Tier 1" | "Tier 2" | "Tier 3",
  "confidence_score": integer (0 to 100),
  "business_model": "D2C E-commerce" | "B2B SaaS" | "Marketplace" | "Fintech" | "Agency" | "Other",
  "industry": string,
  "reasoning": string (max 25 words explaining why this tier was assigned),
  "personalized_hook": string (1 factual opener sentence for a human rep to review),
  "risk_flags": string[],
  "request_quote": string (exact words of the message, or "")
}
```

---

## 3. Five Built-In Guardrails Against AI Errors

1. **Free-email pre-filter (before the AI runs):** Personal email domains (`gmail.com`, `yahoo.com`, `libero.it`, etc.) never reach the HTTP fetch or LLM node — saving API cost and preventing noisy false positives.
2. **Confidence gate (`confidence_score >= 80`):** Any score below 80 — or any failed/timed-out website fetch (`continueOnFail: true`) — branches automatically to `HubSpot: Flag Needs Manual Review` instead of routing a shaky guess to Sales.
3. **The score alone decides nothing:** the Code node checks that `request_quote` is in the message word for word (at least three words). Tier 1 without a request, or a request with a lower tier, goes to a person. [Why: a local model gave 95 and 98 to two messages that asked for nothing](../docs/routing-benchmark.md).
4. **Human-in-the-loop outreach:** The `personalized_hook` is posted into Slack as a *"Suggested opener (review before sending)"* — **the workflow never sends an automated AI-written email directly to a prospect.**
5. **Unit cost discipline:** Using a compact model (`gpt-4o-mini` / `gemini-2.5-flash`) on ~2,500 characters of homepage text keeps qualification cost at **~€0.001–€0.002 per corporate lead (~€1–€2 per 1,000 leads)**.
