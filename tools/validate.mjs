#!/usr/bin/env node
/**
 * Structural validator for the exported workflows.
 *
 * WHAT THIS IS AND IS NOT. There is no n8n binary in this container, so
 * "import-valid" here cannot mean "n8n accepted it". It means: the file parses
 * as JSON, and it conforms to the shape n8n's importer requires, checked
 * property by property. That catches the whole class of mistakes that actually
 * breaks an import - a connection naming a node that does not exist, a missing
 * position, a duplicated node id, a node with no parameters object - and it
 * catches the things the QA gate asks about that a schema check would not: a
 * credential value left in a file, a workflow exported active, an unreachable
 * node, the forbidden project ref.
 *
 * What it cannot check is stated honestly in RUN-REPORT.md.
 *
 *   node tools/validate.mjs
 */
import { readFileSync, readdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const DIR = join(ROOT, 'workflows');

const FORBIDDEN_PROJECT_REF = 'kngcxwcybozgqgnoweyt';

// The reply sentiment taxonomy changed on 2026-09-06 to
//   interested, not_now, not_a_fit, referred, objection, unsubscribe
// (campaign-ledger/migrations/001_schema.sql, campaign.reply_sentiment).
// The superseded values must not appear in any node, expression or payload,
// because the ledger enum will reject them as a cast error at insert time.
const SUPERSEDED_SENTIMENTS = /\b(hot_pain|curious|endorse|unrelated|ineligible)\b/;

// Anything that looks like a live secret rather than a name.
const SECRET_PATTERNS = [
  [/eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\./, 'a JWT'],
  [/\bsk_(live|test)_[A-Za-z0-9]{10,}/, 'a Stripe secret key'],
  [/\brk_(live|test)_[A-Za-z0-9]{10,}/, 'a Stripe restricted key'],
  [/\bwhsec_[A-Za-z0-9]{10,}/, 'a Stripe webhook signing secret'],
  [/\bEAA[A-Za-z0-9]{60,}/, 'a Meta access token'],
  [/\bxox[baprs]-[A-Za-z0-9-]{10,}/, 'a Slack token'],
  [/\bghp_[A-Za-z0-9]{20,}/, 'a GitHub token'],
  [/\bAIza[A-Za-z0-9_-]{30,}/, 'a Google API key'],
  [/-----BEGIN [A-Z ]*PRIVATE KEY-----/, 'a private key'],
];

const TRIGGER_TYPES = new Set([
  'n8n-nodes-base.webhook',
  'n8n-nodes-base.scheduleTrigger',
  'n8n-nodes-base.cron',
  'n8n-nodes-base.manualTrigger',
  'n8n-nodes-base.executeWorkflowTrigger',
  'n8n-nodes-base.errorTrigger',
  'n8n-nodes-base.formTrigger',
]);

// Credential references may carry these keys and nothing else.
const CREDENTIAL_KEYS = new Set(['id', 'name']);

let totalErrors = 0;
let totalWarnings = 0;
const summary = [];

function walkStrings(value, path, fn) {
  if (typeof value === 'string') { fn(value, path); return; }
  if (Array.isArray(value)) {
    value.forEach((v, i) => walkStrings(v, `${path}[${i}]`, fn));
    return;
  }
  if (value && typeof value === 'object') {
    for (const [k, v] of Object.entries(value)) walkStrings(v, `${path}.${k}`, fn);
  }
}

function checkFile(file) {
  const errors = [];
  const warnings = [];
  const raw = readFileSync(join(DIR, file), 'utf8');

  let wf;
  try {
    wf = JSON.parse(raw);
  } catch (e) {
    errors.push(`does not parse as JSON: ${e.message}`);
    return { file, errors, warnings, nodes: 0 };
  }

  // ---- top level ---------------------------------------------------------
  if (typeof wf.name !== 'string' || !wf.name.trim()) errors.push('no top-level "name"');
  if (!Array.isArray(wf.nodes)) errors.push('"nodes" is not an array');
  if (!wf.connections || typeof wf.connections !== 'object' || Array.isArray(wf.connections)) {
    errors.push('"connections" is not an object');
  }
  if (wf.active !== false) errors.push(`"active" must be exactly false, got ${JSON.stringify(wf.active)}`);
  if ('id' in wf) errors.push('carries a top-level "id": on import it could overwrite an existing workflow');
  if (!wf.settings || typeof wf.settings !== 'object') warnings.push('no "settings" object');

  if (!Array.isArray(wf.nodes)) return { file, errors, warnings, nodes: 0 };

  // ---- nodes -------------------------------------------------------------
  const names = new Set();
  const ids = new Set();
  const triggers = [];
  const webhookPaths = new Set();

  for (const [i, n] of wf.nodes.entries()) {
    const where = `node[${i}]${n && n.name ? ` "${n.name}"` : ''}`;
    if (!n || typeof n !== 'object') { errors.push(`${where}: not an object`); continue; }

    if (typeof n.name !== 'string' || !n.name.trim()) errors.push(`${where}: no "name"`);
    else if (names.has(n.name)) errors.push(`${where}: duplicate node name "${n.name}" (connections key on name)`);
    else names.add(n.name);

    if (typeof n.id !== 'string' || !n.id.trim()) errors.push(`${where}: no "id"`);
    else if (ids.has(n.id)) errors.push(`${where}: duplicate node id "${n.id}"`);
    else ids.add(n.id);

    if (typeof n.type !== 'string' || !/^(n8n-nodes-base|@n8n\/|CUSTOM)\./.test(n.type)) {
      errors.push(`${where}: "type" is missing or not a node type: ${JSON.stringify(n.type)}`);
    }
    if (typeof n.typeVersion !== 'number') errors.push(`${where}: "typeVersion" is not a number`);
    if (!Array.isArray(n.position) || n.position.length !== 2 ||
        !n.position.every(p => typeof p === 'number')) {
      errors.push(`${where}: "position" must be [x, y] numbers`);
    }
    if (!n.parameters || typeof n.parameters !== 'object' || Array.isArray(n.parameters)) {
      errors.push(`${where}: "parameters" must be an object (use {} for none)`);
    }
    if (n.disabled === true) warnings.push(`${where}: is disabled in the export`);

    if (TRIGGER_TYPES.has(n.type)) triggers.push(n.name);

    // Code nodes must actually carry code.
    if (n.type === 'n8n-nodes-base.code') {
      const js = n.parameters && n.parameters.jsCode;
      if (typeof js !== 'string' || js.trim().length < 10) {
        errors.push(`${where}: code node has no jsCode`);
      }
    }

    // Webhook paths: unique inside a workflow per method, and namespaced.
    if (n.type === 'n8n-nodes-base.webhook') {
      const p = n.parameters && n.parameters.path;
      const m = (n.parameters && n.parameters.httpMethod) || 'GET';
      if (typeof p !== 'string' || !p.trim()) errors.push(`${where}: webhook has no path`);
      else {
        if (!p.startsWith('campaign/')) {
          warnings.push(`${where}: webhook path "${p}" is not namespaced under campaign/`);
        }
        const key = `${m} ${p}`;
        if (webhookPaths.has(key)) errors.push(`${where}: duplicate webhook ${key} inside this workflow`);
        webhookPaths.add(key);
      }
    }

    // Credentials: names only. No values, ever.
    if (n.credentials) {
      if (typeof n.credentials !== 'object' || Array.isArray(n.credentials)) {
        errors.push(`${where}: "credentials" is not an object`);
      } else {
        for (const [credType, ref] of Object.entries(n.credentials)) {
          if (!ref || typeof ref !== 'object') {
            errors.push(`${where}: credential "${credType}" is not a reference object`);
            continue;
          }
          for (const k of Object.keys(ref)) {
            if (!CREDENTIAL_KEYS.has(k)) {
              errors.push(`${where}: credential "${credType}" carries key "${k}" — only id and name are allowed`);
            }
          }
          if (typeof ref.name !== 'string' || !ref.name.trim()) {
            errors.push(`${where}: credential "${credType}" has no name to look up`);
          }
        }
      }
    }
  }

  if (triggers.length === 0) errors.push('no trigger node: this workflow can never start');

  // ---- connections -------------------------------------------------------
  const conns = wf.connections || {};
  for (const [src, spec] of Object.entries(conns)) {
    if (!names.has(src)) {
      errors.push(`connections: source "${src}" is not a node in this workflow`);
      continue;
    }
    if (!spec || typeof spec !== 'object') {
      errors.push(`connections["${src}"]: not an object`);
      continue;
    }
    for (const [kind, outputs] of Object.entries(spec)) {
      if (!Array.isArray(outputs)) {
        errors.push(`connections["${src}"].${kind}: not an array of outputs`);
        continue;
      }
      outputs.forEach((targets, outIdx) => {
        if (targets === null) return;
        if (!Array.isArray(targets)) {
          errors.push(`connections["${src}"].${kind}[${outIdx}]: not an array`);
          return;
        }
        for (const t of targets) {
          if (!t || typeof t !== 'object') {
            errors.push(`connections["${src}"].${kind}[${outIdx}]: target is not an object`);
            continue;
          }
          if (!names.has(t.node)) {
            errors.push(`connections["${src}"].${kind}[${outIdx}] -> "${t.node}" does not exist`);
          }
          if (typeof t.index !== 'number') {
            errors.push(`connections["${src}"] -> "${t.node}": "index" is not a number`);
          }
          if (t.type !== kind) {
            warnings.push(`connections["${src}"] -> "${t.node}": type "${t.type}" != "${kind}"`);
          }
        }
      });
    }
  }

  // ---- reachability ------------------------------------------------------
  const reached = new Set(triggers);
  const queue = [...triggers];
  while (queue.length) {
    const cur = queue.shift();
    const spec = conns[cur];
    if (!spec) continue;
    for (const outputs of Object.values(spec)) {
      for (const targets of outputs || []) {
        for (const t of targets || []) {
          if (t && names.has(t.node) && !reached.has(t.node)) {
            reached.add(t.node);
            queue.push(t.node);
          }
        }
      }
    }
  }
  for (const n of names) {
    if (!reached.has(n)) errors.push(`node "${n}" is unreachable from any trigger`);
  }

  // ---- merge node input arity -------------------------------------------
  for (const n of wf.nodes) {
    if (n.type !== 'n8n-nodes-base.merge') continue;
    const declared = Number((n.parameters && n.parameters.numberInputs) || 2);
    let maxIdx = -1;
    for (const spec of Object.values(conns)) {
      for (const outputs of Object.values(spec)) {
        for (const targets of outputs || []) {
          for (const t of targets || []) {
            if (t && t.node === n.name) maxIdx = Math.max(maxIdx, t.index);
          }
        }
      }
    }
    if (maxIdx >= declared) {
      errors.push(`merge node "${n.name}" declares ${declared} inputs but is wired to index ${maxIdx}`);
    }
  }

  // ---- secrets and the forbidden project --------------------------------
  walkStrings(wf, wf.name, (s, path) => {
    for (const [re, what] of SECRET_PATTERNS) {
      if (re.test(s)) errors.push(`${path}: contains ${what}`);
    }
    if (s.includes(FORBIDDEN_PROJECT_REF) && !path.includes('jsCode')) {
      errors.push(`${path}: names the forbidden product project ref`);
    }
    const m = SUPERSEDED_SENTIMENTS.exec(s);
    if (m) errors.push(`${path}: uses superseded reply sentiment "${m[1]}"`);
  });

  return { file, errors, warnings, nodes: wf.nodes.length, triggers: triggers.length };
}

const files = readdirSync(DIR).filter(f => f.endsWith('.json')).sort();
if (files.length === 0) {
  console.error('no workflow files found in workflows/');
  process.exit(1);
}

console.log(`validating ${files.length} workflow file(s) in workflows/\n`);

for (const f of files) {
  const r = checkFile(f);
  totalErrors += r.errors.length;
  totalWarnings += r.warnings.length;
  const mark = r.errors.length ? 'FAIL' : 'ok  ';
  console.log(`${mark} ${f}  (${r.nodes} nodes, ${r.triggers ?? 0} trigger(s))`);
  for (const e of r.errors) console.log(`       ERROR   ${e}`);
  for (const w of r.warnings) console.log(`       warn    ${w}`);
  summary.push(r);
}

console.log(`\n${files.length} file(s), ${summary.reduce((a, r) => a + r.nodes, 0)} nodes, ` +
  `${totalErrors} error(s), ${totalWarnings} warning(s)`);
process.exit(totalErrors ? 1 : 0);
