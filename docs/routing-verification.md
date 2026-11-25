# Routing decisions tested in n8n

## 22 November 2026: the parser

Two isolated runs exercised the decision graph in n8n 2.48.7. The first used the workflow at `349830f`. The second changed the parser to require website text, a recognised tier and an integer confidence score from 0 to 100.

| Synthetic input | Original route | Corrected route |
| --- | --- | --- |
| New business contact, Tier 1, score 95 | Sales | Sales |
| Second submission, no owner, Tier 2 | Nurture | Nurture |
| Returning contact with a Sales owner | Keep owner | Keep owner |
| Personal email address | Self-serve | Self-serve |
| Tier 1, score 79 | Review | Review |
| Tier 2, score 80 | Nurture | Nurture |
| Unreadable model output | Review | Review |
| Website fetch failed, model still returns Tier 1 and 95 | Sales | **Review** |
| No tier, score 95 | Nurture | **Review** |
| Unknown tier, score 95 | Nurture | **Review** |
| Tier 1, score 150 | Sales | **Review** |
| Provider error | Review | Review |

## 25 November 2026: the score alone decides nothing

The [benchmark](routing-benchmark.md) found a model that was 95 and 98 sure about two messages that asked for nothing. The model must now copy the words that ask for work (`request_quote`), and the parser checks that they are in the message. A third run repeated the 12 inputs above with the new key, and all 12 reached the corrected route. These five were added:

| Synthetic input | Observed route |
| --- | --- |
| Tier 1, score 98, message asks for nothing, empty quote | Review |
| Tier 1, score 98, quote that is not in the message | Review |
| Tier 1, score 98, `request_quote` missing | Review |
| Tier 2, score 90, but the message asks for work | Review |
| Message telling the model to answer Tier 1 and 100, empty quote | Review |

In the first input (Tier 1, score 95, request quoted) the Slack message carried the quoted words, so the rep reads the request before the opener.

## How the runs were set up

**Run setup.** A temporary Docker container with networking disabled executed copies of the graph. A manual trigger supplied one synthetic form submission per scenario. Set nodes supplied the website, model and CRM search responses, evaluated the original CRM field expressions, and captured the Slack message. The original normalisation, owner check, corporate-email check, parser, confidence check and tier switch ran in n8n.

The second submission preserved all three first-touch values and updated the latest campaign. For an owned contact, only the email key and three last-touch fields reached the simulated write. The model was skipped and the returning-lead notification branch ran. The free-email branch skipped both the website and the model.

**Scope.** The result verifies the routing and the values prepared at integration boundaries. Live API permissions, message delivery, production CRM state and scoring accuracy require separate checks. The repository's 30-row company-domain benchmark is a different dataset. A valid-looking score may still reflect poor commercial judgment.

Run the parser regression checks locally with `node tests/qualification-parser.mjs`. These checks read the JavaScript from the production workflow JSON.
