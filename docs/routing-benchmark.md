# Lead routing benchmark on 30 synthetic enquiries

Run on 22 November 2026 against workflow revision `5e6093b`. The fixed rules matched 23 of 30 expected routes. The same workflow prompt with local Qwen3.5 4B matched 10 of 30.

| Metric | Fixed rules | Qwen3.5 4B |
| --- | ---: | ---: |
| Sent to Sales in error (of 15 cases expected elsewhere) | **0** | **2** |
| Expected at Sales without an automatic Sales route (of 15) | **5** | **10** |
| Left for human review (of 30) | **6** | **17** |

The missed automatic Sales routes include two reviews with fixed rules and seven with Qwen. The other three in each method went to nurture. A Sales enquiry held for review can still be recovered by the reviewer. [See all 30 decisions](../data/routing-benchmark-results.csv).

## What changed between the two methods

- Qwen recovered the pre-send QA enquiry in case `04`, which the keyword rule put in nurture.
- Qwen routed an exploratory framework enquiry (`17`) and a newsletter signup (`22`) to Sales with confidence scores of 98 and 95. The confidence threshold admitted both errors.
- Four live website requests failed and both methods sent those cases to review. Qwen ran on 22 cases, including the ambiguous enquiry fixture, and added 11 reviews beyond those opened by the fixed rules.

On this set the fixed rules are the stronger default for automatic routing. For a follow-up experiment, the [written customer rubric](../prompts/icp-scoring-prompt.md) is worth testing in the runtime prompt. The current node names the tiers and output fields. The written rubric adds criteria for deciding between the tiers.

## Method

- **Inputs.** Same 30 enquiries and pre-existing expected routes from the [benchmark matrix](../data/real-companies-benchmark.csv). The company sites are public and the enquiries are invented. Twenty-five cases use a live homepage request. Two use fixtures for a blocked homepage and an ambiguous enquiry. Three personal-email cases skip the site and the model.
- **Fixed rules.** Personal emails go to self-serve. Missing website context or an enquiry of at most three words goes to review. Passive signals, such as a download or a webinar request, go to nurture. Otherwise, the rule requires both a project-action keyword and a marketing keyword to send the enquiry to Sales. Remaining cases go to nurture. The full keyword lists are in the [runner](../tests/routing-benchmark.mjs).
- **AI.** Qwen3.5 4B (Ollama 0.34.3, model ID `2a654d98e6fb`) ran locally in JSON mode at temperature 0.1 with seed 42. The runner reused the blueprint's embedded prompt, 2,500-character homepage excerpt, output parser, and confidence threshold of 80. The parser sends unavailable website context to review, so the runner skips inference in those cases. The prompt receives the domain, excerpt and enquiry. The expected route is used for scoring after each decision.
- **Scope.** The runner executes the workflow expressions and parser in Node and checks branch destinations against the n8n blueprint. It records intended destinations before the CRM, outreach, or Slack steps. The results apply to this model and run. Labels reflect a fictitious consultancy's sales criteria and the fixed rules were designed after inspecting the exercise. An independently labelled set would give a better estimate of how the comparison transfers.

## Reproduce

With Node.js and Ollama serving a locally installed `qwen3.5:4b` model, run from the repository root.

```sh
node tests/routing-benchmark.mjs > benchmark-rerun.csv
```

The runner writes per-case progress and totals to stderr and the CSV to stdout. Live homepage text and model outputs can vary. The CSV records the HTTP outcome and a hash of the website excerpt used on each eligible case.
