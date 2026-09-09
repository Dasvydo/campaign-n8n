#!/usr/bin/env node
/* Check that every script WF-C6 shells out to still exists in its sibling repo.
 *
 * WF-C6 is the Friday brief. Two of its nodes leave this repo entirely:
 *
 *   Run: pull_ad_stats.py (Batch E)   cd <ad_engine_repo> && python report/pull_ad_stats.py
 *   Run: friday_brief.py  (Batch B)   cd <ledger_repo>    && python src/friday_brief.py
 *
 * Nothing checked those paths. A rename in ad-engine or campaign-ledger would
 * leave this repo's validators, self-test and node harness all green while the
 * Friday brief silently produced nothing on the n8n host - and the first signal
 * would be an empty brief on a Friday morning.
 *
 * This parses the commands out of the export rather than hardcoding them, so it
 * keeps working if the paths are edited, and fails if the target moves.
 *
 * Siblings are located the way NEW-PC-SETUP.md says to clone them: beside this
 * repo under one parent. When they are absent the check SKIPS loudly rather
 * than failing, so a developer with only this repo still gets a clean run -
 * but it says plainly that it did not verify anything.
 *
 *   node tools/check-sibling-invocations.mjs
 */
import { readFileSync, existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, '..');
const PARENT = resolve(REPO, '..');

// cfg key in the Config node -> sibling directory name
const REPOS = { ad_engine_repo: 'ad-engine', ledger_repo: 'campaign-ledger' };

const wf = JSON.parse(readFileSync(join(REPO, 'workflows', 'WF-C6.json'), 'utf8'));

// `=cd {{ ...cfg.ad_engine_repo }} && {{ ...python_bin }} report/pull_ad_stats.py --date ...`
const INVOCATION = /cfg\.(\w+_repo)\s*\}\}\s*&&\s*\{\{[^}]*\}\}\s+([\w./-]+\.py)/;

const found = [];
for (const node of wf.nodes ?? []) {
  const cmd = node.parameters?.command;
  if (typeof cmd !== 'string') continue;
  const m = INVOCATION.exec(cmd);
  if (m) found.push({ node: node.name, cfgKey: m[1], script: m[2] });
}

if (found.length === 0) {
  console.error('FAIL  no sibling invocations found in WF-C6. Either the nodes were');
  console.error('      removed, or the command shape changed and this check went blind.');
  console.error('      A check that cannot fail is worse than no check - fix the regex.');
  process.exit(1);
}

let failed = 0, skipped = 0;
console.log(`checking ${found.length} sibling invocation(s) from WF-C6\n`);

for (const { node, cfgKey, script } of found) {
  const dirName = REPOS[cfgKey];
  if (!dirName) {
    console.error(`FAIL  ${node}`);
    console.error(`      cfg.${cfgKey} is not a repo this check knows about.`);
    console.error(`      Add it to REPOS in this file.`);
    failed++;
    continue;
  }
  const repoDir = join(PARENT, dirName);
  if (!existsSync(repoDir)) {
    console.log(`SKIP  ${node}`);
    console.log(`      ${dirName} is not checked out beside this repo, so`);
    console.log(`      ${script} was NOT verified. Clone the six as siblings`);
    console.log(`      (ops/NEW-PC-SETUP.md) to make this check real.`);
    skipped++;
    continue;
  }
  const target = join(repoDir, script);
  if (existsSync(target)) {
    console.log(`ok    ${node}  ->  ${dirName}/${script}`);
  } else {
    console.error(`FAIL  ${node}`);
    console.error(`      ${dirName}/${script} does not exist.`);
    console.error(`      WF-C6 would cd into the repo and fail on the n8n host,`);
    console.error(`      and the first signal would be an empty Friday brief.`);
    failed++;
  }
}

console.log();
if (failed) {
  console.error(`${failed} broken invocation(s).`);
  process.exit(1);
}
console.log(skipped
  ? `${found.length - skipped} verified, ${skipped} skipped (siblings absent).`
  : `all ${found.length} verified.`);
