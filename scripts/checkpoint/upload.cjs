// Persist BEFORE SMTP and after confirmed acceptance. Only runs in the scheduled workflow.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

async function upload(file, client, env = process.env) {
  if (!client) {
    const {DefaultArtifactClient} = await import('@actions/artifact');
    client = new DefaultArtifactClient();
  }
  const absolute = path.resolve(file);
  const state = JSON.parse(fs.readFileSync(absolute, 'utf8'));
  const prefix = `briefing-state-${state.edition_date}-`;
  const name = `${prefix}${env.GITHUB_RUN_ID}-${env.GITHUB_RUN_ATTEMPT}-${Date.now()}-${crypto.randomBytes(3).toString('hex')}`;
  const directory = path.dirname(absolute);
  const files = fs.readdirSync(directory).filter(name => name.startsWith(state.edition_date + '-') && name.endsWith('.json'))
    .map(name => path.join(directory, name));
  // Include other recipient manifests restored for the same day as well.
  if (!files.includes(absolute)) files.push(absolute);
  await client.uploadArtifact(name, files, directory, {retentionDays: 7});
  // Delete only older checkpoints in THIS run, after the replacement is durable.
  // This keeps even very large multipart digests below per-job artifact-count limits.
  const {artifacts} = await client.listArtifacts();
  for (const old of artifacts) {
    if (old.name.startsWith(prefix) && old.name !== name) {
      await client.deleteArtifact(old.name);
    }
  }
  return name;
}

if (require.main === module) {
  upload(process.argv[2]).catch(() => {
    console.error('Delivery checkpoint failed; SMTP must not continue without durable state.');
    process.exitCode = 1;
  });
}
module.exports = {upload};
