const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {upload} = require('./upload.cjs');
const {restore, trusted} = require('../restore_state.cjs');

(async () => {
  const sdk = await import('@actions/artifact');
  assert.equal(typeof sdk.DefaultArtifactClient, 'function');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'briefing-checkpoint-'));
  const file = path.join(dir, 'state.json');
  fs.writeFileSync(file, JSON.stringify({edition_date: '2026-10-06'}));
  const order = [];
  const client = {
    uploadArtifact: async (name, files, root, options) => { order.push('upload'); assert.equal(files[0],file); assert.equal(root,dir); assert.equal(options.retentionDays,7); },
    listArtifacts: async () => ({artifacts: [{name:'briefing-state-2026-10-06-old'}, {name:'unrelated-artifact'}]}),
    deleteArtifact: async name => { order.push('delete'); assert.equal(name,'briefing-state-2026-10-06-old'); }
  };
  await upload(file,client,{GITHUB_RUN_ID:'1',GITHUB_RUN_ATTEMPT:'1'});
  assert.deepEqual(order,['upload','delete']);
  assert(trusted({head_branch:'main',workflow_id:5,event:'schedule'},'main',5));
  assert(!trusted({head_branch:'main',workflow_id:5,event:'pull_request'},'main',5));
  assert(!trusted({head_branch:'untrusted',workflow_id:5,event:'workflow_dispatch'},'main',5));
  const envFile = path.join(dir,'environment');
  process.env.GITHUB_ENV = envFile;
  process.env.ACTIONS_RUNTIME_TOKEN = 'fixture-runtime-token';
  process.env.ACTIONS_RUNTIME_URL = 'https://example.com/runtime';
  process.env.ACTIONS_RESULTS_URL = 'https://example.com/results';
  const today = new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Jakarta',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  const outputs = {};
  const github = {rest:{repos:{get:async()=>({data:{default_branch:'main'}})},actions:{
    getWorkflow:async()=>({data:{id:5}}),
    listArtifactsForRepo:async()=>({data:{artifacts:[
      {id:9,name:`briefing-state-${today}-untrusted`,created_at:'2026-10-06T09:00:00Z',expired:false,workflow_run:{id:99}},
      {id:8,name:`briefing-state-${today}-trusted`,created_at:'2026-10-06T08:00:00Z',expired:false,workflow_run:{id:98}}
    ]}}),
    getWorkflowRun:async({run_id})=>({data:{head_branch:'main',workflow_id:5,event:run_id===99?'pull_request':'schedule'}})
  }}};
  const core = {setOutput:(name,value)=>{outputs[name]=value;},info:()=>{},setSecret:()=>{}};
  await restore({github,context:{repo:{owner:'fixture',repo:'repo'},ref:'refs/heads/main'},core});
  assert.deepEqual(outputs,{artifact_id:'8',run_id:'98'});
  assert(fs.readFileSync(envFile,'utf8').includes('ACTIONS_RUNTIME_TOKEN='));
  fs.rmSync(dir,{recursive:true});
  console.log('Checkpoint upload order and trusted restore checks passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
