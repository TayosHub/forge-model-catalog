const fs = require('node:fs');

function receipt({ previous = {}, fresh, catalog, outcome, synthetic = false, now = new Date().toISOString() }) {
  // fresh is a separate artifact created by this invocation, never the checked-in
  // status. In particular, a skipped check must not reuse last week's failure.
  const complete = fresh && typeof fresh === 'object' && !Array.isArray(fresh) &&
    typeof fresh.checkedAt === 'string' && Number.isFinite(Date.parse(fresh.checkedAt)) &&
    fresh.validation === 'official_documentation_only' && fresh.liveAPITested === false &&
    ['openAI', 'claude', 'grok'].every(provider => fresh.providers?.[provider]?.state);
  if (!synthetic && complete &&
    ((outcome === 'success' && fresh.health === 'ok') || (outcome === 'failure' && fresh.health === 'degraded'))) return fresh;
  return {
    checkedAt: now, health: 'degraded',
    lastSuccessfulCheckAt: previous.lastSuccessfulCheckAt || null,
    validation: 'official_documentation_only', liveAPITested: false,
    providers: Object.fromEntries(['openAI', 'claude', 'grok'].map(provider => [provider, {
      state: 'held', retained: catalog[provider].primary,
      reason: synthetic ? 'synthetic_alert_test' : 'workflow_failed_before_fresh_status'
    }]))
  };
}

function readJSON(path) {
  try { return JSON.parse(fs.readFileSync(path, 'utf8')); } catch { return undefined; }
}

if (require.main === module) {
  const result = receipt({
    previous: readJSON('status.json') || {}, fresh: readJSON('check-status.json'),
    catalog: JSON.parse(fs.readFileSync('cloud_model_policy.json', 'utf8')),
    outcome: process.env.CHECK_OUTCOME, synthetic: process.env.TEST_ALERT === 'true'
  });
  fs.writeFileSync('status.json', JSON.stringify(result, null, 2) + '\n');
  // A nominally successful command with a missing or malformed receipt must not
  // publish a candidate or close the incident.
  if (process.env.CHECK_OUTCOME === 'success' && result.health !== 'ok') process.exitCode = 1;
}

module.exports = { receipt };
