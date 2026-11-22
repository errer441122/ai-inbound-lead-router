import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';

const model = 'qwen3.5:4b';
const workflow = JSON.parse(readFileSync(new URL('../workflows/ai-inbound-lead-router.n8n.json', import.meta.url), 'utf8'));
const fixture = readFileSync(new URL('../data/real-companies-benchmark.csv', import.meta.url), 'utf8');
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

function fixedRoute(message, hasPage) {
  if (!hasPage || (message.match(/\b\w+\b/g)?.length ?? 0) <= 3) return review;
  const passive = /\b(explor\w*|research\w*|general|download\w*|read\w*|reviewing|newsletter|webinar|compar\w*|case study|checklist|slides)\b/i;
  const project = /\b(audit\w*|automat\w*|fix\w*|improv\w*|integrat\w*|migrat\w*|optimi[sz]\w*|reduc\w*|restructur\w*|standardi[sz]\w*|implement\w*|evaluat\w*|benchmark\w*|clean[- ]?up|prevention)\b/i;
  const marketing = /\b(crm|hubspot|klaviyo|email|retention|lifecycle|attribution|lead\w*|nurtur\w*|churn|geo|deliverability|utm)\b/i;
  return !passive.test(message) && project.test(message) && marketing.test(message) ? sales : nurture;
}

assert.equal(fixedRoute('Please help us migrate our CRM', true), sales);
assert.equal(fixedRoute('I want to download your guide to CRM automation', true), nurture);
assert.equal(fixedRoute('Interested in CRM automation next quarter', false), review);
assert.equal(fixedRoute('More info please', true), review);

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

const [header, ...lines] = fixture.trim().split(/\r?\n/);
const columns = header.split(',');
const cases = lines.map(line => {
  // shortcut: the published fixture is unquoted CSV; use a CSV reader if fields start containing commas or newlines.
  const values = line.split(',');
  assert.equal(values.length, columns.length, 'Unexpected number of fields in benchmark row');
  assert.ok(!line.includes('"'), 'Quoted CSV is unsupported by this fixture reader');
  const row = Object.fromEntries(columns.map((column, index) => [column, values[index]]));
  assert.match(row.domain, /^[a-z0-9-]+(?:\.[a-z0-9-]+)+$/);
  assert.ok([sales, nurture, selfServe, review].includes(row.expected_route));
  return row;
});
assert.equal(cases.length, 30);
assert.equal(new Set(cases.map(row => row.case_id)).size, 30);

const pages = await Promise.all(cases.map(({ domain, sample_test_input_type }) => {
  const context = node => ({ item: { json: node === normalize ? { domain } : {} } });
  return isPersonal({}, context) ? { status: 'skipped' } : fetchPage(domain, sample_test_input_type);
}));

const results = [];
for (const [index, row] of cases.entries()) {
  const page = pages[index];
  const lead = { domain: row.domain, message: row.sample_inbound_intent };
  const context = node => ({ item: { json: node === normalize ? lead : page } });
  const { messages, temperature } = JSON.parse(prompt(page, context));
  const { homepage_excerpt: excerpt } = JSON.parse(messages[1].content);
  const skipAI = page.status === 'skipped';
  const hasPage = !page.error && Boolean(excerpt.trim());
  const callAI = !skipAI && hasPage;
  const answer = parse(callAI ? await qualify(messages, temperature) : {}, context).json;
  const fixed = skipAI ? selfServe : fixedRoute(lead.message, hasPage);
  const ai = skipAI ? selfServe : answer.confidence_score < confidenceThreshold || !hasPage ? review
    : answer.icp_tier === 'Tier 1' ? sales : nurture;
  results.push({
    case_id: row.case_id,
    expected_route: row.expected_route,
    website_status: page.status,
    excerpt_sha256: hasPage ? createHash('sha256').update(excerpt).digest('hex') : '',
    rules_route: fixed,
    ai_route: ai,
    ai_called: callAI,
    ai_tier: callAI ? answer.icp_tier : '',
    ai_confidence: callAI ? answer.confidence_score : '',
  });
  console.error(`${row.case_id} ${page.status} ${fixed} ${ai}`);
}

function summarize(field) {
  return {
    wrongSales: results.filter(row => row[field] === sales && row.expected_route !== sales).length,
    missedSales: results.filter(row => row[field] !== sales && row.expected_route === sales).length,
    manualReview: results.filter(row => row[field] === review).length,
    exactMatches: results.filter(row => row[field] === row.expected_route).length,
  };
}

const resultColumns = Object.keys(results[0]);
console.log(resultColumns.join(','));
for (const row of results) console.log(resultColumns.map(column => row[column]).join(','));
console.error(JSON.stringify({ model, rules: summarize('rules_route'), ai: summarize('ai_route') }));
