#!/usr/bin/env node
/**
 * Proves the validator is not just printing "ok".
 *
 * A validator that has never failed is indistinguishable from a validator that
 * cannot fail. This takes the real WF-C1 export, breaks it in many different
 * ways in a scratch directory, and asserts that each break is caught with the
 * message it should produce.
 *
 *   node tools/validate-selftest.mjs
 */
import { readFileSync, mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { join, dirname } from 'node:path';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const load = f => JSON.parse(readFileSync(join(ROOT, 'workflows', f), 'utf8'));
const base = load('WF-C1.json');
// Most cases break WF-C1. The paired-Config cases need a workflow that HAS a
// pair, so a case may name its own source file as a fourth element.
const clone = (file) => JSON.parse(JSON.stringify(file ? load(file) : base));

const CASES = [
  ['active: true is caught', w => { w.active = true; }, 'must be exactly false'],
  ['a top-level id is caught', w => { w.id = 'Ju1nxQJw6R4mygdt'; }, 'top-level "id"'],
  ['a dangling connection target is caught', w => {
    w.connections['Config'].main[0][0].node = 'A Node That Does Not Exist';
  }, 'does not exist'],
  ['a missing position is caught', w => { delete w.nodes[3].position; }, '"position" must be'],
  ['a missing parameters object is caught', w => { delete w.nodes[3].parameters; },
    '"parameters" must be an object'],
  ['a duplicate node name is caught', w => { w.nodes[4].name = w.nodes[3].name; },
    'duplicate node name'],
  ['a duplicate node id is caught', w => { w.nodes[4].id = w.nodes[3].id; }, 'duplicate node id'],
  ['a credential VALUE is caught', w => {
    const n = w.nodes.find(x => x.credentials);
    n.credentials[Object.keys(n.credentials)[0]].data = { user: 'dovy', password: 'hunter2' };
  }, 'only id and name are allowed'],
  ['a live Stripe key anywhere is caught', w => {
    // Assembled at runtime so the literal never sits in a committed file,
    // which GitHub push protection would flag regardless of context.
    w.nodes[2].parameters.note_for_test = 'sk_live_' + '51QxAbCdEfGhIjKlMnOpQrStU';
  }, 'a Stripe secret key'],
  ['a JWT anywhere is caught', w => {
    w.nodes[2].parameters.note_for_test =
      'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijk';
  }, 'a JWT'],
  ['the forbidden project ref is caught', w => {
    w.nodes[1].parameters.url_for_test = 'https://kngcxwcybozgqgnoweyt.supabase.co/rest/v1/';
  }, 'forbidden product project'],
  ['a superseded reply sentiment is caught', w => {
    w.nodes[2].parameters.note_for_test = "reply_sentiment: 'hot_pain'";
  }, 'superseded reply sentiment'],
  ['an unreachable node is caught', w => {
    delete w.connections['Config'];
  }, 'unreachable from any trigger'],
  ['a workflow with no trigger is caught', w => {
    w.nodes = w.nodes.filter(n => n.type !== 'n8n-nodes-base.webhook');
    w.connections = {};
  }, 'no trigger node'],
  ['unparseable JSON is caught', null, 'does not parse as JSON'],

  // --- paired Config nodes. These need a workflow that has a pair, so they
  // --- name their own source file rather than breaking WF-C1.
  ['a divergent value between paired Config nodes is caught', w => {
    const n = w.nodes.find(x => x.name === 'Config approve');
    const a = n.parameters.assignments.assignments.find(x => x.name === 'cfg');
    a.value = a.value.replace("ig_user_id: ''", "ig_user_id: '17841400000000000'");
  }, 'Config nodes "Config" and "Config approve" disagree', 'WF-C4.json'],

  ['a key missing from one copy of a paired Config is caught', w => {
    const n = w.nodes.find(x => x.name === 'Config webhook');
    const a = n.parameters.assignments.assignments.find(x => x.name === 'cfg');
    a.value = a.value.replace(/\n {2}price_setup_once: '',?/, '');
  }, 'only "Config" has it', 'WF-C5.json'],

  ['a renamed Config node is still checked (the pair is found by shape)', w => {
    const n = w.nodes.find(x => x.name === 'Config approve');
    const a = n.parameters.assignments.assignments.find(x => x.name === 'cfg');
    a.value = a.value.replace("fb_page_id: ''", "fb_page_id: '99'");
    // Rename it and rewire, so only the cfg assignment identifies it.
    const old = n.name;
    n.name = 'Settings for the approve path';
    w.connections[n.name] = w.connections[old];
    delete w.connections[old];
    for (const spec of Object.values(w.connections)) {
      for (const outputs of Object.values(spec)) {
        for (const targets of outputs || []) {
          for (const t of targets || []) if (t && t.node === old) t.node = n.name;
        }
      }
    }
    for (const node of w.nodes) {
      if (node.parameters && typeof node.parameters.jsCode === 'string') {
        node.parameters.jsCode = node.parameters.jsCode.split(`$('${old}')`).join(`$('${n.name}')`);
      }
      walkReplace(node.parameters, old, n.name);
    }
  }, 'disagree', 'WF-C4.json'],
];

// Rewrites $('Config approve') references inside plain expression strings too,
// so the renamed-node case produces a workflow that is otherwise still valid
// and the ONLY error is the one under test.
function walkReplace(v, from, to) {
  if (!v || typeof v !== 'object') return;
  for (const [k, val] of Object.entries(v)) {
    if (typeof val === 'string') v[k] = val.split(`$('${from}')`).join(`$('${to}')`);
    else walkReplace(val, from, to);
  }
}

const dir = mkdtempSync(join(tmpdir(), 'wfselftest-'));
let pass = 0, fail = 0;

function runValidatorOn(fileContents) {
  writeFileSync(join(dir, 'WF-CX.json'), fileContents);
  try {
    // Point the validator at the scratch dir by copying it and rewriting DIR.
    const src = readFileSync(join(ROOT, 'tools', 'validate.mjs'), 'utf8')
      .replace("const DIR = join(ROOT, 'workflows');", `const DIR = ${JSON.stringify(dir)};`);
    writeFileSync(join(dir, 'v.mjs'), src);
    return execFileSync('node', [join(dir, 'v.mjs')], { encoding: 'utf8' });
  } catch (e) {
    return (e.stdout || '') + (e.stderr || '');
  }
}

for (const [label, mutate, expect, srcFile] of CASES) {
  let contents;
  if (mutate === null) contents = '{ this is not json ';
  else { const w = clone(srcFile); mutate(w); contents = JSON.stringify(w, null, 2); }

  const out = runValidatorOn(contents);
  const caught = out.includes(expect);
  const failedOverall = /[1-9]\d* error\(s\)/.test(out);

  if (caught && failedOverall) { console.log(`  PASS  ${label}`); pass++; }
  else {
    console.log(`  FAIL  ${label}`);
    console.log(`        expected the output to contain: ${expect}`);
    console.log(out.split('\n').map(l => '        | ' + l).join('\n'));
    fail++;
  }
}

// And the controls: the unmodified files must still pass. WF-C4 and WF-C5 are
// here because they are the two that carry a Config pair - a sync check that
// fires on the real exports would be worse than no check at all.
for (const f of ['WF-C1.json', 'WF-C4.json', 'WF-C5.json']) {
  const out = runValidatorOn(JSON.stringify(load(f), null, 2));
  if (/0 error\(s\)/.test(out)) { console.log(`  PASS  unmodified ${f} still passes`); pass++; }
  else { console.log(`  FAIL  unmodified ${f} no longer passes`); console.log(out); fail++; }
}

rmSync(dir, { recursive: true, force: true });
console.log(`\nvalidator self-test: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
