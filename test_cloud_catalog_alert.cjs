const test = require('node:test');
const assert = require('node:assert/strict');
const { plan } = require('./cloud_catalog_alert.cjs');
const bad = { health: 'degraded', providers: { grok: { reason: 'changed_document', retained: 'grok-4.6' } } };
test('first failure creates actionable alert', () => {
  const result = plan(bad, true, null, 'https://example.test/run');
  assert.equal(result.action, 'create');
  assert.match(result.body, /grok-4.6/);
  assert.match(result.body, /changed_document/);
  assert.match(result.body, /Do not add paid API keys/);
});
test('repeat failure updates one open issue', () => assert.equal(plan(bad, true, { number: 1 }, 'run').action, 'update'));
test('successful recovery closes with evidence', () => assert.equal(plan({ health: 'ok' }, false, { number: 1 }, 'run').action, 'close'));
test('healthy run creates no notification spam', () => assert.equal(plan({ health: 'ok' }, false, null, 'run').action, 'none'));
test('workflow failure cannot be hidden by stale healthy status', () => assert.equal(plan({ health: 'ok' }, true, null, 'run').action, 'create'));
test('test alert is explicitly labeled', () => assert.match(plan(bad, true, null, 'run', true).body, /Alert-path test/));
