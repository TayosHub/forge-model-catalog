const test = require('node:test');
const assert = require('node:assert/strict');
const { plan, run, TITLE } = require('./cloud_catalog_alert.cjs');
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

function harness(existing = null, comments = []) {
  const calls = [];
  const issues = {};
  for (const method of ['listForRepo', 'listComments', 'create', 'update', 'createComment', 'addAssignees']) {
    issues[method] = async args => { calls.push([method, args]); return { data: { number: 7 } }; };
  }
  const github = {
    rest: { issues, repos: { get: async () => ({ data: { owner: { type: 'User', login: 'catalog-owner' } } }) } },
    paginate: async method => method === issues.listForRepo ? (existing ? [existing] : []) : comments
  };
  const summary = { addHeading() { return this; }, addRaw() { return this; }, async write() {} };
  const core = { info() {}, warning() {}, error: value => calls.push(['error', value]), summary };
  const context = { repo: { owner: 'catalog-owner', repo: 'catalog' }, serverUrl: 'https://github.com', runId: 123 };
  return { calls, github, core, context, report: bad, failed: true, attempt: '1' };
}

test('first failure explicitly mentions and assigns the owner', async () => {
  const h = harness();
  await run(h);
  const created = h.calls.find(([method]) => method === 'create')[1];
  assert.deepEqual(created.assignees, ['catalog-owner']);
  assert.match(created.body, /@catalog-owner/);
  assert.match(created.body, /runs\/123\/attempts\/1/);
  assert.equal(h.calls.filter(([method]) => method === 'createComment').length, 0);
});

test('repeat failure comments with a fresh mention instead of silently editing the issue', async () => {
  const h = harness({ number: 7, title: TITLE, body: 'Old failure', assignees: [{ login: 'catalog-owner' }] });
  await run(h);
  const comments = h.calls.filter(([method]) => method === 'createComment');
  assert.equal(comments.length, 1);
  assert.match(comments[0][1].body, /@catalog-owner/);
  assert.match(comments[0][1].body, /changed_document/);
  assert.ok(h.calls.findIndex(([method]) => method === 'createComment') < h.calls.findIndex(([method]) => method === 'update'));
  assert.ok(h.calls.some(([method]) => method === 'error'));
});

test('retry after a posted comment does not notify twice for the same run attempt', async () => {
  const existing = { number: 7, title: TITLE, body: 'Old failure', assignees: [{ login: 'catalog-owner' }] };
  const first = harness(existing);
  await run(first);
  const comment = first.calls.find(([method]) => method === 'createComment')[1];
  const retry = harness(existing, [comment]);
  await run(retry);
  assert.equal(retry.calls.filter(([method]) => method === 'createComment').length, 0);
  const nextAttempt = harness(existing, [comment]);
  nextAttempt.attempt = '2';
  await run(nextAttempt);
  assert.equal(nextAttempt.calls.filter(([method]) => method === 'createComment').length, 1);
});

test('same first-failure attempt does not add a duplicate notification', async () => {
  const first = harness();
  await run(first);
  const issue = first.calls.find(([method]) => method === 'create')[1];
  const retry = harness({ ...issue, number: 7, assignees: [{ login: 'catalog-owner' }] });
  await run(retry);
  assert.equal(retry.calls.filter(([method]) => method === 'createComment').length, 0);
});

test('existing unassigned alert gets an accountable owner', async () => {
  const h = harness({ number: 7, title: TITLE, body: 'Old failure', assignees: [] });
  await run(h);
  assert.deepEqual(h.calls.find(([method]) => method === 'addAssignees')[1].assignees, ['catalog-owner']);
});

test('healthy documentation cannot close an alert when publication failed', async () => {
  const h = harness({ number: 7, title: TITLE, body: 'Old failure', assignees: [{ login: 'catalog-owner' }] });
  h.report = { health: 'ok' };
  await run(h);
  assert.ok(!h.calls.some(([method, args]) => method === 'update' && args.state === 'closed'));
  assert.match(h.calls.find(([method]) => method === 'createComment')[1].body, /workflow/i);
});

test('healthy published recovery comments then closes the incident', async () => {
  const h = harness({ number: 7, title: TITLE });
  h.report = { health: 'ok' };
  h.failed = false;
  await run(h);
  assert.match(h.calls.find(([method]) => method === 'createComment')[1].body, /Recovered/);
  assert.ok(h.calls.some(([method, args]) => method === 'update' && args.state === 'closed'));
});
