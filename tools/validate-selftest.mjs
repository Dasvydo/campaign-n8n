#!/usr/bin/env node
/**
 * Proves the validator is not just printing "ok".
 *
 * A validator that has never failed is indistinguishable from a validator that
 * cannot fail. This takes the real WF-C1 export, breaks it eleven different
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
const base = JSON.parse(readFileSync(join(ROOT, 'workflows', 'WF-C1.json'), 'utf8'));
const clone = () => JSON.parse(JSON.stringify(base));

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
  ['an unreachable node is caught', w => {
    delete w.connections['Config'];
  }, 'unreachable from any trigger'],
  ['a workflow with no trigger is caught', w => {
    w.nodes = w.nodes.filter(n => n.type !== 'n8n-nodes-base.webhook');
    w.connections = {};
  }, 'no trigger node'],
  ['unparseable JSON is caught', null, 'does not parse as JSON'],
];

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

for (const [label, mutate, expect] of CASES) {
  let contents;
  if (mutate === null) contents = '{ this is not json ';
  else { const w = clone(); mutate(w); contents = JSON.stringify(w, null, 2); }

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

// And the control: the unmodified file must still pass.
const out = runValidatorOn(JSON.stringify(base, null, 2));
if (/0 error\(s\)/.test(out)) { console.log('  PASS  the unmodified export still passes'); pass++; }
else { console.log('  FAIL  the unmodified export no longer passes'); console.log(out); fail++; }

rmSync(dir, { recursive: true, force: true });
console.log(`\nvalidator self-test: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
