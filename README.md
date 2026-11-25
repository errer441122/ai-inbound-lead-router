# AI Inbound Lead Enrichment, ICP Scoring & HubSpot Routing

A visual **n8n + HubSpot + LLM** workflow that turns raw inbound form submissions into clean, deduplicated, UTM-attributed, ICP-scored CRM records and instant Tier 1 Sales alerts, with explicit guardrails for contacts Sales already owns, free emails, low AI confidence, and workflow failures.

**[Explore the interactive workflow walkthrough](https://errer441122.github.io/ai-inbound-lead-router/)** · **[Download n8n blueprint (`workflows/ai-inbound-lead-router.n8n.json`)](workflows/ai-inbound-lead-router.n8n.json)** · **[Error Notifier (`workflows/error-notifier.n8n.json`)](workflows/error-notifier.n8n.json)**

[![The walkthrough page: seven example leads and the n8n workflow drawn from its own file](assets/page.png)](https://errer441122.github.io/ai-inbound-lead-router/)

> **What is real and what is a test:** the workflow is an importable n8n blueprint for HubSpot Free CRM (Private App), OpenAI (`gpt-4o-mini`) or Google Gemini (`gemini-2.5-flash`), and Slack (`#inbound-tier1-leads`, `#martech-alerts`). The 30 test cases pair real public company domains with **invented** inbound messages. They and 51 more invented messages were run through the workflow's own prompt, parser and gates with a small local model ([results](docs/routing-benchmark.md)). HubSpot, Slack and the two cloud models have not been run. The leads on the walkthrough page are examples. No private customer data is used.

---

**Tested in n8n 2.48.7.** In 23 synthetic scenarios the workflow produced all
23 expected destinations. Testing found three mistakes, all fixed: a failed site
lookup, a missing or unknown tier and a score outside 0–100 let four contacts
through; a very sure model could alert Sales about a message that asked for
nothing; text typed in the form reached Slack as it was. The runs used a manual trigger and test doubles for the website, the
model, HubSpot and Slack. [See the cases and observed routes](docs/routing-verification.md).

## The Business Problem

In most B2B and e-commerce growth teams, inbound forms dump unverified leads straight into the CRM:
- **Slow speed-to-lead:** high-fit prospects sit in the same generic inbox as personal `gmail.com` inquiries and students.
- **Dirty CRM & broken attribution:** repeat form fills overwrite original `First Touch UTM` values, or re-route a lead a rep is already working.
- **Unsafe AI automation:** naive LLM workflows hallucinate company facts or auto-send unreviewed emails when a company website is unreachable.

---

## System Architecture (Main Workflow + Standalone Error Workflow)

```mermaid
flowchart LR
    W["1. Inbound Form Webhook + UTMs"] --> N["2. Normalize Email & Domain"]
    N --> HS["3. HubSpot Search (alwaysOutputData=true)"]
    HS --> O{"4. Owned by Sales?"}
    O -- "Yes" --> LT["5. HubSpot: Refresh Last Touch Only"] --> SO["6. Slack: Tell the Owner"]
    O -- "No" --> G1{"7. Corporate Email?"}
    G1 -- "No (gmail / libero / etc.)" --> FS["8. HubSpot Self-Serve Nurture (Zero AI cost)"]
    G1 -- "Yes" --> H["9. Fetch Public Website Context (continueOnFail)"]
    H --> AI["10. AI Structured ICP Scoring (JSON, temp 0.1)"]
    AI --> P["11. Parse AI Output (Safe Defaults, Quoted Request)"]
    P --> G2{"12. Confidence >= 80%?"}
    G2 -- "No / Blocked Site / Tier and Request Disagree" --> MR["13. HubSpot Flag: needs_human_review"]
    G2 -- "Yes" --> SW{"14. Route by ICP Tier"}
    SW -- "Tier 1" --> T1["15. HubSpot Upsert (Preserve all 3 First-Touch UTMs)"] --> SL["16. Slack Instant Sales Alert"]
    SW -- "Tier 2 / 3" --> T2["17. HubSpot Segmented Nurture"]
```

*Global safety net:* link [`workflows/error-notifier.n8n.json`](workflows/error-notifier.n8n.json) under **Settings → Error Workflow** in n8n so a failed HubSpot or Slack call (for example a 429) posts immediately to `#martech-alerts`.

---

## Key Operational Guardrails

| Risk | How This Workflow Handles It | Documentation |
| --- | --- | --- |
| **Re-routing a lead Sales is already working** | `Guard: Owned by Sales?` reads `hubspot_owner_id` before any write. If the contact has an owner, the workflow only refreshes the last-touch UTMs and tells the owner in Slack: no AI call, `icp_tier` and `routing_status` untouched | [`docs/field-ownership-matrix.md`](docs/field-ownership-matrix.md) |
| **Overwriting First-Touch UTMs** | `first_touch_utm_*` is **fill-if-blank only** on every write node, `last_touch_utm_*` always refreshes, `lifecyclestage` and the owner are never written | [`docs/field-ownership-matrix.md`](docs/field-ownership-matrix.md) |
| **Wasted AI credits on personal emails** | Pre-AI `IF` gate sends `gmail.com`, `yahoo.com`, `libero.it`, `outlook.com`, `icloud.com` and similar straight to self-serve nurture | [`workflows/ai-inbound-lead-router.n8n.json`](workflows/ai-inbound-lead-router.n8n.json) |
| **AI hallucinations or blocked websites** | Strict JSON output contract (`temperature = 0.1`), `continueOnFail = true` on the website fetch and the AI call, and a hard **`confidence_score >= 80` gate** routing uncertain cases to `needs_human_review` | [`prompts/icp-scoring-prompt.md`](prompts/icp-scoring-prompt.md) |
| **A very sure AI** | The score alone decides nothing. The model must copy the words that ask for work (`request_quote`) and the Code node checks they are in the message. Tier 1 without a request, or a request with a lower tier, goes to `needs_human_review` | [`docs/routing-benchmark.md`](docs/routing-benchmark.md) |
| **Orders for the AI typed in the form** | Fixed rules, not the model: a message or a website that gives instructions goes to a person, mentions, links and formatting are removed before Slack, and the email domain must be a public name before the workflow opens it. Turn on n8n's SSRF protection too | [`docs/sop-inbound-lead-routing.md`](docs/sop-inbound-lead-routing.md) |
| **Unreviewed AI emails sent to prospects** | **Human-in-the-loop by design:** the AI opener is posted only inside Slack for a rep to verify before sending | [`docs/sop-inbound-lead-routing.md`](docs/sop-inbound-lead-routing.md) |

---

## 30 Test Cases (25 Real Company Domains + 5 Edge Cases)

Test matrix: [`data/real-companies-benchmark.csv`](data/real-companies-benchmark.csv)

- **25 real European D2C & B2B SaaS public domains** (*Velasca, Cortilia, Tannico, Gymshark, Huel, Factorial, Qonto, Brevo, Typeform, Holded, Pipedrive, Fatture in Cloud, Pennylane, Scalapay, Casavo, Satispay, Bending Spoons, Subito, Vinted, Too Good To Go, Klarna, N26, Revolut, Wise, Zalando*). The runs fetched their real homepages; the inbound messages are **invented** test inputs, not enquiries from these companies.
- **3 personal free-email cases** (`gmail.com`, `libero.it`, `outlook.com`) that should never reach the AI.
- **2 failure / low-confidence cases** that should land in `needs_human_review`.
- **Results** ([details](docs/routing-benchmark.md), one row per decision in `data/`), with a small local model: 0 of 30 sent to Sales by mistake (2 before the fix), no request lost in nurture (3 before), 21 of 30 read by a person. On 51 messages never seen before: no request lost out of 24, 1 ambiguous message sent to Sales, 39 read by a person. The webhook, CRM writes and Slack are not part of these runs.
- **Estimated API unit cost:** ~€0.001–€0.002 per corporate lead (~€1–€2 per 1,000 leads on `gpt-4o-mini` / `gemini-2.5-flash` list prices).

---

## Quick Import & Walkthrough

1. Open n8n (local via `npx n8n` or cloud) → **Workflows → Import from File** → import [`workflows/ai-inbound-lead-router.n8n.json`](workflows/ai-inbound-lead-router.n8n.json) and [`workflows/error-notifier.n8n.json`](workflows/error-notifier.n8n.json).
2. In the main workflow, open **Settings → Error Workflow** and select `Error Notifier — Inbound Lead Router`.
3. Connect a free **HubSpot** Private App (`crm.objects.contacts.read` & `.write`), an LLM API key (`gpt-4o-mini` or `gemini-2.5-flash`), and Slack following [`docs/sop-inbound-lead-routing.md`](docs/sop-inbound-lead-routing.md).
4. Send test POST payloads to the Webhook URL and inspect the Contact record in HubSpot + alert in Slack.

## Repository Structure

| Path | Content |
| --- | --- |
| `workflows/ai-inbound-lead-router.n8n.json` | Importable n8n workflow (owner gate, free-email filter, AI confidence gate, first-touch UTM lock) |
| `workflows/error-notifier.n8n.json` | Standalone 2-node Error Workflow routing execution failures to `#martech-alerts` |
| `prompts/icp-scoring-prompt.md` | ICP rubric, system prompt, JSON output contract & hallucination guardrails |
| `docs/field-ownership-matrix.md` | CRM overwrite & First-Touch / Last-Touch UTM governance rules |
| `docs/sop-inbound-lead-routing.md` | 10-minute setup & daily/monthly Operations SOP |
| `data/real-companies-benchmark.csv` | 30 test cases: real company domains, invented messages, expected routes |
| `data/routing-*.csv`, `data/unseen-2026-11-25.csv` | What the workflow decided, one row per case or message |
| `docs/routing-benchmark.md` | What the workflow decided on the 30 cases and on 51 messages it had never seen |
| `data/unseen-messages.csv` | 51 invented messages, English and Italian, half of them asking for nothing |
| `docs/routing-verification.md` | 23 scenarios run in n8n 2.48.7 |
| `docs/index.html` | Interactive visual workflow explorer (GitHub Pages) |

## License

MIT. See [LICENSE](LICENSE).
