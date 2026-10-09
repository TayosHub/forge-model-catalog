const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { receipt } = require('./cloud_catalog_receipt.cjs');
const catalog = JSON.parse(fs.readFileSync('cloud_model_policy.json', 'utf8'));
const previous = {
  checkedAt: '2026-10-05T14:59:53Z', lastSuccessfulCheckAt: '2026-09-21T13:02:06Z',
  health: 'degraded', validation: 'official_documentation_only', liveAPITested: false,
  providers: {
    openAI: { state: 'unchanged' },
    claude: { state: 'held', reason: 'unsupported_or_unproven_request_profile' },
    grok: { state: 'held_due_to_source_failure', firstSeen: '2026-09-28T13:00:00Z', recommended: 'grok-4.7' }
  }
};
const now = '2026-10-09T18:00:00Z';

test('a skipped check replaces a prior degraded report with this run failure', () => {
  const result = receipt({ previous, catalog, outcome: 'skipped', now });
  assert.equal(result.checkedAt, now);
  assert.equal(result.health, 'degraded');
  assert.equal(result.lastSuccessfulCheckAt, previous.lastSuccessfulCheckAt);
  for (const provider of ['openAI', 'claude', 'grok']) {
    assert.equal(result.providers[provider].reason, 'workflow_failed_before_fresh_status');
    assert.equal(result.providers[provider].retained, catalog[provider].primary);
  }
});

test('fresh provider failure preserves diagnostic evidence and observation history', () => {
  const fresh = { ...previous, checkedAt: now };
  assert.deepEqual(receipt({ previous, fresh, catalog, outcome: 'failure' }), fresh);
});

test('synthetic failure cannot masquerade as a real provider outage', () => {
  const result = receipt({ previous, fresh: previous, catalog, outcome: 'failure', synthetic: true, now });
  assert.equal(result.providers.claude.reason, 'synthetic_alert_test');
  assert.equal(result.checkedAt, now);
});

test('only a successful command with a complete healthy receipt can recover', () => {
  const fresh = { ...previous, checkedAt: now, health: 'ok' };
  assert.deepEqual(receipt({ previous, fresh, catalog, outcome: 'success' }), fresh);
  assert.equal(receipt({ previous, fresh, catalog, outcome: 'failure', now }).health, 'degraded');
  for (const invalid of [undefined, {}, { ...fresh, providers: {} }, { ...fresh, checkedAt: 'bad' }]) {
    assert.equal(receipt({ previous, fresh: invalid, catalog, outcome: 'success', now }).health, 'degraded');
  }
});

test('CLI refuses candidate publication after a missing or malformed fresh receipt', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'catalog-receipt-'));
  try {
    fs.writeFileSync(path.join(dir, 'cloud_model_policy.json'), JSON.stringify(catalog));
    fs.writeFileSync(path.join(dir, 'status.json'), JSON.stringify(previous));
    for (const contents of [null, '{invalid json', 'null', '{}']) {
      if (contents !== null) fs.writeFileSync(path.join(dir, 'check-status.json'), contents);
      const result = spawnSync(process.execPath, [path.resolve('cloud_catalog_receipt.cjs')], {
        cwd: dir, env: { ...process.env, CHECK_OUTCOME: 'success', TEST_ALERT: 'false' }
      });
      assert.equal(result.status, 1);
      const status = JSON.parse(fs.readFileSync(path.join(dir, 'status.json'), 'utf8'));
      assert.equal(status.health, 'degraded');
      assert.equal(status.providers.claude.reason, 'workflow_failed_before_fresh_status');
      assert.deepEqual(JSON.parse(fs.readFileSync(path.join(dir, 'cloud_model_policy.json'), 'utf8')), catalog);
    }
  } finally { fs.rmSync(dir, { recursive: true }); }
});
