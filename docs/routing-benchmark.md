# What the workflow decided, measured

> Invented messages read by a small local model (`qwen3.5:4b`). HubSpot, Slack, `gpt-4o-mini` and `gemini-2.5-flash` were not run.

## In short

1. **22 November, the problem.** On 30 test cases the model alone got 10 routes right. It would have alerted Sales about two messages that asked for nothing (a general question and a newsletter sign-up), 98 and 95 sure. Three real requests ended in nurture, where nobody reads them.
2. **Fixed word lists looked better: 23 of 30.** They had been written after reading those 30 messages. On 51 messages they had never seen, they found 3 requests out of 24 and left 21 in nurture.
3. **25 November, the fix.** The model must copy the words that ask for work (`request_quote`). The Code node checks that they are in the message. If tier and request disagree, a person decides.

| 51 unseen messages | Word lists | Score only | **Workflow now** |
| --- | ---: | ---: | ---: |
| 24 requests: alert to Sales | 3 | 11 | **11** |
| 24 requests: read by a person | 0 | 3 | **13** |
| 24 requests: **lost in nurture** | 21 | 10 | **0** |
| 27 other messages: alert to Sales by mistake | 1 | 1 | **1** |
| 27 other messages: read by a person | 0 | 24 | **26** |
| 27 other messages: nurture | 26 | 2 | **0** |

*Score only* is the same answer of the model, judged as the workflow did before the fix. One row per message: [`unseen-2026-11-25.csv`](../data/unseen-2026-11-25.csv).

| 30 test cases | 22 Nov, before | 25 Nov, score only | **25 Nov, workflow now** |
| --- | ---: | ---: | ---: |
| 15 requests: alert to Sales | 5 | 5 | **5** |
| 15 requests: **lost in nurture** | 3 | 3 | **0** |
| 15 other cases: alert to Sales by mistake | 2 | 0 | **0** |
| All 30: read by a person | 17 | 18 | **21** |

Asking for the exact words already changed the answers: the two sure mistakes of 22 November came back as Tier 3. One row per case: [22 November](../data/routing-2026-11-22.csv), [25 November](../data/routing-2026-11-25.csv).

## What it costs

A person reads 39 of the 51 messages and 21 of the 30 cases. With this model the workflow is safe and saves little time, because the model is rarely more than 80 sure about messages that ask for nothing. The next test is the same files with the two cloud models the workflow is built for.

## Where it stops

- **A quote proves that the words are in the message, not that they are a request.** The model quoted 4 of the 27 other messages. Three went to a person because their tier was not Tier 1.
- **The fourth reached Sales:** message 45, "I am looking for a senior freelancer to manage B2B campaigns on LinkedIn" (in Italian). It is one of the five marked `ambiguous`: a person could call it a request.
- **Orders for the AI.** Eight messages that tried to give orders to the model (English, Italian, JSON, one hidden in the website) all went to a person: six by a fixed rule, two because the model scored them 45. The rule stops plain orders. A convincing fake request still reaches Sales, as it would in any inbox.
- **Two requests out of 24 were not quoted** (35 and 36). Both went to a person because the score was 65.
- **The messages are invented.** The 51 were written by the same model, asked for messages that do and do not ask for work, in English and Italian, without seeing the word lists. The labels come from that request; real forms are messier.
- **One run.** Homepages and answers change. Four live homepages failed (08, 10, 20, 23) and those cases went to a person.
- **If your form has a "what do you need" field,** use it instead of the quote.

## Method

- **Inputs.** The [30 cases](../data/real-companies-benchmark.csv) have their expected route and real homepages, fetched live; two use fixtures for a blocked and an empty site, three personal emails skip site and model. The [51 messages](../data/unseen-messages.csv) use one made-up homepage.
- **Workflow.** The runner reads the prompt, the parser, the threshold and the routes from the [workflow file](../workflows/ai-inbound-lead-router.n8n.json) and stops before HubSpot and Slack. The expected route is used only after each decision.
- **Model.** `qwen3.5:4b` on Ollama, JSON mode, temperature 0.1, seed 42, on a computer without a graphics card (about 20 seconds per message).
- **Word lists.** Written on 22 November after reading the 30 cases, kept in the [runner](../tests/routing-benchmark.mjs) only as a comparison.

## Reproduce

```sh
node tests/routing-benchmark.mjs > rerun-30.csv
node tests/routing-benchmark.mjs unseen > rerun-unseen.csv
node tests/qualification-parser.mjs
```

The first two need Ollama with `qwen3.5:4b`. The third needs only Node and checks the fixed rules: the quote is in the message (at least three words), a score alone never decides, orders for the AI go to a person.

The rules on orders, links and domains were added after these runs. Applied to the same 73 answers of the model, they change none of the decisions.
