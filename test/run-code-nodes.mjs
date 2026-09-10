#!/usr/bin/env node
/**
 * Runs the real Code node bodies out of the exported workflow JSON against the
 * real sample payloads, in a small n8n shim.
 *
 * This is the difference between "I built a validation node" and "the
 * validation node does what I said it does". The bodies executed here are read
 * out of workflows/*.json at run time, so they cannot drift from what would be
 * imported into n8n.
 *
 * It proves, specifically, the four things the QA gate and the brief ask about:
 *   1. WF-C1 handles a malformed payload without losing the lead
 *   2. WF-C1 dedupes on the header when present and on the derived key when not
 *   3. WF-C2 sends nothing without a proven opt-in, and nothing at all for dk
 *      until the marketing-law flag is set
 *   4. WF-C3 has a working non-Buffer fallback path, routed by the real IF
 *      conditions taken from the export
 *
 *   node test/run-code-nodes.mjs
 */
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const payloads = JSON.parse(readFileSync(join(ROOT, 'test', 'sample-payloads.json'), 'utf8'));

const wfCache = new Map();
function wf(key) {
  if (!wfCache.has(key)) {
    wfCache.set(key, JSON.parse(readFileSync(join(ROOT, 'workflows', `${key}.json`), 'utf8')));
  }
  return wfCache.get(key);
}
function nodeOf(key, name) {
  const n = wf(key).nodes.find(x => x.name === name);
  if (!n) throw new Error(`${key} has no node named "${name}"`);
  return n;
}

/* ---- the shim ---------------------------------------------------------- */

function makeRunner() {
  const staticData = { global: {} };
  const outputs = new Map();          // node name -> items

  function nodeAccessor(name) {
    const items = outputs.get(name) || [];
    return {
      all: () => items,
      first: () => items[0],
      get item() { return items[0]; },
    };
  }

  function run(key, nodeName, items) {
    const body = nodeOf(key, nodeName).parameters.jsCode;
    const $input = {
      all: () => items,
      first: () => items[0],
      get item() { return items[0]; },
    };
    const $ = (name) => nodeAccessor(name);
    const $getWorkflowStaticData = (scope) => (staticData[scope] = staticData[scope] || {});
    const fn = new Function('$input', '$', '$getWorkflowStaticData', 'Buffer', '$json',
      `"use strict";\n${body}`);
    const result = fn($input, $, $getWorkflowStaticData, Buffer, items[0] && items[0].json);
    outputs.set(nodeName, result);
    return result;
  }

  function seed(nodeName, items) { outputs.set(nodeName, items); }

  /* Evaluates an IF node's real condition string from the export, so the routing
     tested here is the routing that ships, not a paraphrase of it. */
  function ifCondition(key, nodeName, json) {
    const n = nodeOf(key, nodeName);
    const raw = n.parameters.conditions.conditions[0].leftValue;
    const expr = String(raw).replace(/^=\{\{/, '').replace(/\}\}$/, '');
    const fn = new Function('$json', '$', `"use strict"; return (${expr});`);
    return !!fn(json, $ => nodeAccessor($));
  }

  return { run, seed, ifCondition, staticData, outputs };
}

/* ---- assertions -------------------------------------------------------- */

let pass = 0, fail = 0;
const failures = [];
function check(label, cond, detail) {
  if (cond) { console.log(`  PASS  ${label}`); pass++; }
  else {
    console.log(`  FAIL  ${label}${detail ? `\n        ${detail}` : ''}`);
    failures.push(label); fail++;
  }
}
function section(t) { console.log(`\n${t}\n${'-'.repeat(t.length)}`); }

const CFG_C1 = { ledger_url: 'https://oqpeebtwtikdzorgouxd.supabase.co',
                 dovy_email: 'hello@doviloop.dev', from_email: 'bot@doviloop.dev',
                 data_dir: '/tmp/campaign' };

function webhookItem(sample, cfg) {
  return [{ json: { cfg, headers: Object.fromEntries(
    Object.entries(sample._headers || {}).map(([k, v]) => [k.toLowerCase(), v])),
    body: sample.body, query: {}, params: {} } }];
}

/* =========================================================================
   WF-C1
   ========================================================================= */
section('WF-C1 · validate and route, on every sample payload');

const q = payloads.wf_c1_qualifier;
const r = makeRunner();

const results = {};
for (const [name, sample] of Object.entries(q)) {
  if (name.startsWith('_')) continue;
  results[name] = r.run('WF-C1', 'Validate and route', webhookItem(sample, CFG_C1))[0].json;
}

check('qualified: outlook + 25-49 routes to stage "qualified"',
  results.qualified_outlook_global.outcome === 'qualified',
  `got ${results.qualified_outlook_global.outcome}`);
check('gmail: gmail + 10-24 routes to stage "gmail_on_request" (Batch B\'s enum value, not a flag)',
  results.gmail_on_request_lt.outcome === 'gmail_on_request' &&
  results.gmail_on_request_lt.lead_row.stage === 'gmail_on_request');
check('other mail client + 50+ also routes to "gmail_on_request"',
  results.no_dedupe_header.outcome === 'gmail_on_request');
check('1-9 routes to "too_small"',
  results.too_small_dk.outcome === 'too_small');
check('the too_small row satisfies B\'s CHECK ((team_size = 1-9) = (stage = too_small))',
  (results.too_small_dk.lead_row.team_size === '1-9') ===
  (results.too_small_dk.lead_row.stage === 'too_small'));

check('natural_key is byte-for-byte Batch B\'s: lower(work_email) + "|" + submitted_at verbatim',
  results.qualified_outlook_global.natural_key ===
  'ruth.pell@harbourline-acc.co.uk|2026-09-15T09:41:22.318Z',
  `got ${results.qualified_outlook_global.natural_key}`);

check('dedupe uses the X-DoviLoop-Dedupe header when present',
  results.qualified_outlook_global.dedupe_source === 'header:X-DoviLoop-Dedupe' &&
  results.qualified_outlook_global.dedupe_key === 'b1f2c3d4-0001-4a11-9c22-000000000001');
check('a retry with the same header produces the same dedupe key',
  results.duplicate_of_qualified.dedupe_key === results.qualified_outlook_global.dedupe_key);
check('dedupe falls back to B\'s derived key when the header is absent',
  results.no_dedupe_header.dedupe_source === 'derived:work_email+submitted_at' &&
  results.no_dedupe_header.dedupe_key === results.no_dedupe_header.natural_key);

check('the lead row contains ONLY columns that exist in campaign.leads',
  Object.keys(results.qualified_outlook_global.lead_row).every(k =>
    ['company_name', 'work_email', 'phone', 'team_size', 'email_client', 'role',
     'market', 'locale', 'source', 'utm_source', 'utm_medium', 'utm_campaign',
     'utm_content', 'stage', 'company_id', 'submitted_at', 'natural_key'].includes(k)),
  JSON.stringify(Object.keys(results.qualified_outlook_global.lead_row)));
check('nulls are stripped, so a merge cannot blank a known column',
  !('phone' in results.no_dedupe_header.lead_row));
check('company site is derived from the email domain',
  results.qualified_outlook_global.company_site === 'https://harbourline-acc.co.uk');

section('WF-C1 · malformed payloads are REJECTED but never lost');

for (const bad of ['malformed_missing_keys', 'malformed_bad_enum', 'malformed_not_an_object']) {
  check(`${bad}: marked not-ok`, results[bad].ok === false);
}
check('an extra unknown key is TOLERATED, not bounced',
  results.tolerated_extra_key.ok === true &&
  results.tolerated_extra_key.problems.some(p => p.startsWith('unexpected key (ignored)')) &&
  !('referrer_hint' in results.tolerated_extra_key.lead_row));
check('a bad enum names the field in the problem list',
  results.malformed_bad_enum.fatal_problems.some(p => p.includes('team_size')));

// The proof that matters: the dead letter keeps the whole payload.
const dl = {};
for (const bad of ['malformed_missing_keys', 'malformed_bad_enum', 'malformed_not_an_object']) {
  dl[bad] = r.run('WF-C1', 'Dead letter: malformed', [{ json: results[bad] }])[0].json;
}
check('dead letter preserves the ORIGINAL body of a half-filled form',
  dl.malformed_missing_keys.dead_letter.raw_body.work_email === 'someone@halfway.example' &&
  dl.malformed_missing_keys.dead_letter.raw_body.company_name === 'Halfway Filled Form Ltd');
check('dead letter preserves a body that was not even an object',
  JSON.stringify(dl.malformed_not_an_object.dead_letter.raw_body)
    .includes('this is not a json object at all'),
  JSON.stringify(dl.malformed_not_an_object.dead_letter.raw_body));
check('dead letter carries the dedupe key, so a replay cannot double-create',
  dl.malformed_bad_enum.dead_letter.dedupe_key === 'b1f2c3d4-0005-4a11-9c22-000000000005');
check('dead letter produces a real email subject and body for Dovy',
  dl.malformed_missing_keys.dl_subject.startsWith('[DEAD LETTER]') &&
  dl.malformed_missing_keys.dl_html.includes('Halfway Filled Form Ltd'));
check('the JSONL line is valid JSON on its own',
  (() => { try { JSON.parse(dl.malformed_bad_enum.line); return true; } catch { return false; } })());

// And the webhook still answers 200 with an error body, rather than 4xx.
const respondNode = nodeOf('WF-C1', 'Respond: accepted with errors');
check('the malformed branch responds 200, not 4xx (a 4xx makes A\'s client retry a payload that will always fail)',
  respondNode.parameters.responseCode === 200 &&
  respondNode.parameters.responseBody.includes('kept: true'));

// The ledger-failure branch: a dead database must also not lose the lead.
r.seed('Validate and route', [{ json: results.qualified_outlook_global }]);
const ledgerDown = r.run('WF-C1', 'Read ledger result',
  [{ json: { statusCode: 503, body: { message: 'upstream connect error' } } }])[0].json;
check('a 5xx from the ledger is data, not a crash', ledgerDown.ledger_stored === false);
const dlLedger = r.run('WF-C1', 'Dead letter: ledger write failed', [{ json: ledgerDown }])[0].json;
check('a failed ledger write dead-letters the lead instead of dropping it',
  dlLedger.dead_letter.kind === 'ledger_write_failed' &&
  dlLedger.dead_letter.raw_body.work_email === 'ruth.pell@harbourline-acc.co.uk');

const stored = r.run('WF-C1', 'Read ledger result',
  [{ json: { statusCode: 201, body: [{ id: 'lead-uuid-1' }] } }])[0].json;
check('a 201 with a row is a store', stored.ledger_stored && stored.lead_id === 'lead-uuid-1');
const dedup = r.run('WF-C1', 'Read ledger result',
  [{ json: { statusCode: 201, body: [] } }])[0].json;
check('an empty array from ignore-duplicates is a DEDUPE, not a failure',
  dedup.ledger_stored === true && dedup.ledger_deduped === true);

section('WF-C1 · routing branches, evaluated from the real IF conditions');

check('IF payload valid sends a good payload down the true branch',
  r.ifCondition('WF-C1', 'IF payload valid', results.qualified_outlook_global) === true);
check('IF payload valid sends a malformed payload down the false branch',
  r.ifCondition('WF-C1', 'IF payload valid', results.malformed_missing_keys) === false);
check('IF too small routes a 1-9 lead to the park branch',
  r.ifCondition('WF-C1', 'IF too small', results.too_small_dk) === true);
check('IF too small routes a qualified lead to the notify branch',
  r.ifCondition('WF-C1', 'IF too small', results.qualified_outlook_global) === false);

const parked = r.run('WF-C1', 'Park: no nurture without opt-in',
  [{ json: Object.assign({}, results.too_small_dk, { lead_id: 'lead-uuid-3' }) }])[0].json;
check('THE CONSENT CONTROL: a too_small lead is parked and no nurture is started',
  parked.parked === true && parked.nurture_started === false);
check('the parked record says what it is waiting for',
  JSON.parse(parked.line).awaiting.includes('explicit opt-in'));

const notify = r.run('WF-C1', 'Email Dovy: new lead',
  [{ json: Object.assign({}, results.gmail_on_request_lt,
      { ledger_stored: true, lead_id: 'lead-uuid-2' }) }])[0].json;
check('the notification subject carries market and team size, per spec',
  notify.lead_subject.includes('Lithuania') && notify.lead_subject.includes('10 to 24 seats'));
check('a gmail_on_request lead gets the Gmail note in the body',
  notify.lead_html.includes('not Outlook'));

/* =========================================================================
   WF-C2
   ========================================================================= */
section('WF-C2 · the consent gate is the legal control, so it is tested hardest');

const c2 = payloads.wf_c2_nurture;
const CFG_C2 = { ledger_url: 'https://oqpeebtwtikdzorgouxd.supabase.co',
                 dovy_email: 'hello@doviloop.dev', from_email: 'dovy@doviloop.dev',
                 unsubscribe_base: 'https://n8n.example/webhook/campaign/unsubscribe',
                 pricing_url: 'https://doviloop.dev/pricing',
                 postal_address: 'DoviLoop, Copenhagen',
                 dk_marketing_law_confirmed: false };

const r2 = makeRunner();
r2.seed('Config', [{ json: { cfg: CFG_C2 } }]);
const gate = (body, cfg = CFG_C2) =>
  r2.run('WF-C2', 'Consent gate', [{ json: Object.assign({ cfg }, body) }])[0].json;

const noOptin = gate(c2.no_optin_should_park.body);
check('a lead with NO opt-in is refused',
  noOptin.consented === false);
check('and the refusal says exactly what was missing',
  noOptin.consent_reasons.some(x => x.includes('optin.granted is not exactly true')));

const dkNoLaw = gate(c2.dk_optin_without_law_confirmation_should_park.body);
check('DENMARK: a real opt-in is STILL refused while the marketing-law flag is unset',
  dkNoLaw.consented === false &&
  dkNoLaw.consent_reasons.some(x => x.includes('dk_marketing_law_confirmed')));

const dkBothSet = gate(Object.assign(
  JSON.parse(JSON.stringify(c2.dk_optin_without_law_confirmation_should_park.body)),
  { optin: Object.assign({}, c2.dk_optin_without_law_confirmation_should_park.body.optin,
      { dk_marketing_law_confirmed: true }) }),
  Object.assign({}, CFG_C2, { dk_marketing_law_confirmed: true }));
check('DENMARK: only with BOTH the per-lead and the instance-wide confirmation does it pass',
  dkBothSet.consented === true);

const good = gate(c2.global_optin_should_send.body);
check('a complete opt-in outside dk passes', good.consented === true, JSON.stringify(good.consent_reasons));

const mismatched = gate({ lead: c2.global_optin_should_send.body.lead,
  optin: Object.assign({}, c2.global_optin_should_send.body.optin,
    { work_email: 'someone.else@example.com' }) });
check('an opt-in pasted onto the wrong person is refused',
  mismatched.consented === false &&
  mismatched.consent_reasons.some(x => x.includes('does not match the lead')));

for (const missing of ['source', 'evidence', 'recorded_at']) {
  const o = Object.assign({}, c2.global_optin_should_send.body.optin);
  delete o[missing];
  check(`an opt-in with no ${missing} is refused`,
    gate({ lead: c2.global_optin_should_send.body.lead, optin: o }).consented === false);
}

// Emails and unsubscribe.
const emails = r2.run('WF-C2', 'Build the three emails', [{ json: good }])[0].json;
const escapedUnsub = emails.unsub_url.replace(/&/g, '&amp;');
check('all three emails carry a working unsubscribe link',
  ['e1', 'e2', 'e3'].every(k =>
    emails.emails[k].html.includes('href="' + escapedUnsub + '"')),
  escapedUnsub);
check('the unsubscribe href is HTML-escaped, so the &-joined query survives',
  escapedUnsub.includes('?e=jo%40twodeskbooks.example&amp;t='));
check('NO em dash appears in any of the three emails (voice rule)',
  !['e1', 'e2', 'e3'].some(k => /—/.test(emails.emails[k].html)));
// Decision 2026-09-06: the ROI figures are MODELLED, not measured. Email 2
// carries them as a worked example and must say so in the same paragraph.
const e2 = emails.emails.e2.html.replace(/<!--[\s\S]*?-->/g, '');
const roiPara = (e2.match(/<p><b>On the numbers\.<\/b>[\s\S]*?<\/p>/) || [''])[0];
// The multiple is 400 EUR saved against one seat at $89/month, about 82 EUR at
// 0.92 USD/EUR: 4.9x, stated as 5x. It read 9x until 2026-09-10, which was
// correct at the withdrawn $49 rate and did not move when the price did. If the
// seat price or the assumed saving changes again, recompute it here and in
// campaign-site/src/content/{en,da,lt}.ts - this check is what catches the two
// drifting apart.
check('email 2 carries all three modelled figures (5x, 400 EUR a month, 40 days)',
  /\b5x\b/.test(roiPara) && /400 EUR a month/.test(roiPara) && /40 days/.test(roiPara));
check('and no stale 9x survives anywhere in email 2',
  !/\b9x\b/.test(e2));
check('and the SAME paragraph says they are a model, not a customer result',
  /a model, not a customer result/.test(roiPara) && /Nothing has been measured/.test(roiPara));
check('and shows the arithmetic: assumed hours, costed at a salary',
  /10 hours a month/.test(roiPara) && /40 EUR an hour/.test(roiPara) && /mid level salary/.test(roiPara));
check('and never claims a measurement, verification or a customer behind them',
  !/measured usage|verified|our customers|clients have seen|firms like yours have seen/i.test(roiPara));
check('email 2 still says plainly that no customer numbers exist yet',
  e2.includes('we do not have a customer'));
check('the ROI block in the node source is non-empty and records the decision',
  /DECISION, Dovy, 2026-09-06[\s\S]*const ROI_BLOCK =\s*'<p>/
    .test(nodeOf('WF-C2', 'Build the three emails').parameters.jsCode));

const unsub = r2.run('WF-C2', 'Record opt-out',
  [{ json: { query: payloads.wf_c2_unsubscribe.query } }])[0].json;
check('an unsubscribe is recorded immediately, with no confirm step',
  unsub.unsub_email === 'jo@twodeskbooks.example');

r2.seed('Config', [{ json: { cfg: CFG_C2 } }]);
const afterUnsub = r2.run('WF-C2', 'Suppression check 2', [{ json: emails }])[0].json;
check('the NEXT email in the sequence is stopped by that unsubscribe',
  afterUnsub.still_subscribed === false);
check('and an unsubscribed address can never be re-enrolled',
  gate(c2.global_optin_should_send.body).consented === false);

/* =========================================================================
   WF-C3
   ========================================================================= */
section('WF-C3 · approval fails closed, and the non-Buffer fallback path works');

const CFG_C3_DIRECT = {
  ledger_url: 'https://oqpeebtwtikdzorgouxd.supabase.co',
  dovy_email: 'hello@doviloop.dev', from_email: 'bot@doviloop.dev',
  publisher: 'direct',
  buffer_api_url: 'https://graph.buffer.com/',
  buffer_channels: { instagram: 'ch1', facebook: 'ch2', youtube_shorts: 'ch3', linkedin: 'ch4' },
  meta_graph_version: 'v21.0', ig_user_id: '178414', fb_page_id: '999',
  asset_base_url: 'https://cdn.doviloop.dev/reels',
};

const CONTENT_ROWS = [
  { id: 'c-en-1', natural_key: 'reel:on_camera:en:the-mail-you-answer-twenty-times',
    kind: 'reel', lane: 'on_camera', language: 'en',
    hook: 'The mail you answer twenty times a week', asset_path: 'https://cdn.doviloop.dev/reels/en-1.mp4',
    platforms: [], published_at: null, buffer_id: null },
  { id: 'c-da-1', natural_key: 'reel:on_camera:da:drafts-in-outlook',
    kind: 'reel', lane: 'on_camera', language: 'da',
    hook: 'Udkast i din egen Outlook', asset_path: 'https://cdn.doviloop.dev/reels/da-1.mp4',
    platforms: [], published_at: null, buffer_id: null },
  { id: 'c-en-2', natural_key: 'reel:higgsfield:en:signed-url',
    kind: 'reel', lane: 'higgsfield', language: 'en',
    hook: 'Six hours of repeat mail',
    asset_path: 'https://cdn.doviloop.dev/reels/en-2.mp4?X-Amz-Signature=deadbeef',
    platforms: [], published_at: null, buffer_id: null },
];

const r3 = makeRunner();
r3.seed('Config', [{ json: { cfg: CFG_C3_DIRECT } }]);

let gateOut = r3.run('WF-C3', 'Approval gate + channel map',
  [{ json: { body: CONTENT_ROWS } }]);
let summary = gateOut.map(i => i.json).find(j => j.__summary);
check('FAILS CLOSED: with an empty approval list, nothing is publishable',
  summary.ready_count === 0 && summary.held.length === 3);
check('and each hold says why',
  summary.held.every(h => h.hold_reasons.includes('not on the approval list')));

// Approve two of them, the way Dovy would.
r3.run('WF-C3', 'Record approval', [{ json: { body: {
  natural_keys: ['reel:on_camera:en:the-mail-you-answer-twenty-times',
                 'reel:on_camera:da:drafts-in-outlook',
                 'reel:higgsfield:en:signed-url'],
  approved_by: 'dovy' } } }]);

gateOut = r3.run('WF-C3', 'Approval gate + channel map', [{ json: { body: CONTENT_ROWS } }]);
summary = gateOut.map(i => i.json).find(j => j.__summary);
const posts = gateOut.map(i => i.json).filter(j => !j.__summary);

check('after approval, the English reel fans out to all four channels',
  posts.filter(p => p.content_id === 'c-en-1').map(p => p.channel).sort().join(',') ===
  'facebook,instagram,linkedin,youtube_shorts');
check('the Danish reel goes to LinkedIn only, per the spec table',
  posts.filter(p => p.content_id === 'c-da-1').map(p => p.channel).join(',') === 'linkedin');
check('a signed/expiring asset URL is held even though it was approved (Batch D\'s rule)',
  summary.held.some(h => h.natural_key === 'reel:higgsfield:en:signed-url' &&
    h.hold_reasons.some(x => x.includes('query string'))));
check('an approval can be revoked and the item stops being publishable',
  (() => {
    r3.run('WF-C3', 'Record approval', [{ json: { body: {
      natural_key: 'reel:on_camera:da:drafts-in-outlook', revoke: true } } }]);
    const g = r3.run('WF-C3', 'Approval gate + channel map', [{ json: { body: CONTENT_ROWS } }]);
    return !g.map(i => i.json).some(j => j.content_id === 'c-da-1' && j.channel);
  })());

section('WF-C3 · the non-Buffer fallback, routed by the real IF conditions');

const routed = {};
for (const p of posts) {
  if (r3.ifCondition('WF-C3', 'IF publisher is Buffer', p)) { routed[p.channel] = 'buffer'; continue; }
  if (r3.ifCondition('WF-C3', 'IF platform is Meta', p)) {
    routed[p.channel] = r3.ifCondition('WF-C3', 'IF platform is Instagram', p)
      ? 'IG: create reel container' : 'FB page: post video';
  } else if (r3.ifCondition('WF-C3', 'IF platform is YouTube', p)) {
    routed[p.channel] = 'YouTube: upload short';
  } else if (r3.ifCondition('WF-C3', 'IF platform is LinkedIn', p)) {
    routed[p.channel] = 'LinkedIn: post video';
  } else routed[p.channel] = 'Unsupported channel';
}
check('publisher "direct" bypasses Buffer entirely',
  !Object.values(routed).includes('buffer'), JSON.stringify(routed));
check('instagram reaches the Instagram container node', routed.instagram === 'IG: create reel container');
check('facebook reaches the FB page video node', routed.facebook === 'FB page: post video');
check('youtube_shorts reaches the YouTube upload node', routed.youtube_shorts === 'YouTube: upload short');
check('linkedin reaches the LinkedIn post node', routed.linkedin === 'LinkedIn: post video');
check('every fallback branch terminates in a node wired to the Collect results merge',
  (() => {
    const conns = wf('WF-C3').connections;
    const feeds = new Set();
    for (const [src, spec] of Object.entries(conns))
      for (const outs of Object.values(spec))
        for (const ts of outs || []) for (const t of ts || [])
          if (t.node === 'Collect results') feeds.add(src);
    return ['Normalise: Instagram', 'Normalise: Facebook', 'Normalise: YouTube',
            'Normalise: LinkedIn', 'Interpret Buffer response'].every(n => feeds.has(n));
  })());

// The write-back, from direct-path results.
const directResults = [
  { json: Object.assign({}, posts.find(p => p.channel === 'instagram'),
      { publisher: 'meta_graph', post_ok: true, post_id: '17900000000000123' }) },
  { json: Object.assign({}, posts.find(p => p.channel === 'facebook'),
      { publisher: 'meta_graph', post_ok: true, post_id: '999_888' }) },
  { json: Object.assign({}, posts.find(p => p.channel === 'youtube_shorts'),
      { publisher: 'youtube_data_api', post_ok: true, post_id: 'yt_abc123' }) },
  { json: Object.assign({}, posts.find(p => p.channel === 'linkedin'),
      { publisher: 'linkedin_api', post_ok: false, post_error: 'LinkedIn: 403 no ugcPost scope' }) },
];
const norm = r3.run('WF-C3', 'Normalise for the ledger', directResults)
  .map(i => i.json).filter(j => j.content_id);
const enRow = norm.find(n => n.content_id === 'c-en-1');
check('three of four channels succeeded, so the row is marked published',
  enRow.any_published === true && enRow.patch !== null);
check('all three post ids survive into the single buffer_id text column',
  enRow.patch.buffer_id === 'instagram=17900000000000123;facebook=999_888;youtube_shorts=yt_abc123');
check('platforms is a real array for the text[] column',
  Array.isArray(enRow.patch.platforms) && enRow.patch.platforms.length === 3);
check('the one failure is kept and reported, not swallowed',
  enRow.errors.length === 1 && enRow.errors[0].includes('linkedin'));

const allFailed = r3.run('WF-C3', 'Normalise for the ledger', [{ json:
  Object.assign({}, posts.find(p => p.channel === 'instagram'),
    { post_ok: false, post_error: 'IG: transcode failed' }) }])
  .map(i => i.json).filter(j => j.content_id)[0];
check('a total failure leaves published_at null so it is retried next Thursday',
  allFailed.any_published === false && allFailed.patch === null);

section('WF-C3 · Buffer\'s HTTP-200-with-an-error-body trap');

const bufItem = (body, channel = 'linkedin') =>
  [{ json: Object.assign({}, posts.find(p => p.channel === channel) || {}, { channel, body }) }];
const interp = (body, channel) =>
  r3.run('WF-C3', 'Interpret Buffer response', bufItem(body, channel))[0].json;

check('a typed error body at HTTP 200 is a FAILURE',
  interp({ data: { createPost: { __typename: 'PostCreateError', message: 'channel not connected' } } })
    .post_ok === false);
check('an UNLISTED error typename is also a failure, because it carries no post id',
  interp({ data: { createPost: { __typename: 'SomeBrandNewError2027', message: 'x' } } })
    .post_ok === false);
check('a real success is a success',
  interp({ data: { createPost: { __typename: 'PostCreated', post: { id: 'p1' } } } })
    .post_ok === true);
check('Instagram with no publishingType fails closed (auto-publish unconfirmed)',
  interp({ data: { createPost: { __typename: 'PostCreated', post: { id: 'p2' } } } }, 'instagram')
    .post_ok === false);
check('Instagram reporting a phone notification fails closed',
  interp({ data: { createPost: { __typename: 'PostCreated',
    post: { id: 'p3', publishingType: 'notification' } } } }, 'instagram').post_ok === false);
check('Instagram confirming auto-publish succeeds',
  interp({ data: { createPost: { __typename: 'PostCreated',
    post: { id: 'p4', publishingType: 'auto' } } } }, 'instagram').post_ok === true);
check('"api" is NOT accepted as proof of auto-publish',
  interp({ data: { createPost: { __typename: 'PostCreated',
    post: { id: 'p5', publishingType: 'api' } } } }, 'instagram').post_ok === false);

/* =========================================================================
   WF-C4 and WF-C5
   ========================================================================= */
section('WF-C4 · keyword match, rate limit, and the mandatory approval step');

const CFG_C4 = { ledger_url: 'https://oqpeebtwtikdzorgouxd.supabase.co',
  dovy_email: 'hello@doviloop.dev', from_email: 'bot@doviloop.dev',
  meta_graph_version: 'v21.0', ig_user_id: '178414', fb_page_id: '999',
  landing_url: 'https://teams.doviloop.dev',
  keywords: ['draft', 'drafts', 'demo', 'outlook', 'info'],
  rate_limit_days: 90, approve_base: 'https://n8n.example/webhook/campaign/meta-dm-approve' };

const r4 = makeRunner();
r4.seed('Config', [{ json: { cfg: CFG_C4 } }]);
r4.seed('Config approve', [{ json: { cfg: CFG_C4 } }]);

const hit = r4.run('WF-C4', 'Match keyword + rate limit',
  [{ json: { body: payloads.wf_c4_meta_comment.instagram_keyword_hit.body } }])[0].json;
check('a comment containing a keyword matches', hit.matched === true && hit.keyword === 'draft');
const miss = r4.run('WF-C4', 'Match keyword + rate limit',
  [{ json: { body: payloads.wf_c4_meta_comment.instagram_no_keyword.body } }])[0].json;
check('a comment without a keyword does not', miss.matched === false);

const draft = r4.run('WF-C4', 'Build DM draft', [{ json: Object.assign({}, hit,
  { content_lookup: [{ id: 'c-en-1', natural_key: 'reel:on_camera:en:the-mail', language: 'en' }] }) }])[0].json;
check('the DM carries the landing page with the reel\'s UTM',
  draft.landing_link.includes('utm_source=instagram') &&
  draft.landing_link.includes('utm_medium=social_dm') &&
  draft.landing_link.includes('utm_content=reel%3Aon_camera%3Aen%3Athe-mail'));
check('THE APPROVAL STEP: the DM is only drafted, and Dovy is asked',
  draft.approval_html.includes('Nothing has been sent') &&
  draft.approve_url.includes(hit.approval_token));
check('no Config key in WF-C4 can switch the approval step off',
  !wf('WF-C4').nodes.filter(n => n.type === 'n8n-nodes-base.set')
    .some(n => /require_approval|skip_approval|auto_?send|approval_?mode/i
      .test(JSON.stringify(n.parameters))));
check('STRUCTURAL: the comment webhook cannot reach the DM send node at all',
  (() => {
    // Everything reachable from the comment trigger. The send node must not be
    // in it: the only way in is the separate approval webhook Dovy clicks.
    const conns = wf('WF-C4').connections;
    const seen = new Set(['Webhook — Meta comments']);
    const queue = ['Webhook — Meta comments'];
    while (queue.length) {
      const cur = queue.shift();
      for (const outs of Object.values(conns[cur] || {}))
        for (const ts of outs || []) for (const t of ts || [])
          if (!seen.has(t.node)) { seen.add(t.node); queue.push(t.node); }
    }
    return !seen.has('Meta: send private reply');
  })());
check('STRUCTURAL: the DM send node is reachable ONLY from the approval webhook',
  (() => {
    const conns = wf('WF-C4').connections;
    const reachable = (start) => {
      const seen = new Set([start]); const queue = [start];
      while (queue.length) {
        const cur = queue.shift();
        for (const outs of Object.values(conns[cur] || {}))
          for (const ts of outs || []) for (const t of ts || [])
            if (!seen.has(t.node)) { seen.add(t.node); queue.push(t.node); }
      }
      return seen;
    };
    // Real triggers only. `respondToWebhook` contains the word "webhook" but
    // is a mid-flow node, not an entry point.
    const TRIGGERS = ['n8n-nodes-base.webhook', 'n8n-nodes-base.scheduleTrigger',
      'n8n-nodes-base.executeWorkflowTrigger', 'n8n-nodes-base.manualTrigger'];
    const triggers = wf('WF-C4').nodes
      .filter(n => TRIGGERS.includes(n.type)).map(n => n.name);
    const canReach = triggers.filter(t => reachable(t).has('Meta: send private reply'));
    return canReach.length === 1 && canReach[0] === 'Webhook — approve DM';
  })());

r4.run('WF-C4', 'Park draft against a token', [{ json: draft }]);
const redeem1 = r4.run('WF-C4', 'Redeem approval token',
  [{ json: { query: { t: draft.approval_token } } }])[0].json;
check('a valid approval token sends the DM', redeem1.approved === true);
const redeem2 = r4.run('WF-C4', 'Redeem approval token',
  [{ json: { query: { t: draft.approval_token } } }])[0].json;
check('the SAME token cannot be used twice: nobody gets two DMs',
  redeem2.approved === false && redeem2.reasons.some(x => x.includes('already been used')));

const hit2 = r4.run('WF-C4', 'Match keyword + rate limit',
  [{ json: { body: payloads.wf_c4_meta_comment.instagram_keyword_hit.body } }])[0].json;
check('and the same person commenting again is rate-limited',
  hit2.matched === false && hit2.match_reasons.some(x => x.includes('already messaged')));

const touch = r4.run('WF-C4', 'Log the touch (journal)',
  [{ json: Object.assign({}, redeem1, { send_result: { ok: true, message_id: 'mid.1' } }) }])[0].json;
const touchLine = JSON.parse(touch.line);
check('the touch is journalled with the two named reasons it cannot go in campaign.touches',
  touchLine.not_in_campaign_touches_because.length === 2 &&
  touchLine.channel === 'instagram_dm');
check('an outbound DM carries no reply sentiment (the field is present and null)',
  'reply_sentiment' in touchLine && touchLine.reply_sentiment === null);
// Taxonomy decision 2026-09-06: interested, not_now, not_a_fit, referred,
// objection, unsubscribe. The superseded values must not survive anywhere.
check('no Code node in any workflow names a superseded sentiment value',
  ['WF-C1', 'WF-C2', 'WF-C3', 'WF-C4', 'WF-C5', 'WF-C6'].every(w =>
    !/\b(hot_pain|curious|endorse|unrelated|ineligible)\b/.test(JSON.stringify(wf(w)))));

section('WF-C5 · a link, never a charge');

const CFG_C5 = { ledger_url: 'https://oqpeebtwtikdzorgouxd.supabase.co',
  dovy_email: 'hello@doviloop.dev', from_email: 'bot@doviloop.dev',
  stripe_api: 'https://api.stripe.com/v1',
  price_seat_monthly: 'price_seat_TEST', price_setup_once: 'price_setup_TEST',
  success_url: 'https://doviloop.dev/welcome', cancel_url: 'https://doviloop.dev',
  usd_eur_rate: null };

const r5 = makeRunner();
r5.seed('Config', [{ json: { cfg: CFG_C5 } }]);
r5.seed('Config webhook', [{ json: { cfg: CFG_C5 } }]);

const PILOT = { id: 'pilot-1', lead_id: 'lead-1', seats: 14, started_on: '2026-09-06',
  charge_due_on: '2026-09-20', workshop_done_on: '2026-09-08', setup_done_on: null,
  leads: { company_name: 'Harbourline Accounting LLP',
           work_email: 'ruth.pell@harbourline-acc.co.uk', market: 'global' } };

const due = r5.run('WF-C5', 'Build the Stripe request', [{ json: { body: [PILOT] } }])[0].json;
check('the Stripe body is mode=subscription with seats as the quantity',
  due.stripe_form.includes('mode=subscription') &&
  due.stripe_form.includes(encodeURIComponent('line_items[0][quantity]') + '=14'));
check('the setup fee rides along as a second line item',
  due.stripe_form.includes(encodeURIComponent('line_items[1][price]') + '=price_setup_TEST'));
check('NO customer_email is ever sent, so Stripe has no address for the client at all',
  !due.stripe_form.includes('customer_email'));
check('no off_session, confirm or setup_future_usage parameter is built',
  !/off_session|(^|&)confirm=|setup_future_usage/.test(due.stripe_form));
check('the ONLY Stripe write endpoint in the whole workflow is /checkout/sessions',
  wf('WF-C5').nodes.filter(n => n.type === 'n8n-nodes-base.httpRequest' &&
      String(n.parameters.url).includes('stripe_api') && n.parameters.method === 'POST')
    .every(n => String(n.parameters.url).endsWith('/checkout/sessions')));
check('a pilot under 10 seats is refused outright',
  r5.run('WF-C5', 'Build the Stripe request',
    [{ json: { body: [Object.assign({}, PILOT, { seats: 4 })] } }])[0].json.ready === false);

r5.seed('Build the Stripe request', [{ json: due }]);
const linkMail = r5.run('WF-C5', 'Guard: the link goes to Dovy only',
  [{ json: { body: { id: 'cs_test_1', url: 'https://checkout.stripe.com/c/pay/cs_test_1' } } }])[0].json;
check('the payment link email is addressed to Dovy',
  linkMail.recipient_checked === 'hello@doviloop.dev');
check('and the body tells him to send it himself',
  linkMail.link_html.includes('<b>You send it.</b>') &&
  linkMail.link_html.includes('nothing has been sent to them'));
check('the Send node is wired to the guard\'s checked value, not a free-text address',
  nodeOf('WF-C5', 'Send: link for Dovy to send').parameters.toEmail ===
  '={{ $json.recipient_checked }}');

r5.seed('Build the Stripe request', [{ json: Object.assign({}, due,
  { cfg: Object.assign({}, CFG_C5, { dovy_email: 'ruth.pell@harbourline-acc.co.uk' }) }) }]);
let threw = false;
try {
  r5.run('WF-C5', 'Guard: the link goes to Dovy only',
    [{ json: { body: { id: 'cs_test_1', url: 'https://checkout.stripe.com/c/pay/cs_test_1' } } }]);
} catch (e) { threw = /may only send the payment link to Dovy/.test(e.message); }
check('IF THE RECIPIENT IS EVER THE CLIENT, the workflow throws and sends nothing', threw);

r5.seed('Config webhook', [{ json: { cfg: CFG_C5 } }]);
const forged = r5.run('WF-C5', 'Take only the event id',
  [{ json: { body: payloads.wf_c5_stripe.forged_no_event_id.body, headers: {} } }])[0].json;
check('a forged webhook with no real event id is ignored', forged.usable === false);
const real = r5.run('WF-C5', 'Take only the event id',
  [{ json: { body: payloads.wf_c5_stripe.checkout_completed.body, headers: {} } }])[0].json;
check('a real event id is kept, and ONLY the id is kept',
  real.usable === true && Object.keys(real).sort().join(',') ===
  'cfg,claimed_type,event_id,has_signature_header,usable');

const conv = r5.run('WF-C5', 'Apply the Stripe event',
  [{ json: { body: payloads.wf_c5_stripe.checkout_completed.body } }])[0].json;
check('a paid checkout marks the pilot converted', conv.paid === true && conv.patch.converted === true);
check('THE CURRENCY GAP: with no FX rate set, mrr_eur is left NULL rather than guessed',
  conv.mrr_eur === null && !('mrr_eur' in conv.patch) && conv.note.includes('rather than guessed'));
r5.seed('Config webhook', [{ json: { cfg: Object.assign({}, CFG_C5, { usd_eur_rate: 0.92 }) } }]);
const conv2 = r5.run('WF-C5', 'Apply the Stripe event',
  [{ json: { body: payloads.wf_c5_stripe.checkout_completed.body } }])[0].json;
check('with a rate set, 14 seats x 89 USD converts to EUR',
  conv2.mrr_eur === Math.round(14 * 89 * 0.92 * 100) / 100);
const notPaid = r5.run('WF-C5', 'Apply the Stripe event',
  [{ json: { body: payloads.wf_c5_stripe.not_a_payment.body } }])[0].json;
check('a non-payment event writes nothing', notPaid.paid === false && notPaid.patch === null);

/* =========================================================================
   WF-C6
   ========================================================================= */
section('WF-C6 · snapshot before render, and the markdown renderer');

const r6 = makeRunner();
const CFG_C6 = { ledger_url: 'https://oqpeebtwtikdzorgouxd.supabase.co',
  dovy_email: 'hello@doviloop.dev', from_email: 'bot@doviloop.dev',
  python_bin: 'python3', ledger_repo: '/opt/campaign/campaign-ledger',
  ad_engine_repo: '/opt/campaign/ad-engine', meta_graph_version: 'v21.0' };
r6.seed('Config', [{ json: { cfg: CFG_C6 } }]);

const fan = r6.run('WF-C6', 'Fan out published posts', [{ json: { body: [
  { id: 'c-en-1', natural_key: 'reel:on_camera:en:x', published_at: '2026-09-24T08:00:00Z',
    buffer_id: 'instagram=IG1;facebook=FB1;youtube_shorts=YT1;linkedin=LI1' },
  { id: 'c-da-1', natural_key: 'reel:on_camera:da:y', published_at: null, buffer_id: null },
] } }]);
const fanPosts = fan.map(i => i.json).filter(j => !j.__stats_summary);
const fanSummary = fan.map(i => i.json).find(j => j.__stats_summary);
check('the packed buffer_id is unpacked back into per-platform post ids',
  fanPosts.map(p => `${p.platform}:${p.post_id}`).join(',') ===
  'instagram:IG1,facebook:FB1,youtube_shorts:YT1');
check('LinkedIn is counted as skipped, not silently dropped',
  fanSummary.skipped_linkedin === 1);
check('unpublished content is not asked for stats', !fanPosts.some(p => p.content_id === 'c-da-1'));

r6.seed('Fan out published posts', [{ json: Object.assign({}, fanPosts[0]) }]);
const statRow = r6.run('WF-C6', 'Normalise stats row', [{ json: { body: { data: [
  { name: 'plays', values: [{ value: 4210 }] },
  { name: 'likes', values: [{ value: 96 }] },
  { name: 'saved', values: [{ value: 31 }] },
] } } }])[0].json;
check('a Meta insights response becomes exactly the content_stats columns',
  Object.keys(statRow.row).sort().join(',') ===
  'captured_on,clicks,comments,content_id,likes,platform,saves,views');
check('and every number satisfies the >= 0 CHECK constraint',
  Object.entries(statRow.row).filter(([k]) => ['views','likes','comments','saves','clicks'].includes(k))
    .every(([, v]) => Number.isInteger(v) && v >= 0));
check('a metric the platform did not report becomes 0, not a fabricated number',
  statRow.row.clicks === 0 && statRow.row.views === 4210);

r6.seed('Fan out published posts', fan);
r6.seed('Run: pull_ad_stats.py (Batch E)', [{ json: { exitCode: 0, stdout: 'wrote 3 rows' } }]);
const md = [
  '# DoviLoop campaign brief',
  '',
  'Week ending **2026-09-25**.',
  '',
  '## Three market funnel',
  '',
  '| Market | Leads | Booked |',
  '|---|---|---|',
  '| Denmark | 4 | 1 |',
  '| Lithuania | - | - |',
  '',
  '- Denmark is ahead on leads',
  '- Evidence is thin below 30',
  '',
  '---',
].join('\n');
const brief = r6.run('WF-C6', 'Markdown to HTML', [{ json: { stdout: md, stderr: '' } }])[0].json;
check('the brief renders', brief.brief_ok === true);
check('markdown tables become HTML tables', brief.brief_html.includes('<table') &&
  brief.brief_html.includes('<th align="left"'));
check('headings, bold and bullets all render',
  brief.brief_html.includes('<h1') && brief.brief_html.includes('<b>2026-09-25</b>') &&
  brief.brief_html.includes('<li'));
check('the brief\'s dash for an unknown number is preserved, not turned into a zero',
  /<td[^>]*>-<\/td>/.test(brief.brief_html));
check('the preamble reports the snapshot that ran first',
  brief.brief_html.includes('Snapshot ran first') &&
  brief.brief_html.includes('1 LinkedIn post(s) skipped'));
const failedBrief = r6.run('WF-C6', 'Markdown to HTML',
  [{ json: { stdout: '', stderr: 'CampaignDBError: missing SUPABASE_SERVICE_KEY' } }])[0].json;
check('a failed brief still emails Dovy, with the stderr and how to run it by hand',
  failedBrief.brief_ok === false &&
  failedBrief.brief_subject.includes('FAILED TO RENDER') &&
  failedBrief.brief_html.includes('SUPABASE_SERVICE_KEY'));

const c6conn = wf('WF-C6').connections;
check('ORDER: the ad pull runs only after the snapshot joins',
  c6conn['Snapshot done'].main[0][0].node === 'Run: pull_ad_stats.py (Batch E)');
check('ORDER: the brief runs only after the ad pull',
  c6conn['Run: pull_ad_stats.py (Batch E)'].main[0][0].node === 'Run: friday_brief.py (Batch B)');

/* =========================================================================
   Cross-cutting
   ========================================================================= */
section('Cross-cutting');

for (const key of ['WF-C1', 'WF-C2', 'WF-C3', 'WF-C4', 'WF-C5', 'WF-C6']) {
  check(`${key} is exported inactive`, wf(key).active === false);
}
const guardHolders = ['WF-C1', 'WF-C3', 'WF-C5', 'WF-C6'];
for (const key of guardHolders) {
  const g = wf(key).nodes.find(n => n.name === 'Guard: ledger target');
  check(`${key} refuses to run against the product project`,
    !!g && g.parameters.jsCode.includes('kngcxwcybozgqgnoweyt'));
}
const rG = makeRunner();
let guardThrew = 0;
for (const url of ['', 'https://kngcxwcybozgqgnoweyt.supabase.co', 'http://insecure.example']) {
  try { rG.run('WF-C1', 'Guard: ledger target', [{ json: { cfg: { ledger_url: url } } }]); }
  catch { guardThrew++; }
}
check('the guard throws on blank, on the product ref, and on non-https', guardThrew === 3);
check('the guard passes a real campaign URL',
  rG.run('WF-C1', 'Guard: ledger target',
    [{ json: { cfg: { ledger_url: 'https://oqpeebtwtikdzorgouxd.supabase.co' } } }]).length === 1);

console.log(`\n${pass} passed, ${fail} failed`);
if (fail) { console.log('\nfailures:'); failures.forEach(f => console.log('  - ' + f)); }
process.exit(fail ? 1 : 0);
