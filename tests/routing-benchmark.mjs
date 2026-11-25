import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';

// node tests/routing-benchmark.mjs           the 30 cases, with their real homepages
// node tests/routing-benchmark.mjs unseen    the messages in data/unseen-messages.csv, with one made-up homepage
const model = 'qwen3.5:4b';
const workflow = JSON.parse(readFileSync(new URL('../workflows/ai-inbound-lead-router.n8n.json', import.meta.url), 'utf8'));
const nodes = new Map(workflow.nodes.map(node => [node.name, node.parameters]));
const website = 'HTTP: Fetch Public Homepage Context';
const normalize = 'Normalize Lead & Extract Domain';
const prompt = expression(nodes.get('AI: Structured ICP Qualification (JSON)').jsonBody);
const parse = new Function('$json', '$', nodes.get('Parse AI ICP Output (Safe Defaults)').jsCode);
const [personalCheck] = nodes.get('Guard: Corporate Email Check').conditions.conditions;
const isPersonal = expression(personalCheck.leftValue);
const confidenceThreshold = nodes.get('Guard: AI Confidence >= 80%').conditions.conditions[0].rightValue;
const websiteTimeout = nodes.get(website).options.timeout;
const maxRedirects = nodes.get(website).options.redirect.redirect.maxRedirects;
const sales = 'sales_fast_track';
const nurture = 'marketing_nurture';
const selfServe = 'self_serve_nurture';
const review = 'needs_human_review';

function expression(source) {
  assert.match(source, /^=\{\{.*\}\}$/s);
  return new Function('$json', '$', `return (${source.slice(3, -2)});`);
}

function routeAt(node, branch) {
  const [{ node: destination }] = workflow.connections[node].main[branch];
  return nodes.get(destination).additionalFields.customPropertiesUi.customPropertiesValues
    .find(field => field.property === 'routing_status').value;
}

const tierSwitch = 'Switch: Route by ICP Tier';
assert.deepEqual([0, 1, 2].map(branch => routeAt(tierSwitch, branch)), [sales, nurture, nurture]);
assert.equal(routeAt('Guard: Corporate Email Check', 1), selfServe);
assert.equal(routeAt('Guard: AI Confidence >= 80%', 1), review);

// Word lists written on 22 November after reading the 30 cases. Kept as a comparison: see docs/routing-benchmark.md.
function wordRoute(message, hasPage) {
  if (!hasPage || (message.match(/\b\w+\b/g)?.length ?? 0) <= 3) return review;
  const passive = /\b(explor\w*|research\w*|general|download\w*|read\w*|reviewing|newsletter|webinar|compar\w*|case study|checklist|slides)\b/i;
  const project = /\b(audit\w*|automat\w*|fix\w*|improv\w*|integrat\w*|migrat\w*|optimi[sz]\w*|reduc\w*|restructur\w*|standardi[sz]\w*|implement\w*|evaluat\w*|benchmark\w*|clean[- ]?up|prevention)\b/i;
  const marketing = /\b(crm|hubspot|klaviyo|email|retention|lifecycle|attribution|lead\w*|nurtur\w*|churn|geo|deliverability|utm)\b/i;
  return !passive.test(message) && project.test(message) && marketing.test(message) ? sales : nurture;
}

assert.equal(wordRoute('Please help us migrate our CRM', true), sales);
assert.equal(wordRoute('I want to download your guide to CRM automation', true), nurture);
assert.equal(wordRoute('Interested in CRM automation next quarter', false), review);
assert.equal(wordRoute('More info please', true), review);

async function fetchPage(domain, inputType) {
  if (inputType === 'http_fetch_blocked') return { status: 'fixture:403', error: 'Simulated HTTP 403' };
  if (inputType === 'low_confidence_input') {
    return { status: 'fixture:200', data: '<title>Stealth Co</title><p>Coming soon.</p>' };
  }
  let url = new URL(`https://${domain}/`);
  const signal = AbortSignal.timeout(websiteTimeout);
  try {
    for (let redirect = 0; redirect <= maxRedirects; redirect++) {
      const response = await fetch(url, { redirect: 'manual', signal });
      const location = response.headers.get('location');
      if (response.status >= 300 && response.status < 400 && location) {
        await response.body?.cancel();
        url = new URL(location, url);
        continue;
      }
      if (response.ok) return { status: String(response.status), data: await response.text() };
      await response.body?.cancel();
      return { status: String(response.status), error: `HTTP ${response.status}` };
    }
    return { status: 'redirect-limit', error: 'Redirect limit exceeded' };
  } catch (error) {
    return { status: signal.aborted ? 'timeout' : 'fetch-error', error: error.name };
  }
}

async function qualify(messages, temperature) {
  const response = await fetch('http://127.0.0.1:11434/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model, messages, format: 'json', stream: false, think: false,
      options: { temperature, seed: 42, num_ctx: 4096, num_predict: 384 },
    }),
    signal: AbortSignal.timeout(120_000),
  });
  assert.ok(response.ok, `Ollama returned HTTP ${response.status}`);
  const body = await response.json();
  assert.equal(body.model, model);
  assert.equal(typeof body.message?.content, 'string');
  return { choices: [{ message: { content: body.message.content } }] };
}

function readCsv(path) {
  const rows = [[]];
  let cell = '', quoted = false;
  const text = readFileSync(new URL(path, import.meta.url), 'utf8').trim() + '\n';
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (quoted && char === '"' && text[i + 1] === '"') { cell += '"'; i++; }
    else if (char === '"') quoted = !quoted;
    else if (!quoted && (char === ',' || char === '\n')) {
      rows.at(-1).push(cell.replace(/\r$/, '')); cell = '';
      if (char === '\n') rows.push([]);
    } else cell += char;
  }
  const [header, ...body] = rows.filter(row => row.length);
  return body.map(row => {
    assert.equal(row.length, header.length, 'Unexpected number of fields');
    return Object.fromEntries(header.map((name, index) => [name, row[index]]));
  });
}

// One lead through the workflow's own prompt, parser and gates.
async function decide(lead, page) {
  const context = node => ({ item: { json: node === normalize ? lead : page } });
  const { messages, temperature } = JSON.parse(prompt(page, context));
  const { homepage_excerpt: excerpt } = JSON.parse(messages[1].content);
  const hasPage = !page.error && Boolean(excerpt.trim());
  const skipAI = page.status === 'skipped';
  const response = !skipAI && hasPage ? await qualify(messages, temperature) : {};
  const answer = parse(response, context).json;
  let model = {};
  try { model = JSON.parse(response.choices[0].message.content) ?? {}; } catch {}
  const gate = (tier, score) => !Number.isInteger(score) || score < confidenceThreshold || score > 100 || !/^Tier [123]$/.test(tier) ? review
    : tier === 'Tier 1' ? sales : nurture;
  return {
    website_status: page.status,
    excerpt_sha256: hasPage && !skipAI ? createHash('sha256').update(excerpt).digest('hex') : '',
    word_rules_route: skipAI ? selfServe : wordRoute(lead.message, hasPage),
    score_only_route: skipAI ? selfServe : gate(model.icp_tier, model.confidence_score),
    workflow_route: skipAI ? selfServe : gate(answer.icp_tier, answer.confidence_score),
    ai_called: !skipAI && hasPage,
    ai_tier: model.icp_tier ?? '',
    ai_confidence: model.confidence_score ?? '',
    request_quote: model.request_quote ?? '',
  };
}

const results = [];
if (process.argv[2] === 'unseen') {
  const page = { status: 'fixture:200', data: '<title>Acme</title><p>Acme sells subscription software and products to companies and consumers in Europe.</p>' };
  for (const row of readCsv('../data/unseen-messages.csv')) {
    const { website_status, excerpt_sha256, ai_called, ...decision } = await decide({ domain: 'acme.example', message: row.message }, page);
    results.push({ id: row.id, language: row.language, asks_for_work: row.asks_for_work, ...decision });
    console.error(`${row.id} ${row.asks_for_work} ${decision.word_rules_route} ${decision.workflow_route}`);
  }
  for (const field of ['word_rules_route', 'score_only_route', 'workflow_route']) {
    const count = (asks, route) => results.filter(row => row.asks_for_work === asks && row[field] === route).length;
    console.error(field, JSON.stringify(Object.fromEntries(['yes', 'no'].map(asks => [asks, { sales: count(asks, sales), review: count(asks, review), nurture: count(asks, nurture) }]))));
  }
} else {
  const cases = readCsv('../data/real-companies-benchmark.csv');
  assert.equal(new Set(cases.map(row => row.case_id)).size, 30);
  for (const row of cases) {
    assert.match(row.domain, /^[a-z0-9-]+(?:\.[a-z0-9-]+)+$/);
    assert.ok([sales, nurture, selfServe, review].includes(row.expected_route));
  }
  const pages = await Promise.all(cases.map(({ domain, sample_test_input_type }) => {
    const context = node => ({ item: { json: node === normalize ? { domain } : {} } });
    return isPersonal({}, context) ? { status: 'skipped' } : fetchPage(domain, sample_test_input_type);
  }));
  for (const [index, row] of cases.entries()) {
    const decision = await decide({ domain: row.domain, message: row.sample_inbound_intent }, pages[index]);
    results.push({ case_id: row.case_id, expected_route: row.expected_route, ...decision });
    console.error(`${row.case_id} ${decision.website_status} ${decision.word_rules_route} ${decision.workflow_route}`);
  }
  for (const field of ['word_rules_route', 'score_only_route', 'workflow_route']) {
    console.error(field, JSON.stringify({
      wrongSales: results.filter(row => row[field] === sales && row.expected_route !== sales).length,
      salesNotAlerted: results.filter(row => row[field] !== sales && row.expected_route === sales).length,
      salesLostInNurture: results.filter(row => row[field] === nurture && row.expected_route === sales).length,
      manualReview: results.filter(row => row[field] === review).length,
      exactMatches: results.filter(row => row[field] === row.expected_route).length,
    }));
  }
}

const csv = value => /[",\n]/.test(String(value)) ? `"${String(value).replaceAll('"', '""')}"` : value;
console.log(Object.keys(results[0]).join(','));
for (const row of results) console.log(Object.values(row).map(csv).join(','));
