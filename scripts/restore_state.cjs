// Executed by actions/github-script; restore only same-day production workflow state.
const fs = require('node:fs');

function trusted(run, branch, workflowId) {
  return run.head_branch === branch && run.workflow_id === workflowId &&
    ['schedule', 'workflow_dispatch'].includes(run.event);
}

async function restore({github, context, core}) {
  const repository = await github.rest.repos.get(context.repo);
  const branch = repository.data.default_branch;
  if (context.ref !== `refs/heads/${branch}`) throw new Error('Production delivery requires the default branch');
  const workflow = await github.rest.actions.getWorkflow({...context.repo, workflow_id: 'daily_briefing.yml'});
  const dateParts = new Intl.DateTimeFormat('en-CA', {
    timeZone: process.env.TIMEZONE || 'Asia/Jakarta', year: 'numeric', month: '2-digit', day: '2-digit'
  }).formatToParts(new Date());
  const value = type => dateParts.find(part => part.type === type).value;
  const edition = `${value('year')}-${value('month')}-${value('day')}`;
  const prefix = `briefing-state-${edition}-`;
  let artifact;
  for (let page = 1; page <= 10 && !artifact; page++) {
    const response = await github.rest.actions.listArtifactsForRepo({...context.repo, per_page: 100, page});
    const candidates = response.data.artifacts.filter(a => a.name.startsWith(prefix) && !a.expired)
      .sort((a,b) => new Date(b.created_at) - new Date(a.created_at) || b.id - a.id);
    for (const candidate of candidates) {
      const run = await github.rest.actions.getWorkflowRun({...context.repo, run_id: candidate.workflow_run.id});
      if (trusted(run.data, branch, workflow.data.id)) { artifact = candidate; break; }
    }
    if (response.data.artifacts.length < 100) break;
    if (page === 10 && !artifact) throw new Error('Artifact scan incomplete; refusing delivery without restored state');
  }
  if (artifact) {
    core.setOutput('artifact_id', String(artifact.id));
    core.setOutput('run_id', String(artifact.workflow_run.id));
    core.info('Restoring durable edition checkpoint.');
  } else {
    core.info('No checkpoint for this edition; preparing a new frozen digest.');
  }
  // Runtime credentials are masked and supplied only to the artifact SDK; never put them in outputs.
  for (const name of ['ACTIONS_RUNTIME_TOKEN', 'ACTIONS_RUNTIME_URL', 'ACTIONS_RESULTS_URL']) {
    const value = process.env[name];
    if (!value) throw new Error(`Artifact runtime missing ${name}`);
    core.setSecret(value);
    fs.appendFileSync(process.env.GITHUB_ENV, `${name}=${value}\n`);
  }
}

module.exports = {restore, trusted};
