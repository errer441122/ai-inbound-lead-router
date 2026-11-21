import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const file = new URL('../workflows/ai-inbound-lead-router.n8n.json', import.meta.url);
const workflow = JSON.parse(readFileSync(file, 'utf8'));
const parser = workflow.nodes.find(node => node.name.startsWith('Parse AI ICP Output'));
const execute = new Function('$json', '$', parser.parameters.jsCode);
const source = { data: '<p>Public product information</p>' };
const answer = { icp_tier: 'Tier 1', confidence_score: 90 };

function inspect(page, result) {
  const response = { choices: [{ message: { content: JSON.stringify(result) } }] };
  return execute(response, () => ({ item: { json: page } })).json;
}

assert.equal(inspect(source, answer).confidence_score, 90);
for (const [page, result] of [
  [{ error: 'timeout' }, answer],
  [{ data: '<p> </p>' }, answer],
  [source, { confidence_score: 95 }],
  [source, { ...answer, icp_tier: 'Tier X' }],
  [source, { ...answer, confidence_score: 150 }],
  [source, { ...answer, confidence_score: '95' }],
  [source, { ...answer, confidence_score: -1 }],
  [source, null],
]) {
  const actual = inspect(page, result);
  assert.equal(actual.confidence_score, 0);
  assert.ok(actual.reasoning);
  assert.equal(actual.personalized_hook, '');
}
console.log('Qualification parser regression checks passed.');
