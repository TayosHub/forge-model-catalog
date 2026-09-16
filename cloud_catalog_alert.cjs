const fs = require('node:fs');

const TITLE = 'Forge model catalog needs attention';

function plan(report, failed, existing, runURL, synthetic = false) {
  if (!failed && report.health === 'ok') {
    return existing ? { action: 'close', body: 'Recovered. The keyless documentation check succeeded. No paid API tests were run.\n\n' + runURL } : { action: 'none' };
  }
  const details = Object.entries(report.providers || {}).map(([provider, row]) =>
    '- ' + provider + ': ' + (row.reason || row.state || 'check unavailable') +
    (row.retained ? '. Retaining ' + row.retained : '')).join('\n');
  return { action: existing ? 'update' : 'create', title: TITLE,
    body: (synthetic ? '**Alert-path test. No catalog change was attempted.**\n\n' : '') +
      'The automatic model update could not be verified. The previous catalog remains published; this does not by itself mean the coach is broken.\n\n' +
      details + '\n\nNext action: inspect the source/format or documented request-profile change in the run below. Update the parser or app adapter if needed, then rerun. Do not add paid API keys.\n\n' +
      'Last successful check: ' + (report.lastSuccessfulCheckAt || 'not yet recorded') + '\n\nRun: ' + runURL };
}

async function run({ github, context, core }) {
  let report = {};
  try { report = JSON.parse(fs.readFileSync('status.json', 'utf8')); } catch { }
  const issues = await github.paginate(github.rest.issues.listForRepo, { ...context.repo, state: 'open', per_page: 100 });
  const existing = issues.find(issue => !issue.pull_request && issue.title === TITLE);
  const url = context.serverUrl + '/' + context.repo.owner + '/' + context.repo.repo + '/actions/runs/' + context.runId;
  const change = plan(report, process.env.CHECK_OUTCOME !== 'success', existing, url, process.env.TEST_ALERT === 'true');
  if (change.action === 'create') {
    const repo = await github.rest.repos.get(context.repo);
    const assignees = repo.data.owner.type === 'User' ? [repo.data.owner.login] : [];
    await github.rest.issues.create({ ...context.repo, title: change.title, body: change.body, assignees });
  } else if (change.action === 'update') {
    await github.rest.issues.update({ ...context.repo, issue_number: existing.number, body: change.body });
  } else if (change.action === 'close') {
    await github.rest.issues.createComment({ ...context.repo, issue_number: existing.number, body: change.body });
    await github.rest.issues.update({ ...context.repo, issue_number: existing.number, state: 'closed', state_reason: 'completed' });
  }
  core.info('Catalog alert: ' + change.action);
}

module.exports = { plan, run, TITLE };
