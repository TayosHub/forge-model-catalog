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
      (failed ? 'The workflow failed. Check the run for documentation, test, or publication errors.\n\n' : '') +
      details + '\n\nNext action: inspect the source/format or documented request-profile change in the run below. Update the parser or app adapter if needed, then rerun. Do not add paid API keys.\n\n' +
      'Last successful check: ' + (report.lastSuccessfulCheckAt || 'not yet recorded') + '\n\nRun: ' + runURL };
}

function readReport() {
  let report = {};
  try { report = JSON.parse(fs.readFileSync('status.json', 'utf8')); } catch { }
  return report;
}

async function run({ github, context, core, report = readReport(),
  failed = process.env.CHECK_OUTCOME !== 'success',
  attempt = process.env.GITHUB_RUN_ATTEMPT || '1' }) {
  const issues = await github.paginate(github.rest.issues.listForRepo, { ...context.repo, state: 'open', per_page: 100 });
  const existing = issues.find(issue => !issue.pull_request && issue.title === TITLE);
  const url = context.serverUrl + '/' + context.repo.owner + '/' + context.repo.repo + '/actions/runs/' + context.runId + '/attempts/' + attempt;
  const change = plan(report, failed, existing, url, process.env.TEST_ALERT === 'true');
  let assignees = [];
  if (change.action === 'create' || change.action === 'update') {
    const repo = await github.rest.repos.get(context.repo);
    assignees = repo.data.owner.type === 'User' ? [repo.data.owner.login] : (existing?.assignees || []).map(a => a.login);
    if (!assignees.length) core.warning('Catalog alert has no recipient. Assign a maintainer to the alert issue.');
    const marker = '<!-- forge-catalog-alert:' + context.runId + ':' + attempt + ' -->';
    change.body = assignees.map(login => '@' + login).join(' ') + '\n\n' + change.body + '\n\n' + marker;
    core.error('Model catalog needs attention: ' + url);
    await core.summary.addHeading(TITLE).addRaw(change.body).write();
    if (existing) {
      // A body edit alone is not a fresh alert. Comment once per attempt, before
      // updating the summary so an API failure cannot hide an undelivered comment.
      const comments = await github.paginate(github.rest.issues.listComments, { ...context.repo, issue_number: existing.number, per_page: 100 });
      const delivered = (existing.body || '').includes(marker) || comments.some(comment => (comment.body || '').includes(marker));
      if (!delivered) await github.rest.issues.createComment({ ...context.repo, issue_number: existing.number, body: change.body });
      const missing = assignees.filter(login => !(existing.assignees || []).some(a => a.login === login));
      if (missing.length) await github.rest.issues.addAssignees({ ...context.repo, issue_number: existing.number, assignees: missing });
    }
  }
  if (change.action === 'create') {
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
