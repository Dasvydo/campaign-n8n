#!/usr/bin/env node
/* Check that workflows/*.json are exactly what tools/build_workflows.py emits.
 *
 * The repo's rule is "never hand-edit a workflow export - edit the builder and
 * regenerate". Until now that was a request in prose. Nothing enforced it, and
 * a hand-edit is invisible: validate.mjs, the self-test and the node harness
 * all read the committed JSON, so an edit that is structurally valid passes
 * every check while silently diverging from the source that is supposed to
 * produce it. The next person to run the builder would then wipe the edit
 * without noticing, or - worse - keep it and never know the two disagreed.
 *
 * How it works: the builder derives its output directory from its own
 * __file__ (`ROOT = parents[1]`, `OUT = ROOT / "workflows"`), so copying it
 * into a scratch tree makes it write there instead. Nothing under this repo's
 * workflows/ is touched, on success or on failure - this check only ever
 * reads them.
 *
 *   node tools/check-regen.mjs
 *
 * Exit 0 = committed exports match the builder byte for byte.
 * Exit 1 = they do not. The fix is `python3 tools/build_workflows.py`, after
 *          moving whatever you hand-edited into the builder.
 */
import { readFileSync, writeFileSync, mkdirSync, mkdtempSync, rmSync, readdirSync, existsSync }
  from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { tmpdir } from 'node:os';
import { spawnSync } from 'node:child_process';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, '..');
const BUILDER = join(REPO, 'tools', 'build_workflows.py');
const COMMITTED = join(REPO, 'workflows');

if (!existsSync(BUILDER)) {
  console.error(`FAIL  no builder at ${BUILDER}. The exports have no source.`);
  process.exit(1);
}

const python = ['python3', 'python'].find(
  (bin) => spawnSync(bin, ['--version'], { stdio: 'ignore' }).status === 0);

if (!python) {
  console.log('SKIP  no python3 on PATH, so the builder cannot be run and nothing');
  console.log('      was verified. Install python3 to check the exports against it.');
  process.exit(0);
}

const scratch = mkdtempSync(join(tmpdir(), 'wf-regen-'));
let failed = 0;

try {
  // The builder writes to <its parent's parent>/workflows. Give it a scratch
  // one so the committed exports are never written to.
  mkdirSync(join(scratch, 'tools'), { recursive: true });
  writeFileSync(join(scratch, 'tools', 'build_workflows.py'), readFileSync(BUILDER));

  const run = spawnSync(python, [join(scratch, 'tools', 'build_workflows.py')],
                        { encoding: 'utf8' });
  if (run.status !== 0) {
    console.error('FAIL  the builder itself does not run:\n');
    console.error((run.stderr || run.stdout || '').trimEnd());
    process.exit(1);
  }

  const regenDir = join(scratch, 'workflows');
  const listJson = (dir) =>
    existsSync(dir) ? readdirSync(dir).filter((f) => f.endsWith('.json')).sort() : [];

  const regen = listJson(regenDir);
  const committed = listJson(COMMITTED);

  if (regen.length === 0) {
    console.error('FAIL  the builder produced no workflows. Either it changed where it');
    console.error('      writes, or this check went blind - fix the check, not the JSON.');
    process.exit(1);
  }

  console.log(`regenerated ${regen.length} workflow(s) into a scratch tree; ` +
              `comparing with workflows/\n`);

  for (const name of regen) {
    if (!committed.includes(name)) {
      console.error(`FAIL  ${name}  the builder emits it, but it is not committed`);
      failed++;
      continue;
    }
    const want = readFileSync(join(regenDir, name));
    const have = readFileSync(join(COMMITTED, name));
    if (want.equals(have)) {
      console.log(`  ok   ${name}`);
      continue;
    }
    failed++;
    const wantLines = want.toString('utf8').split('\n');
    const haveLines = have.toString('utf8').split('\n');
    const at = wantLines.findIndex((line, i) => line !== haveLines[i]);
    console.error(`FAIL  ${name}  differs from what the builder emits`);
    if (at >= 0) {
      console.error(`        first difference at line ${at + 1}`);
      console.error(`        committed: ${JSON.stringify((haveLines[at] ?? '').trim().slice(0, 100))}`);
      console.error(`        builder:   ${JSON.stringify((wantLines[at] ?? '').trim().slice(0, 100))}`);
    } else {
      console.error(`        same lines, different bytes (encoding or trailing newline)`);
    }
  }

  for (const name of committed) {
    if (!regen.includes(name)) {
      console.error(`FAIL  ${name}  committed, but no builder function emits it`);
      failed++;
    }
  }
} finally {
  rmSync(scratch, { recursive: true, force: true });
}

console.log();
if (failed) {
  console.error(`${failed} workflow(s) do not match tools/build_workflows.py.`);
  console.error('A workflow export is generated, not source. Move the change into the');
  console.error('builder and run:  python3 tools/build_workflows.py');
  process.exit(1);
}
console.log('all workflow exports match tools/build_workflows.py');
