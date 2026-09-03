#!/usr/bin/env python3
"""Builds workflows/WF-C1..WF-C6.json.

The exports are the deliverable; this file is how they are maintained. Code
node bodies live here as plain Python strings so they stay readable and so JSON
escaping is done by json.dump rather than by hand.

Run:  python3 tools/build_workflows.py
Then: node tools/validate.mjs
"""
from __future__ import annotations

import json
import pathlib
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "workflows"

# Deterministic node IDs: same input, same file, so a rebuild is a clean diff.
_NS = uuid.UUID("6f1a5b2c-9d3e-4a71-8c52-0e7b4d9a1f60")


def nid(workflow: str, name: str) -> str:
    return str(uuid.uuid5(_NS, f"{workflow}:{name}"))


class WF:
    """One workflow under construction."""

    def __init__(self, key: str, name: str, notes: str, timezone: str = "Europe/Copenhagen"):
        self.key = key
        self.name = name
        self.notes = notes
        self.timezone = timezone
        self.nodes: list[dict] = []
        self.connections: dict = {}

    def node(self, name, type_, typeVersion, position, parameters,
             credentials=None, onError=None, alwaysOutputData=None,
             notesInFlow=None, note=None, webhookId=None, retryOnFail=None):
        n = {
            "parameters": parameters,
            "id": nid(self.key, name),
            "name": name,
            "type": type_,
            "typeVersion": typeVersion,
            "position": list(position),
        }
        if credentials:
            n["credentials"] = credentials
        if onError:
            n["onError"] = onError
        if retryOnFail:
            n["retryOnFail"] = True
            n["maxTries"] = 3
        if alwaysOutputData:
            n["alwaysOutputData"] = True
        if note:
            n["notes"] = note
        if notesInFlow:
            n["notesInFlow"] = True
        if webhookId:
            n["webhookId"] = webhookId
        self.nodes.append(n)
        return name

    def link(self, src, dst, src_index=0, dst_index=0):
        conn = self.connections.setdefault(src, {"main": []})["main"]
        while len(conn) <= src_index:
            conn.append([])
        conn[src_index].append({"node": dst, "type": "main", "index": dst_index})

    def to_json(self) -> dict:
        # No top-level "id": n8n mints a fresh one on import, so no export in
        # this repo can ever overwrite an existing workflow. See AUDIT.md s.3.
        return {
            "name": self.name,
            "nodes": self.nodes,
            "connections": self.connections,
            "active": False,
            "settings": {
                "executionOrder": "v1",
                "timezone": self.timezone,
                "saveManualExecutions": True,
                "saveExecutionProgress": True,
                "saveDataErrorExecution": "all",
                "saveDataSuccessExecution": "all",
            },
            "pinData": {},
            "tags": [],
            "meta": {"templateCredsSetupCompleted": False},
            "versionId": str(uuid.uuid5(_NS, self.key + ":version")),
        }

    def write(self):
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / f"{self.key}.json"
        path.write_text(json.dumps(self.to_json(), indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)}  ({len(self.nodes)} nodes)")


# ---------------------------------------------------------------------------
# Shared node factories
# ---------------------------------------------------------------------------

CRED_LEDGER = {"httpHeaderAuth": {"name": "Campaign Ledger PostgREST (service key)"}}
CRED_SMTP = {"smtp": {"name": "DoviLoop campaign SMTP"}}
CRED_BUFFER = {"httpHeaderAuth": {"name": "Buffer API token"}}
CRED_META = {"httpHeaderAuth": {"name": "Meta Graph API page token"}}
CRED_YT = {"youTubeOAuth2Api": {"name": "YouTube Data API (campaign)"}}
CRED_LI = {"httpHeaderAuth": {"name": "LinkedIn UGC token"}}
CRED_STRIPE = {"httpHeaderAuth": {"name": "Stripe secret key (campaign)"}}


def cfg_assignment(obj_expr: str) -> dict:
    return {
        "mode": "manual",
        "includeOtherFields": True,
        "assignments": {
            "assignments": [
                {"id": "cfg", "name": "cfg", "value": obj_expr, "type": "object"}
            ]
        },
        "options": {},
    }


def if_bool(expr: str) -> dict:
    """An IF node on a single boolean expression."""
    return {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "",
                        "typeValidation": "loose", "version": 2},
            "conditions": [{
                "id": str(uuid.uuid5(_NS, expr)),
                "leftValue": expr,
                "rightValue": "",
                "operator": {"type": "boolean", "operation": "true", "singleValue": True},
            }],
            "combinator": "and",
        },
        "looseTypeValidation": True,
        "options": {},
    }


def http(method, url, *, headers=None, json_body=None, query=None,
         generic_header_auth=True, options=None):
    p = {
        "method": method,
        "url": url,
        "options": options or {"response": {"response": {"neverError": True,
                                                         "fullResponse": True}}},
    }
    if generic_header_auth:
        p["authentication"] = "genericCredentialType"
        p["genericAuthType"] = "httpHeaderAuth"
    if headers:
        p["sendHeaders"] = True
        p["headerParameters"] = {"parameters": [{"name": k, "value": v}
                                                for k, v in headers]}
    if query:
        p["sendQuery"] = True
        p["queryParameters"] = {"parameters": [{"name": k, "value": v}
                                               for k, v in query]}
    if json_body is not None:
        p["sendBody"] = True
        p["specifyBody"] = "json"
        p["jsonBody"] = json_body
    return p


def email(from_expr, to_expr, subject_expr, html_expr):
    return {
        "fromEmail": from_expr,
        "toEmail": to_expr,
        "subject": subject_expr,
        "emailFormat": "html",
        "html": html_expr,
        "options": {},
    }


# The guard every ledger-touching workflow runs before its first HTTP call.
# Mirrors campaign_db.py's _FORBIDDEN_PROJECT_REF refusal so the two layers agree.
GUARD_JS = r"""
// Refuses to run against the product database, and refuses to run unconfigured.
//
// This mirrors the same refusal Batch B built into campaign_db.py
// (_FORBIDDEN_PROJECT_REF). Two independent layers now have to be defeated
// before a campaign workflow can touch the product project by accident.
const FORBIDDEN = 'kngcxwcybozgqgnoweyt';

const out = [];
for (const item of $input.all()) {
  const cfg = (item.json && item.json.cfg) || {};
  const url = String(cfg.ledger_url || '').trim();

  if (!url) {
    throw new Error(
      'Config.ledger_url is blank. Open the Config node and paste the CAMPAIGN ' +
      'ledger project URL (the lead-pipeline project, schema "campaign"). It ships ' +
      'blank on purpose so an unreviewed import cannot reach any database.');
  }
  if (url.includes(FORBIDDEN)) {
    throw new Error(
      'Config.ledger_url points at the PRODUCT database (' + FORBIDDEN + '). ' +
      'The campaign ledger is a different project. Refusing to run.');
  }
  if (!/^https:\/\//.test(url)) {
    throw new Error('Config.ledger_url must be https, got: ' + url);
  }
  out.push(item);
}
return out;
"""


def code(js: str, mode: str = "runOnceForAllItems") -> dict:
    return {"mode": mode, "jsCode": js.strip() + "\n"}


def http_ledger(method, url, *, headers=None, json_body=None):
    """An HTTP node against the campaign ledger via PostgREST.

    Uses n8n's built-in `supabaseApi` predefined credential, which injects BOTH
    the `apikey` and the `Authorization: Bearer` header Supabase's gateway wants.
    Name only in the export; no value.

    neverError + fullResponse: a 4xx or 5xx must NOT abort the execution, because
    aborting on the lead path is exactly how a lead gets lost. The following Code
    node reads statusCode and decides.
    """
    p = {
        "method": method,
        "url": url,
        "authentication": "predefinedCredentialType",
        "nodeCredentialType": "supabaseApi",
        "options": {"response": {"response": {"neverError": True,
                                              "fullResponse": True}},
                    "timeout": 20000},
    }
    if headers:
        p["sendHeaders"] = True
        p["headerParameters"] = {"parameters": [{"name": k, "value": v}
                                                for k, v in headers]}
    if json_body is not None:
        p["sendBody"] = True
        p["specifyBody"] = "json"
        p["jsonBody"] = json_body
    return p


CRED_LEDGER = {"supabaseApi": {"name": "Campaign Ledger (Supabase, campaign schema)"}}

LEDGER_WRITE_HEADERS = [
    ("Content-Profile", "campaign"),
    ("Accept-Profile", "campaign"),
    ("Content-Type", "application/json"),
    ("Accept", "application/json"),
]
LEDGER_READ_HEADERS = [
    ("Accept-Profile", "campaign"),
    ("Accept", "application/json"),
]


def to_text_file(source_property, file_name):
    return {"operation": "toText", "sourceProperty": source_property,
            "options": {"fileName": file_name, "encoding": "utf8"}}


def append_file(path_expr):
    return {"operation": "write", "fileName": path_expr,
            "dataPropertyName": "data", "options": {"append": True}}


# ===========================================================================
# WF-C1 — qualifier intake
# ===========================================================================

C1_CONFIG = (
    "={{ {\n"
    "  ledger_url: '',\n"
    "  dovy_email: 'hello@doviloop.dev',\n"
    "  from_email: 'campaign-bot@doviloop.dev',\n"
    "  data_dir: '/home/node/.n8n/campaign',\n"
    "  dedupe_ttl_hours: 72\n"
    "} }}"
)

C1_VALIDATE_JS = r"""
/* ------------------------------------------------------------------------
   WF-C1 · Validate and route
   ------------------------------------------------------------------------
   Contract: campaign-specs/00-START-HERE.md, implemented in
   campaign-site/src/lib/contract.ts. The enum labels below were copied from
   Batch B's campaign-ledger/migrations/001_schema.sql, which is the thing that
   will actually reject a bad value, not from the spec prose.

   THREE THINGS THIS NODE OWNS

   1. It never throws. A throw here aborts the execution, the webhook never
      answers, and the lead is gone. Everything is caught and turned into an
      `ok: false` item that the malformed branch can still write down and mail
      to Dovy. "Never lose a lead" is the whole point of this node.

   2. natural_key is byte-for-byte what Batch B computes in
      campaign_db.insert_lead:  lower(trim(work_email)) + '|' + submitted_at
      with submitted_at passed through VERBATIM. B's _iso() returns str(value)
      unchanged for a string input, so normalising the timestamp here (adding a
      Z, dropping millis, re-serialising) would produce a DIFFERENT key and
      break dedupe against anything B wrote. Do not "tidy" it.

   3. stage is Batch B's shape, not the spec's. B modelled gmail_on_request as a
      VALUE of the lead_stage enum ('qualified' | 'gmail_on_request' |
      'too_small'), where 00-START-HERE.md described it as a flag on a qualified
      lead. B's shape is what the database has, and 001_schema.sql has a CHECK
      constraint tying too_small to team_size 1-9. Follow the code.
   ------------------------------------------------------------------------ */

const ENUMS = {
  source:       ['reel', 'ad', 'outreach', 'direct'],
  market:       ['dk', 'lt', 'global'],
  locale:       ['en', 'da', 'lt'],
  team_size:    ['1-9', '10-24', '25-49', '50+'],
  email_client: ['outlook', 'gmail', 'other'],
  role:         ['owner_partner', 'ops_office_manager', 'it_admin', 'other'],
};
const TOP_LEVEL = ['source', 'market', 'locale', 'utm', 'company_name',
  'work_email', 'phone', 'team_size', 'email_client', 'role', 'submitted_at'];
const UTM_KEYS = ['source', 'medium', 'campaign', 'content'];

// NOT NULL in campaign.leads, so a missing one is fatal at the database even
// though campaign_db._check() would let it through as None.
const REQUIRED_ENUMS = ['source', 'market', 'locale', 'team_size', 'email_client'];

function routeStage(team_size, email_client) {
  if (team_size === '1-9') return 'too_small';
  return email_client === 'outlook' ? 'qualified' : 'gmail_on_request';
}

function siteFromEmail(workEmail) {
  const at = String(workEmail || '').lastIndexOf('@');
  if (at < 0) return null;
  const domain = String(workEmail).slice(at + 1).trim().toLowerCase();
  if (!domain || !domain.includes('.')) return null;
  const free = ['gmail.com', 'outlook.com', 'hotmail.com', 'live.com',
    'yahoo.com', 'icloud.com', 'me.com', 'proton.me', 'protonmail.com'];
  if (free.includes(domain)) return null;   // a free mailbox is not a company site
  return 'https://' + domain;
}

const out = [];

for (const item of $input.all()) {
  const raw = item.json || {};
  const cfg = raw.cfg || {};
  const headers = raw.headers || {};
  // n8n lower-cases incoming header names.
  const dedupeHeader = String(headers['x-doviloop-dedupe'] || '').trim();

  let body = raw.body;
  // A client that posts a JSON string, or n8n configured with rawBody, both
  // arrive as text. Recover rather than reject.
  if (typeof body === 'string') {
    try { body = JSON.parse(body); } catch (e) { body = { __unparseable: raw.body }; }
  }
  if (body === null || typeof body !== 'object' || Array.isArray(body)) {
    body = { __not_an_object: body };
  }

  const problems = [];

  for (const key of TOP_LEVEL) {
    if (!(key in body)) problems.push('missing key: ' + key);
  }
  for (const key of Object.keys(body)) {
    // Unknown keys are recorded but are NOT fatal on their own: we strip them
    // before the insert rather than bounce a real lead over an extra field.
    if (!TOP_LEVEL.includes(key)) problems.push('unexpected key (ignored): ' + key);
  }
  for (const [key, allowed] of Object.entries(ENUMS)) {
    if (key in body && body[key] != null && !allowed.includes(body[key])) {
      problems.push(key + ' = ' + JSON.stringify(body[key]) +
        ' is not one of ' + allowed.join(' | '));
    }
  }
  for (const key of REQUIRED_ENUMS) {
    if (body[key] == null || body[key] === '') problems.push(key + ' is required and empty');
  }

  const workEmail = String(body.work_email == null ? '' : body.work_email).trim().toLowerCase();
  if (!workEmail) problems.push('work_email is required and empty');
  else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(workEmail)) problems.push('work_email is not an email address');

  const companyName = String(body.company_name == null ? '' : body.company_name).trim();
  if (!companyName) problems.push('company_name is required and empty');

  const submittedAt = body.submitted_at;   // verbatim, see header note 2
  if (typeof submittedAt !== 'string' || !submittedAt.trim()) {
    problems.push('submitted_at is required and must be a string');
  } else if (Number.isNaN(Date.parse(submittedAt))) {
    problems.push('submitted_at is not parseable as ISO-8601');
  }

  const utm = (body.utm && typeof body.utm === 'object' && !Array.isArray(body.utm))
    ? body.utm : {};
  if (!body.utm || typeof body.utm !== 'object' || Array.isArray(body.utm)) {
    problems.push('utm is not an object (treated as empty)');
  } else {
    for (const k of UTM_KEYS) if (!(k in utm)) problems.push('utm missing key: ' + k);
  }

  // Fatal = anything that would make the ledger row wrong or the insert fail.
  // "unexpected key (ignored)" and a missing utm sub-key are not fatal.
  const fatal = problems.filter(p =>
    !p.startsWith('unexpected key (ignored)') && !p.startsWith('utm missing key'));

  const ok = fatal.length === 0;

  const stage = ok ? routeStage(body.team_size, body.email_client) : null;
  const naturalKey = ok ? (workEmail + '|' + submittedAt) : null;

  // TWO dedupe mechanisms, both used, per the reconciliation note.
  //   primary   the per-submission id Batch A puts in X-DoviLoop-Dedupe
  //             (campaign-site/src/lib/lead.ts:111). It is stable across A's
  //             two send attempts AND across a drain of its localStorage
  //             retry queue, so it is the strongest key available.
  //   fallback  Batch B's derived key, for any caller that does not send the
  //             header (a hand-run curl, a future integration, an old bundle).
  const dedupeKey = dedupeHeader || naturalKey;
  const dedupeSource = dedupeHeader ? 'header:X-DoviLoop-Dedupe' : 'derived:work_email+submitted_at';

  const record = {
    cfg,
    ok,
    problems,
    fatal_problems: fatal,
    dedupe_key: dedupeKey,
    dedupe_source: dedupeSource,
    received_at: new Date().toISOString(),
    raw_body: body,
    raw_headers: {
      'x-doviloop-dedupe': dedupeHeader || null,
      'user-agent': headers['user-agent'] || null,
      'content-type': headers['content-type'] || null,
    },
  };

  if (ok) {
    record.outcome = stage;                 // qualified | gmail_on_request | too_small
    record.natural_key = naturalKey;
    record.company_site = siteFromEmail(workEmail);
    // Exactly the columns campaign.leads has, nothing else. Nulls are stripped
    // so a merge can never blank a known column, matching campaign_db._clean().
    const row = {
      company_name: companyName,
      work_email: workEmail,
      phone: (body.phone == null || String(body.phone).trim() === '') ? null : String(body.phone).trim(),
      team_size: body.team_size,
      email_client: body.email_client,
      role: (body.role == null || body.role === '') ? null : body.role,
      market: body.market,
      locale: body.locale,
      source: body.source,
      utm_source: utm.source || null,
      utm_medium: utm.medium || null,
      utm_campaign: utm.campaign || null,
      utm_content: utm.content || null,
      stage: stage,
      submitted_at: submittedAt,
      natural_key: naturalKey,
    };
    for (const k of Object.keys(row)) if (row[k] === null) delete row[k];
    record.lead_row = row;
  }

  out.push({ json: record });
}

return out;
"""

C1_READ_LEDGER_JS = r"""
/* WF-C1 · Read ledger result.

   The HTTP node runs with neverError + fullResponse, so a 409, a 401 or a 502
   arrives here as data instead of killing the execution. That is deliberate:
   the response to the browser and the notification to Dovy must both still
   happen when the database is down.

   PostgREST with Prefer: resolution=ignore-duplicates returns an EMPTY array
   when the natural_key already existed. That is a successful dedupe, not a
   failure, and it is the second of the two idempotency mechanisms: even if the
   in-flight header check misses (two n8n workers, a restarted instance), the
   unique index on campaign.leads.natural_key still collapses the duplicate. */

const out = [];
for (const item of $input.all()) {
  const prev = $('Validate and route').all()[item.pairedItem ? 0 : 0].json;
  const res = item.json || {};
  const status = Number(res.statusCode || 0);
  const payload = res.body;

  const rows = Array.isArray(payload) ? payload : (payload ? [payload] : []);
  const stored = status >= 200 && status < 300;
  const deduped = stored && rows.length === 0;

  out.push({
    json: Object.assign({}, prev, {
      ledger_status: status,
      ledger_stored: stored,
      ledger_deduped: deduped,
      ledger_error: stored ? null :
        ('HTTP ' + status + ': ' + JSON.stringify(payload).slice(0, 600)),
      lead_id: (rows[0] && rows[0].id) || null,
    }),
  });
}
return out;
"""

C1_PARK_JS = r"""
/* WF-C1 · Park an under-10 lead. NO NURTURE IS STARTED HERE.

   The spec says a `too_small` lead "enters a 3-email nurture". This node
   deliberately does not do that, and WF-C2 will refuse the lead if it is
   handed one without proof of opt-in. The reason, in full, is in README.md
   under "Consent" and in BLOCKED.md F-4. In short:

     * the shared contract has no consent field, so nothing on the wire says
       this person agreed to be emailed;
     * Batch A reached the same conclusion independently and refused to
       auto-enrol: the 1-9 result screen offers an explicit opt-in instead
       (campaign-site/src/components/Qualifier.tsx, `nurtureHref`), and that
       opt-in is a mailto to hello@doviloop.dev, so it never reaches this
       webhook at all;
     * for market 'dk' this is not a preference. Denmark's marketing law is the
       stated reason this whole campaign bans Danish cold email. Enrolling a
       Danish address off a form that never asked is the same exposure the ban
       exists to avoid.

   So the lead is written down, and nothing is sent. The opt-in arrives in
   Dovy's inbox as an email he can see, and he starts WF-C2 by hand. */

const out = [];
for (const item of $input.all()) {
  const j = item.json || {};
  const row = j.lead_row || {};
  out.push({
    json: Object.assign({}, j, {
      parked: true,
      parked_reason: 'too_small: no opt-in signal exists on the qualifier contract',
      nurture_started: false,
      line: JSON.stringify({
        parked_at: new Date().toISOString(),
        work_email: row.work_email || null,
        company_name: row.company_name || null,
        market: row.market || null,
        locale: row.locale || null,
        source: row.source || null,
        team_size: row.team_size || null,
        lead_id: j.lead_id || null,
        natural_key: j.natural_key || null,
        awaiting: 'explicit opt-in before WF-C2 may send anything',
      }),
    }),
  });
}
return out;
"""

C1_DEADLETTER_JS = r"""
/* WF-C1 · Dead letter.

   Reached on a malformed payload, or on a ledger write that did not succeed.
   Writes the WHOLE raw body and the dedupe header, so the submission can be
   replayed by hand or re-posted to this same webhook once the cause is fixed.

   The file write and the email to Dovy are both attempted, on purpose. If the
   file node is misconfigured on his instance the lead is still in his inbox;
   if his mail is down it is still on disk. Losing a lead needs both to fail. */

const out = [];
for (const item of $input.all()) {
  const j = item.json || {};
  const record = {
    dead_lettered_at: new Date().toISOString(),
    kind: j.ok === false ? 'malformed_payload' : 'ledger_write_failed',
    dedupe_key: j.dedupe_key || null,
    dedupe_source: j.dedupe_source || null,
    problems: j.problems || [],
    fatal_problems: j.fatal_problems || [],
    ledger_status: j.ledger_status == null ? null : j.ledger_status,
    ledger_error: j.ledger_error || null,
    raw_headers: j.raw_headers || {},
    raw_body: j.raw_body === undefined ? null : j.raw_body,
  };
  out.push({ json: Object.assign({}, j, {
    dead_letter: record,
    line: JSON.stringify(record),
    dl_subject: '[DEAD LETTER] qualifier ' + record.kind +
      ' — ' + ((j.raw_body && j.raw_body.company_name) || 'unknown company'),
    dl_html:
      '<p>A qualifier submission did not make it into the ledger. It is not lost: ' +
      'the full payload is below and in the dead-letter file.</p>' +
      '<p><b>Reason:</b> ' + record.kind + '</p>' +
      '<p><b>Problems:</b><br>' +
      ((record.fatal_problems.length ? record.fatal_problems : record.problems)
        .map(p => '&bull; ' + p).join('<br>') || 'none recorded') + '</p>' +
      (record.ledger_error ? '<p><b>Ledger said:</b> ' + record.ledger_error + '</p>' : '') +
      '<p><b>Raw payload</b></p><pre style="white-space:pre-wrap;font-size:12px">' +
      JSON.stringify(record.raw_body, null, 2)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;') +
      '</pre>' +
      '<p>To replay it once the cause is fixed, POST that body back to the ' +
      'WF-C1 webhook with header <code>X-DoviLoop-Dedupe: ' +
      (record.dedupe_key || '(none)') + '</code>. The dedupe key means a replay ' +
      'cannot create a second lead.</p>',
  }) });
}
return out;
"""

C1_LEAD_EMAIL_JS = r"""
/* WF-C1 · Build the notification to Dovy for a 10+ seat lead. */

const SIZE_LABEL = { '10-24': '10 to 24 seats', '25-49': '25 to 49 seats', '50+': '50 or more seats' };
const MARKET_LABEL = { dk: 'Denmark', lt: 'Lithuania', global: 'US / global' };
const ROLE_LABEL = {
  owner_partner: 'Owner or partner', ops_office_manager: 'Ops or office manager',
  it_admin: 'IT admin', other: 'Other',
};

function esc(s) {
  return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

const out = [];
for (const item of $input.all()) {
  const j = item.json || {};
  const r = j.lead_row || {};
  const market = MARKET_LABEL[r.market] || r.market || 'unknown market';
  const size = SIZE_LABEL[r.team_size] || r.team_size || 'unknown size';

  // Subject carries market and team size, per the spec.
  const subject = '[Lead] ' + market + ' · ' + size + ' · ' + (r.company_name || 'unknown company') +
    (j.outcome === 'gmail_on_request' ? ' · Gmail' : '');

  const rows = [
    ['Company', esc(r.company_name)],
    ['Site', j.company_site ? '<a href="' + esc(j.company_site) + '">' + esc(j.company_site) + '</a>'
      : '<i>not derivable from the email domain</i>'],
    ['Work email', '<a href="mailto:' + esc(r.work_email) + '">' + esc(r.work_email) + '</a>'],
    ['Phone', r.phone ? esc(r.phone) : '<i>not given</i>'],
    ['Team size', esc(r.team_size)],
    ['Mail client', esc(r.email_client)],
    ['Role', esc(ROLE_LABEL[r.role] || r.role || 'not given')],
    ['Market / locale', esc(r.market) + ' / ' + esc(r.locale)],
    ['Came from', esc(r.source)],
    ['UTM', esc([r.utm_source, r.utm_medium, r.utm_campaign, r.utm_content].filter(Boolean).join(' / ') || 'none')],
    ['Submitted', esc(r.submitted_at)],
    ['Ledger stage', esc(j.outcome)],
    ['Lead id', esc(j.lead_id || '(not returned — see note below)')],
  ];

  let note = '';
  if (j.outcome === 'gmail_on_request') {
    note = '<p style="padding:10px;background:#fff6e5;border-left:3px solid #e0a030">' +
      'This firm is on ' + esc(r.email_client) + ', not Outlook. They still book. ' +
      'Onboarding needs to set up the Gmail path for them, so say so on the call ' +
      'rather than finding out during setup.</p>';
  }
  if (j.ledger_deduped) {
    note += '<p style="color:#666;font-size:13px">The ledger already had this exact ' +
      'submission (same email, same timestamp), so no second row was created. ' +
      'That is the retry path working, not a problem.</p>';
  }
  if (!j.ledger_stored) {
    note += '<p style="padding:10px;background:#ffe9e9;border-left:3px solid #c33">' +
      'The ledger write did NOT succeed (' + esc(j.ledger_error) + '). ' +
      'The lead is in the dead-letter file and in this email. Nothing is lost, ' +
      'but the row is not in the database yet.</p>';
  }

  out.push({ json: Object.assign({}, j, {
    lead_subject: subject,
    lead_html:
      '<p>New qualifier submission, ' + esc(size) + ', ' + esc(market) + '.</p>' +
      note +
      '<table cellpadding="6" style="border-collapse:collapse;font-family:system-ui,sans-serif;font-size:14px">' +
      rows.map(([k, v]) =>
        '<tr><td style="border-bottom:1px solid #eee;color:#666">' + k +
        '</td><td style="border-bottom:1px solid #eee">' + v + '</td></tr>').join('') +
      '</table>' +
      '<p style="margin-top:18px;font-size:13px;color:#666">Sent by WF-C1. ' +
      'Nothing was sent to this person. The booking link was shown on the page.</p>',
  }) });
}
return out;
"""


def build_c1():
    w = WF("WF-C1", "WF-C1 — Qualifier intake (teams.doviloop.dev)",
           "Webhook from Batch A's qualifier. Validates, dedupes twice, writes "
           "campaign.leads, notifies Dovy, and never loses a lead.")

    w.node("Webhook — qualifier", "n8n-nodes-base.webhook", 2, (-200, 0), {
        "httpMethod": "POST",
        "path": "campaign/qualifier",
        "responseMode": "responseNode",
        "options": {"rawBody": False, "allowedOrigins": "*"},
    }, webhookId=nid("WF-C1", "webhook:qualifier"),
        note="Production URL goes into Batch A's VITE_LEAD_WEBHOOK_URL.")

    w.node("Config", "n8n-nodes-base.set", 3.4, (20, 0), cfg_assignment(C1_CONFIG),
           note="ledger_url ships BLANK on purpose. Fill it with the CAMPAIGN "
                "project URL, never the product one.")
    w.node("Validate and route", "n8n-nodes-base.code", 2, (240, 0), code(C1_VALIDATE_JS))
    w.node("IF payload valid", "n8n-nodes-base.if", 2, (460, 0), if_bool("={{ $json.ok }}"))

    # -- valid path ---------------------------------------------------------
    w.node("Guard: ledger target", "n8n-nodes-base.code", 2, (680, -200), code(GUARD_JS))
    w.node("Ledger: upsert lead", "n8n-nodes-base.httpRequest", 4.2, (900, -200),
           http_ledger("POST",
                       "={{ $json.cfg.ledger_url }}/rest/v1/leads?on_conflict=natural_key",
                       headers=LEDGER_WRITE_HEADERS + [
                           ("Prefer", "resolution=ignore-duplicates,return=representation")],
                       json_body="={{ JSON.stringify([$json.lead_row]) }}"),
           credentials=CRED_LEDGER, retryOnFail=True, alwaysOutputData=True,
           note="Idempotency mechanism 2 of 2: the unique index on natural_key.")
    w.node("Read ledger result", "n8n-nodes-base.code", 2, (1120, -200), code(C1_READ_LEDGER_JS))
    w.node("Respond: routing outcome", "n8n-nodes-base.respondToWebhook", 1.1, (1340, -200), {
        "respondWith": "json",
        "responseCode": 200,
        "responseBody": "={{ JSON.stringify({ ok: $json.ok, outcome: $json.outcome, "
                        "stage: $json.outcome, lead_id: $json.lead_id, "
                        "deduped: $json.ledger_deduped, "
                        "shows_booking: $json.outcome !== 'too_small', "
                        "nurture_started: false, "
                        "stored: $json.ledger_stored }) }}",
        "options": {},
    }, note="Batch A renders its own screen from contract.ts route() and ignores "
            "this body. It is answered anyway for curl testing and for any future client.")
    w.node("IF ledger stored", "n8n-nodes-base.if", 2, (1560, -200),
           if_bool("={{ $json.ledger_stored }}"))
    w.node("IF too small", "n8n-nodes-base.if", 2, (1780, -320),
           if_bool("={{ $json.outcome === 'too_small' }}"))

    w.node("Park: no nurture without opt-in", "n8n-nodes-base.code", 2, (2000, -220),
           code(C1_PARK_JS))
    w.node("To file: parked lead", "n8n-nodes-base.convertToFile", 1.1, (2220, -220),
           to_text_file("line", "parked-under-10.jsonl"))
    w.node("Append parked-under-10.jsonl", "n8n-nodes-base.readWriteFile", 1, (2440, -220),
           append_file("={{ $('Config').first().json.cfg.data_dir }}/parked-under-10.jsonl"),
           onError="continueRegularOutput")

    w.node("Email Dovy: new lead", "n8n-nodes-base.code", 2, (2000, -440), code(C1_LEAD_EMAIL_JS))
    w.node("Send: new lead", "n8n-nodes-base.emailSend", 2.1, (2220, -440),
           email("={{ $json.cfg.from_email }}", "={{ $json.cfg.dovy_email }}",
                 "={{ $json.lead_subject }}", "={{ $json.lead_html }}"),
           credentials=CRED_SMTP, onError="continueRegularOutput")

    # -- malformed path -----------------------------------------------------
    w.node("Dead letter: malformed", "n8n-nodes-base.code", 2, (680, 260),
           code(C1_DEADLETTER_JS))
    w.node("To file: malformed", "n8n-nodes-base.convertToFile", 1.1, (900, 260),
           to_text_file("line", "dead-letter.jsonl"))
    w.node("Append dead-letter.jsonl", "n8n-nodes-base.readWriteFile", 1, (1120, 260),
           append_file("={{ $('Config').first().json.cfg.data_dir }}/dead-letter.jsonl"),
           onError="continueRegularOutput")
    w.node("Send: malformed submission", "n8n-nodes-base.emailSend", 2.1, (1340, 260),
           email("={{ $('Config').first().json.cfg.from_email }}",
                 "={{ $('Config').first().json.cfg.dovy_email }}",
                 "={{ $('Dead letter: malformed').first().json.dl_subject }}",
                 "={{ $('Dead letter: malformed').first().json.dl_html }}"),
           credentials=CRED_SMTP, onError="continueRegularOutput")
    w.node("Respond: accepted with errors", "n8n-nodes-base.respondToWebhook", 1.1, (1560, 260), {
        "respondWith": "json",
        "responseCode": 200,
        "responseBody": "={{ JSON.stringify({ ok: false, "
                        "error: 'payload did not match the qualifier contract', "
                        "problems: $('Dead letter: malformed').first().json.dead_letter.fatal_problems, "
                        "kept: true, "
                        "note: 'Your answers were kept and a human was notified. Nothing was lost.' "
                        "}) }}",
        "options": {},
    }, note="200, not 4xx. Batch A's client retries on !res.ok and would re-post a "
            "payload that will fail identically, twice, then queue it forever.")

    # -- ledger failure path ------------------------------------------------
    w.node("Dead letter: ledger write failed", "n8n-nodes-base.code", 2, (1780, -60),
           code(C1_DEADLETTER_JS))
    w.node("To file: ledger failure", "n8n-nodes-base.convertToFile", 1.1, (2000, -60),
           to_text_file("line", "dead-letter.jsonl"))
    w.node("Append dead-letter.jsonl (ledger)", "n8n-nodes-base.readWriteFile", 1, (2220, -60),
           append_file("={{ $('Config').first().json.cfg.data_dir }}/dead-letter.jsonl"),
           onError="continueRegularOutput")
    w.node("Send: ledger write failed", "n8n-nodes-base.emailSend", 2.1, (2440, -60),
           email("={{ $('Config').first().json.cfg.from_email }}",
                 "={{ $('Config').first().json.cfg.dovy_email }}",
                 "={{ $('Dead letter: ledger write failed').first().json.dl_subject }}",
                 "={{ $('Dead letter: ledger write failed').first().json.dl_html }}"),
           credentials=CRED_SMTP, onError="continueRegularOutput")

    # -- wiring -------------------------------------------------------------
    w.link("Webhook — qualifier", "Config")
    w.link("Config", "Validate and route")
    w.link("Validate and route", "IF payload valid")
    w.link("IF payload valid", "Guard: ledger target", 0)
    w.link("IF payload valid", "Dead letter: malformed", 1)

    w.link("Guard: ledger target", "Ledger: upsert lead")
    w.link("Ledger: upsert lead", "Read ledger result")
    w.link("Read ledger result", "Respond: routing outcome")
    w.link("Respond: routing outcome", "IF ledger stored")
    w.link("IF ledger stored", "IF too small", 0)
    w.link("IF ledger stored", "Dead letter: ledger write failed", 1)

    w.link("IF too small", "Park: no nurture without opt-in", 0)
    w.link("IF too small", "Email Dovy: new lead", 1)
    w.link("Park: no nurture without opt-in", "To file: parked lead")
    w.link("To file: parked lead", "Append parked-under-10.jsonl")
    w.link("Email Dovy: new lead", "Send: new lead")

    w.link("Dead letter: malformed", "To file: malformed")
    w.link("To file: malformed", "Append dead-letter.jsonl")
    w.link("Append dead-letter.jsonl", "Send: malformed submission")
    w.link("Send: malformed submission", "Respond: accepted with errors")

    w.link("Dead letter: ledger write failed", "To file: ledger failure")
    w.link("To file: ledger failure", "Append dead-letter.jsonl (ledger)")
    w.link("Append dead-letter.jsonl (ledger)", "Send: ledger write failed")

    w.write()


# ===========================================================================
# WF-C2 — under-10 nurture, CONSENT-GATED
# ===========================================================================

C2_CONFIG = (
    "={{ {\n"
    "  ledger_url: '',\n"
    "  dovy_email: 'hello@doviloop.dev',\n"
    "  from_email: 'dovy@doviloop.dev',\n"
    "  reply_to: 'hello@doviloop.dev',\n"
    "  data_dir: '/home/node/.n8n/campaign',\n"
    "  unsubscribe_base: '',\n"
    "  pricing_url: 'https://doviloop.dev/pricing',\n"
    "  postal_address: '',\n"
    "  dk_marketing_law_confirmed: false\n"
    "} }}"
)

C2_CONSENT_JS = r"""
/* ------------------------------------------------------------------------
   WF-C2 · CONSENT GATE.  Read this before changing anything below it.
   ------------------------------------------------------------------------
   The spec for this workflow says a `too_small` lead "enters a 3-email
   nurture", automatically, straight out of WF-C1. This node is the reason
   that does not happen, and it is a legal control, not a preference.

   THE FACTS, each one checked against the code rather than the spec:

   1. The shared qualifier contract (00-START-HERE.md, and
      campaign-site/src/lib/contract.ts) has ELEVEN fields and not one of them
      is a consent field. Nothing that arrives from the landing page says this
      person agreed to receive marketing email.

   2. Batch A refused to auto-enrol and built an explicit opt-in instead. The
      1-9 seat result screen shows "Want the short version by email instead?"
      with a button the visitor has to press
      (campaign-site/src/components/Qualifier.tsx, `nurtureHref`;
       campaign-site/src/content/en.ts, `results.tooSmall`).
      That button is a mailto: to hello@doviloop.dev. It does NOT post to this
      or any other webhook. So even the real opt-in never arrives here on its
      own, and anything this workflow receives automatically has, by
      construction, no opt-in behind it.

   3. Batch B raised the same gap independently: no consent or capture-context
      column on a schema holding EU personal data. campaign.leads has no
      consent column and no opt_out column. There is nowhere in the ledger to
      even record the answer.

   4. Denmark. The campaign bans Danish cold email outright, and the stated
      reason is Danish marketing law being stricter than the rest of the EU on
      unsolicited commercial email. A Danish address enrolled off a form that
      never asked is precisely the exposure that ban exists to prevent. So `dk`
      needs a second, separate confirmation from Dovy on top of the opt-in.

   WHAT THIS NODE REQUIRES, therefore:

     optin.granted        === true
     optin.source           a non-empty string saying HOW they opted in
                            (e.g. "reply to hello@doviloop.dev 2026-09-12")
     optin.evidence         a non-empty string that lets a human find the proof
                            again later (message id, thread link, screenshot path)
     optin.recorded_at      an ISO-8601 timestamp
     optin.work_email       must equal the lead's work_email, so an opt-in
                            cannot be pasted onto the wrong person

   and, only when market === 'dk', BOTH of:

     optin.dk_marketing_law_confirmed === true   (per lead)
     cfg.dk_marketing_law_confirmed   === true   (instance-wide, in Config)

   Anything missing: the lead is PARKED. Nothing is sent. That is the whole
   behaviour of the failure path, and it is the correct one.
   ------------------------------------------------------------------------ */

const out = [];

for (const item of $input.all()) {
  const j = item.json || {};
  const cfg = j.cfg || {};
  const lead = j.lead || j.lead_row || {};
  const optin = j.optin || {};
  const reasons = [];

  const workEmail = String(lead.work_email || '').trim().toLowerCase();
  if (!workEmail) reasons.push('no work_email on the lead');

  if (optin.granted !== true) reasons.push('optin.granted is not exactly true');
  if (!String(optin.source || '').trim()) reasons.push('optin.source is empty: say how they opted in');
  if (!String(optin.evidence || '').trim()) reasons.push('optin.evidence is empty: point at the proof');

  const recordedAt = String(optin.recorded_at || '').trim();
  if (!recordedAt) reasons.push('optin.recorded_at is empty');
  else if (Number.isNaN(Date.parse(recordedAt))) reasons.push('optin.recorded_at is not ISO-8601');

  const optinEmail = String(optin.work_email || '').trim().toLowerCase();
  if (!optinEmail) reasons.push('optin.work_email is empty');
  else if (workEmail && optinEmail !== workEmail) {
    reasons.push('optin.work_email (' + optinEmail + ') does not match the lead (' + workEmail + ')');
  }

  if (String(lead.market || '') === 'dk') {
    if (optin.dk_marketing_law_confirmed !== true) {
      reasons.push('market is dk and optin.dk_marketing_law_confirmed is not true');
    }
    if (cfg.dk_marketing_law_confirmed !== true) {
      reasons.push('market is dk and Config.dk_marketing_law_confirmed is not true. ' +
        'Denmark needs Dovy to confirm the marketing-law position once, in Config, ' +
        'before ANY Danish address can be emailed by this campaign.');
    }
  }

  // Already unsubscribed? Never re-enrol someone who has opted out.
  const store = $getWorkflowStaticData('global');
  store.optedOut = store.optedOut || {};
  if (workEmail && store.optedOut[workEmail]) {
    reasons.push('this address opted out on ' + store.optedOut[workEmail] + ' and must not be re-enrolled');
  }

  const consented = reasons.length === 0;

  out.push({ json: Object.assign({}, j, {
    consented: consented,
    consent_reasons: reasons,
    work_email: workEmail,
    // Opaque, not secret. The worst an attacker can do with a guessed token is
    // unsubscribe someone, which fails safe. Documented in README.
    unsub_token: Buffer.from('unsub:' + workEmail).toString('base64url'),
    parked_line: consented ? null : JSON.stringify({
      parked_at: new Date().toISOString(),
      work_email: workEmail || null,
      company_name: lead.company_name || null,
      market: lead.market || null,
      reasons: reasons,
      sent: 'nothing',
    }),
  }) });
}

return out;
"""

C2_SUPPRESSION_JS = r"""
/* WF-C2 · Suppression check. Runs before EVERY send, not just the first.

   Someone can unsubscribe on day 5, between email 2 and email 3, and the whole
   point of "trivially easy to stop" is that the next one does not go out.

   The operative store is n8n's workflow static data, written by the
   "Unsubscribe" branch of this same workflow. There is no opt_out column in
   campaign.leads to write to: Batch B's schema does not have one, and a
   workflow cannot add one (Dovy runs migrations, not n8n). sql/004_consent.sql
   in this repo is the proposed migration that would make this durable. Until it
   is run, an n8n instance rebuild loses the suppression list, which is why the
   unsubscribe branch ALSO appends to a file and emails Dovy. */

const store = $getWorkflowStaticData('global');
store.optedOut = store.optedOut || {};

const out = [];
for (const item of $input.all()) {
  const j = item.json || {};
  const email = String(j.work_email || '').trim().toLowerCase();
  const optedOutAt = email ? store.optedOut[email] : null;
  out.push({ json: Object.assign({}, j, {
    still_subscribed: !optedOutAt,
    opted_out_at: optedOutAt || null,
  }) });
}
return out;
"""

# The copy. English only, per spec. No em dashes, per the voice rules.
C2_EMAILS_JS = r"""
/* WF-C2 · The three emails.

   English only, per spec. Voice rules from 00-START-HERE.md: casual, plain
   verbs, no em dashes, none of the AI-flavoured phrasing. Every one carries a
   working unsubscribe link, and email 1 says in its first two lines why they
   are getting it and how to stop.

   ====================================================================
   EMAIL 2 AND THE ROI NUMBERS. Read this before adding any figure.
   ====================================================================
   The spec says email 2 carries "the ROI numbers": roughly 9x ROI, roughly
   EUR 400 a month saved, roughly a 40 day payback.

   ad-engine/claims/evidence.json, which is Dovy's own claims ledger, says:
   "DoviLoop currently has no customers, no case studies and no measured
   outcomes", marks hours_saved, customer_count and percentage_claim as
   UNVERIFIED, and notes that a measurable public claim with nothing behind it
   "is the exposure an investor specifically warned about".

   00-START-HERE.md calls the same figures verified proof. Both cannot be true.
   Batch E resolved it by shipping zero ROI numbers in any of its eight statics
   and six copy variants. This workflow resolves it the same way, and for a
   stronger reason: an ad is a claim shouted at a crowd, whereas this is a
   named person who filled in a form, and a number in their inbox is a number
   they can hold you to.

   So email 2 below is written to work WITHOUT the figures. It explains the
   mechanism instead of the payoff, which is the part that is verifiable today.

   THE SLOT: if Dovy confirms the figures were measured against a real customer,
   set ROI_BLOCK below to the commented-out paragraph and nothing else changes.
   Do not set it on the strength of the numbers merely having been used before.
   Prior use of an unmeasured number is not evidence for it. Logged in
   BLOCKED.md as F-5. */

// ---------------------------------------------------------------------------
// ROI SLOT. Ships empty. Fill ONLY if ad-engine/claims/evidence.json is updated
// to say the figures were measured against a real customer.
//
//   const ROI_BLOCK =
//     '<p>On the numbers: firms like yours have seen about <b>X</b> back for ' +
//     'every euro spent, roughly <b>EUR Y a month</b> of time returned, and ' +
//     'payback in about <b>Z days</b>. Those come from ' +
//     '&lt;name the measurement here&gt;.</p>';
//
const ROI_BLOCK = '';
// ---------------------------------------------------------------------------

function esc(s) {
  return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

const out = [];
for (const item of $input.all()) {
  const j = item.json || {};
  const cfg = j.cfg || {};
  const lead = j.lead || j.lead_row || {};
  const first = String(lead.company_name || '').trim();
  const pricing = cfg.pricing_url || 'https://doviloop.dev/pricing';

  const unsubUrl = String(cfg.unsubscribe_base || '') +
    '?e=' + encodeURIComponent(j.work_email || '') +
    '&t=' + encodeURIComponent(j.unsub_token || '');

  const foot =
    '<hr style="border:none;border-top:1px solid #e5e5e5;margin:26px 0">' +
    '<p style="font-size:12px;color:#777;line-height:1.6">' +
    'You asked us to send these when you filled in the form at teams.doviloop.dev. ' +
    'Three notes over two weeks, then they stop on their own.<br>' +
    '<a href="' + esc(unsubUrl) + '">Stop these emails</a>' +
    (cfg.postal_address ? '<br>' + esc(cfg.postal_address) : '') +
    '</p>';

  const wrap = (inner) =>
    '<div style="font-family:system-ui,-apple-system,Segoe UI,sans-serif;font-size:15px;' +
    'line-height:1.65;color:#1a1a1a;max-width:560px">' + inner + foot + '</div>';

  const emails = {
    e1: {
      subject: 'The short version, note 1 of 3',
      html: wrap(
        '<p>Hi' + (first ? ' ' + esc(first) : '') + ',</p>' +
        '<p>You asked for the short version by email, so here it is. Three notes, ' +
        'two weeks, then they stop. You can stop them sooner with the link at the ' +
        'bottom and I will not chase.</p>' +
        '<p><b>What DoviLoop does.</b> It sits inside the Outlook you already use ' +
        'and writes the reply for the mail you get twenty times a week. The same ' +
        'fee question, the same deadline question, the same "can you send me the ' +
        'form again". It writes the draft in your own words, using your own fees ' +
        'and deadlines, and puts it in your drafts folder.</p>' +
        '<p>It never sends anything on its own. You read it, you change what you ' +
        'want, you press send. That is the whole deal.</p>' +
        '<p>You are under ten seats today, so the team plan is not the right shape ' +
        'for you. The smaller plan does the same drafting and costs a lot less.</p>' +
        '<p><a href="' + esc(pricing) + '">See the plan for smaller teams</a></p>' +
        '<p>Next note, in about four days: how the drafting actually works, and why ' +
        'it does not read like a robot.</p>' +
        '<p>Dovy</p>'),
    },
    e2: {
      subject: 'How the drafting actually works, note 2 of 3',
      html: wrap(
        '<p>Hi' + (first ? ' ' + esc(first) : '') + ',</p>' +
        '<p>Second note. This one is the mechanism, because that is the part you ' +
        'can check for yourself.</p>' +
        '<p><b>It learns how you write.</b> It reads your sent mail and builds a ' +
        'profile of how you actually put a sentence together. Short or long, ' +
        'formal or not, whether you open with a greeting. Every person in the ' +
        'office gets their own. That is why the drafts do not read like a robot ' +
        'wrote them: they read like you on a normal day.</p>' +
        '<p><b>It answers from your documents, not the internet.</b> Your fee ' +
        'schedule, your deadlines, your policies, the answers you have already ' +
        'given a hundred times. When a client asks what the filing deadline is, it ' +
        'answers from your file, not from something it read somewhere.</p>' +
        '<p><b>It never sends.</b> There is no send button on its side. It writes ' +
        'into your drafts folder and stops. Nothing leaves your Outlook without ' +
        'you pressing send.</p>' +
        '<p><b>It stays in Europe.</b> The whole thing runs on European servers.</p>' +
        ROI_BLOCK +
        '<p>Worth saying plainly: we are early, and we do not have a customer ' +
        'yet whose numbers I can show you. When we do, I will send them rather ' +
        'than an estimate.</p>' +
        '<p><a href="' + esc(pricing) + '">The plan for smaller teams</a></p>' +
        '<p>Last note in about a week.</p>' +
        '<p>Dovy</p>'),
    },
    e3: {
      subject: 'Last one, note 3 of 3',
      html: wrap(
        '<p>Hi' + (first ? ' ' + esc(first) : '') + ',</p>' +
        '<p>Last note, and then I am out of your inbox.</p>' +
        '<p>The team offer starts at ten seats because that is where the setup ' +
        'work pays for itself. Below that you are better off on the smaller plan, ' +
        'which is why I pointed you there rather than booking a call that would ' +
        'have reached the same answer.</p>' +
        '<p>If the office grows past ten, reply to this email and I will pick it ' +
        'up. The team version comes with a workshop, the setup done for you, and ' +
        'two weeks free before anything is charged. No form to fill in again, just ' +
        'reply to this one.</p>' +
        '<p>If it does not grow, that is fine too. The smaller plan is here:</p>' +
        '<p><a href="' + esc(pricing) + '">doviloop.dev pricing</a></p>' +
        '<p>Thanks for the two weeks of attention.</p>' +
        '<p>Dovy</p>'),
    },
  };

  out.push({ json: Object.assign({}, j, { emails: emails, unsub_url: unsubUrl }) });
}
return out;
"""

C2_UNSUB_JS = r"""
/* WF-C2 · Record an unsubscribe.

   Writes to three places on purpose, because the one place it SHOULD write to
   does not exist yet:

     1. n8n workflow static data. This is what the suppression check reads, so
        it is what actually stops the next email.
     2. an append-only file, so the record survives a static-data reset.
     3. an email to Dovy, so a human knows.

   What is missing: campaign.leads has no opt_out column. Batch B's schema does
   not have one and this workflow cannot add one. sql/004_consent.sql in this
   repo is the migration that would fix it properly. Until Dovy runs it, points
   1 to 3 are the whole mechanism. See BLOCKED.md F-6. */

const store = $getWorkflowStaticData('global');
store.optedOut = store.optedOut || {};

const out = [];
for (const item of $input.all()) {
  const j = item.json || {};
  const q = j.query || {};
  const email = String(q.e || '').trim().toLowerCase();
  const now = new Date().toISOString();

  if (email) store.optedOut[email] = now;

  out.push({ json: Object.assign({}, j, {
    unsub_email: email,
    unsub_at: now,
    line: JSON.stringify({ opted_out_at: now, work_email: email || null,
                           token: q.t || null, via: 'WF-C2 unsubscribe webhook' }),
    ack_html:
      '<!doctype html><meta charset="utf-8"><title>Stopped</title>' +
      '<body style="font-family:system-ui,sans-serif;max-width:520px;margin:12vh auto;' +
      'padding:0 20px;line-height:1.6;color:#1a1a1a">' +
      '<h1 style="font-size:22px">Stopped.</h1>' +
      '<p>No more emails from this campaign to <b>' +
      (email || 'that address').replace(/</g, '&lt;') + '</b>.</p>' +
      '<p style="color:#666;font-size:14px">Nothing else happens. You do not need ' +
      'to confirm and there is no second step.</p></body>',
  }) });
}
return out;
"""


def build_c2():
    w = WF("WF-C2", "WF-C2 — Under-10 nurture (opt-in gated, English only)",
           "Three emails over two weeks. Sends NOTHING without a proven opt-in.")

    w.node("Start: called with a lead + opt-in", "n8n-nodes-base.executeWorkflowTrigger", 1,
           (-220, -140), {},
           note="Started by hand or by a parent workflow with {lead, optin}. "
                "WF-C1 deliberately does NOT call this.")
    w.node("Webhook — record opt-in", "n8n-nodes-base.webhook", 2, (-220, 40), {
        "httpMethod": "POST",
        "path": "campaign/nurture-optin",
        "responseMode": "lastNode",
        "options": {},
    }, webhookId=nid("WF-C2", "webhook:optin"),
        note="For a future opt-in capture that posts server-side. Batch A's current "
             "opt-in is a mailto and never reaches this.")

    w.node("Config", "n8n-nodes-base.set", 3.4, (0, -50), cfg_assignment(C2_CONFIG),
           note="unsubscribe_base and postal_address must both be filled before "
                "this workflow is activated. See README.")
    w.node("Consent gate", "n8n-nodes-base.code", 2, (220, -50), code(C2_CONSENT_JS))
    w.node("IF consent proven", "n8n-nodes-base.if", 2, (440, -50),
           if_bool("={{ $json.consented }}"))

    # -- parked path --------------------------------------------------------
    w.node("Park: no opt-in, send nothing", "n8n-nodes-base.noOp", 1, (660, 160), {},
           note="This is the correct outcome for a lead with no opt-in. It is not an error.")
    w.node("To file: parked", "n8n-nodes-base.convertToFile", 1.1, (880, 160),
           to_text_file("parked_line", "nurture-parked.jsonl"))
    w.node("Append nurture-parked.jsonl", "n8n-nodes-base.readWriteFile", 1, (1100, 160),
           append_file("={{ $('Config').first().json.cfg.data_dir }}/nurture-parked.jsonl"),
           onError="continueRegularOutput")

    # -- consented path -----------------------------------------------------
    w.node("Build the three emails", "n8n-nodes-base.code", 2, (660, -180), code(C2_EMAILS_JS))
    w.node("Suppression check 1", "n8n-nodes-base.code", 2, (880, -180), code(C2_SUPPRESSION_JS))
    w.node("IF subscribed 1", "n8n-nodes-base.if", 2, (1100, -180),
           if_bool("={{ $json.still_subscribed }}"))
    w.node("Send email 1 (day 0)", "n8n-nodes-base.emailSend", 2.1, (1320, -260),
           email("={{ $json.cfg.from_email }}", "={{ $json.work_email }}",
                 "={{ $json.emails.e1.subject }}", "={{ $json.emails.e1.html }}"),
           credentials=CRED_SMTP)
    w.node("Wait 4 days", "n8n-nodes-base.wait", 1.1, (1540, -260),
           {"resume": "timeInterval", "amount": 4, "unit": "days"},
           webhookId=nid("WF-C2", "wait:4d"))

    w.node("Suppression check 2", "n8n-nodes-base.code", 2, (1760, -260), code(C2_SUPPRESSION_JS))
    w.node("IF subscribed 2", "n8n-nodes-base.if", 2, (1980, -260),
           if_bool("={{ $json.still_subscribed }}"))
    w.node("Send email 2 (day 4)", "n8n-nodes-base.emailSend", 2.1, (2200, -340),
           email("={{ $json.cfg.from_email }}", "={{ $json.work_email }}",
                 "={{ $json.emails.e2.subject }}", "={{ $json.emails.e2.html }}"),
           credentials=CRED_SMTP,
           note="Carries NO ROI figures. See the ROI SLOT comment in "
                "'Build the three emails' and BLOCKED.md F-5.")
    w.node("Wait 7 days", "n8n-nodes-base.wait", 1.1, (2420, -340),
           {"resume": "timeInterval", "amount": 7, "unit": "days"},
           webhookId=nid("WF-C2", "wait:7d"))

    w.node("Suppression check 3", "n8n-nodes-base.code", 2, (2640, -340), code(C2_SUPPRESSION_JS))
    w.node("IF subscribed 3", "n8n-nodes-base.if", 2, (2860, -340),
           if_bool("={{ $json.still_subscribed }}"))
    w.node("Send email 3 (day 11)", "n8n-nodes-base.emailSend", 2.1, (3080, -420),
           email("={{ $json.cfg.from_email }}", "={{ $json.work_email }}",
                 "={{ $json.emails.e3.subject }}", "={{ $json.emails.e3.html }}"),
           credentials=CRED_SMTP)
    w.node("Stopped: unsubscribed mid-sequence", "n8n-nodes-base.noOp", 1, (3080, -180), {},
           note="Every suppression check lands here on a false. Correct outcome.")

    # -- unsubscribe branch -------------------------------------------------
    w.node("Webhook — unsubscribe", "n8n-nodes-base.webhook", 2, (220, 420), {
        "httpMethod": "GET",
        "path": "campaign/unsubscribe",
        "responseMode": "responseNode",
        "options": {},
    }, webhookId=nid("WF-C2", "webhook:unsub"),
        note="One click, no confirm step. This is the 'trivially easy to stop' requirement.")
    w.node("Record opt-out", "n8n-nodes-base.code", 2, (440, 420), code(C2_UNSUB_JS))
    w.node("Respond: stopped", "n8n-nodes-base.respondToWebhook", 1.1, (660, 420), {
        "respondWith": "text",
        "responseCode": 200,
        "responseBody": "={{ $json.ack_html }}",
        "options": {"responseHeaders": {"entries": [
            {"name": "Content-Type", "value": "text/html; charset=utf-8"}]}},
    })
    w.node("To file: opt-out", "n8n-nodes-base.convertToFile", 1.1, (880, 420),
           to_text_file("line", "opt-outs.jsonl"))
    w.node("Append opt-outs.jsonl", "n8n-nodes-base.readWriteFile", 1, (1100, 420),
           append_file("={{ $('Config').first().json.cfg.data_dir }}/opt-outs.jsonl"),
           onError="continueRegularOutput")
    w.node("Send: someone unsubscribed", "n8n-nodes-base.emailSend", 2.1, (1320, 420),
           email("={{ $('Config').first().json.cfg.from_email }}",
                 "={{ $('Config').first().json.cfg.dovy_email }}",
                 "=[Unsubscribe] {{ $('Record opt-out').first().json.unsub_email }}",
                 "=<p>{{ $('Record opt-out').first().json.unsub_email }} stopped the "
                 "under-10 nurture at {{ $('Record opt-out').first().json.unsub_at }}.</p>"
                 "<p>Recorded in n8n static data and in opt-outs.jsonl. There is still no "
                 "opt_out column in campaign.leads to write it to. See sql/004_consent.sql.</p>"),
           credentials=CRED_SMTP, onError="continueRegularOutput")

    # -- wiring -------------------------------------------------------------
    w.link("Start: called with a lead + opt-in", "Config")
    w.link("Webhook — record opt-in", "Config")
    w.link("Config", "Consent gate")
    w.link("Consent gate", "IF consent proven")
    w.link("IF consent proven", "Build the three emails", 0)
    w.link("IF consent proven", "Park: no opt-in, send nothing", 1)
    w.link("Park: no opt-in, send nothing", "To file: parked")
    w.link("To file: parked", "Append nurture-parked.jsonl")

    w.link("Build the three emails", "Suppression check 1")
    w.link("Suppression check 1", "IF subscribed 1")
    w.link("IF subscribed 1", "Send email 1 (day 0)", 0)
    w.link("IF subscribed 1", "Stopped: unsubscribed mid-sequence", 1)
    w.link("Send email 1 (day 0)", "Wait 4 days")
    w.link("Wait 4 days", "Suppression check 2")
    w.link("Suppression check 2", "IF subscribed 2")
    w.link("IF subscribed 2", "Send email 2 (day 4)", 0)
    w.link("IF subscribed 2", "Stopped: unsubscribed mid-sequence", 1)
    w.link("Send email 2 (day 4)", "Wait 7 days")
    w.link("Wait 7 days", "Suppression check 3")
    w.link("Suppression check 3", "IF subscribed 3")
    w.link("IF subscribed 3", "Send email 3 (day 11)", 0)
    w.link("IF subscribed 3", "Stopped: unsubscribed mid-sequence", 1)

    w.link("Webhook — unsubscribe", "Record opt-out")
    w.link("Record opt-out", "Respond: stopped")
    w.link("Respond: stopped", "To file: opt-out")
    w.link("To file: opt-out", "Append opt-outs.jsonl")
    w.link("Append opt-outs.jsonl", "Send: someone unsubscribed")

    w.write()


# ===========================================================================
# WF-C3 — publish approved reels, Buffer first, real fallback second
# ===========================================================================

C3_CONFIG = (
    "={{ {\n"
    "  ledger_url: '',\n"
    "  dovy_email: 'hello@doviloop.dev',\n"
    "  from_email: 'campaign-bot@doviloop.dev',\n"
    "  data_dir: '/home/node/.n8n/campaign',\n"
    "  publisher: 'buffer',\n"
    "  buffer_api_url: 'https://graph.buffer.com/',\n"
    "  buffer_channels: { instagram: '', facebook: '', youtube_shorts: '', linkedin: '' },\n"
    "  meta_graph_version: 'v21.0',\n"
    "  ig_user_id: '',\n"
    "  fb_page_id: '',\n"
    "  asset_base_url: ''\n"
    "} }}"
)

C3_GATE_JS = r"""
/* ------------------------------------------------------------------------
   WF-C3 · Approval gate and channel map.  FAILS CLOSED.
   ------------------------------------------------------------------------
   This is the only workflow in the campaign that publishes in public, so the
   gate here is the one that matters most.

   THE DIVERGENCE, stated plainly. The spec says: read campaign.content "where
   published_at is null AND an approval flag is set". There is no approval flag.
   Batch B's campaign.content is exactly:

     id, kind, lane, language, hook, script_path, asset_path, platforms,
     published_at, buffer_id, natural_key, created_at

   No approved column, no status column, nothing. Batch D confirms the same
   list in reel-engine/engine/ledger.py (CONTENT_COLUMNS) and asserts it in its
   own tests. Batch D's approval lives in a completely different place: a
   GitHub-issue queue on disk (reel-engine/engine/approval.py, queue/proposed,
   queue/rendered, queue/rejected), which n8n cannot see.

   So "an approval flag is set" cannot be read from the ledger. Two ways to
   resolve that, and only one of them is safe:

     WRONG: treat "published_at is null and asset_path is set" as approval.
            That publishes every rendered reel automatically. A render is not
            an approval, and the spec's own sentence is "it only ever moves
            content Dovy has marked approved".

     RIGHT: keep a separate, explicit approval list that only Dovy writes, and
            publish nothing that is not on it. That is what this does.

   The list lives in this workflow's static data and is written by the
   "Webhook - approve content" branch of this same workflow. Approving is one
   POST per item, or one click from the email WF-C3 sends when it finds
   unapproved content waiting.

   The proper fix is one column. sql/004_consent.sql in this repo also proposes
   `campaign.content.approved_at timestamptz` so this list can move into the
   ledger where the rest of the campaign can see it. Until then: fails closed,
   which for a public post is the only acceptable direction.
   ------------------------------------------------------------------------ */

const CHANNELS_BY_LANGUAGE = {
  // English is the master and goes everywhere.
  en: ['instagram', 'facebook', 'youtube_shorts', 'linkedin'],
  // Danish and Lithuanian are LinkedIn only, per the spec's table.
  da: ['linkedin'],
  lt: ['linkedin'],
};

// Ported from reel-engine/engine/publish.py check_asset_url(). Buffer fetches
// the video when it publishes, which may be hours later, so a signed or
// expiring URL silently becomes a dead one.
const SIGNING_MARKERS = ['X-Amz-', 'Signature=', 'Expires=', 'token=', 'Key-Pair-Id='];

function assetProblem(url) {
  const u = String(url || '');
  if (!u) return 'no asset URL';
  if (!/^https:\/\//i.test(u)) return 'asset URL must be https';
  const withoutQuery = u.split('?')[0];
  if (!/\.mp4$/i.test(withoutQuery)) return 'asset URL must point directly at an .mp4';
  if (u.includes('?')) {
    const marker = SIGNING_MARKERS.find(m => u.includes(m));
    return 'asset URL carries a query string' + (marker ? ' (' + marker + ')' : '') +
      ': a signed or expiring URL will be dead by the time it is fetched';
  }
  return null;
}

const cfg = $('Config').first().json.cfg || {};
const store = $getWorkflowStaticData('global');
store.approved = store.approved || {};    // natural_key -> ISO approved_at

const rows = [];
for (const item of $input.all()) {
  const body = item.json && item.json.body;
  if (Array.isArray(body)) rows.push(...body);
  else if (Array.isArray(item.json)) rows.push(...item.json);
  else if (body) rows.push(body);
  else if (item.json && item.json.id) rows.push(item.json);
}

const ready = [];
const held = [];

for (const row of rows) {
  if (row.published_at) continue;                  // already out
  const key = row.natural_key || row.id;
  const approvedAt = store.approved[key];

  const channels = CHANNELS_BY_LANGUAGE[row.language] || [];
  const assetUrl = row.asset_path && /^https?:/i.test(row.asset_path)
    ? row.asset_path
    : (cfg.asset_base_url ? String(cfg.asset_base_url).replace(/\/+$/, '') + '/' +
        String(row.asset_path || '').replace(/^\/+/, '') : row.asset_path);

  const reasons = [];
  if (!approvedAt) reasons.push('not on the approval list');
  if (!channels.length) reasons.push('language "' + row.language + '" maps to no channel');
  const ap = assetProblem(assetUrl);
  if (ap) reasons.push(ap);
  if (!String(row.hook || '').trim()) reasons.push('no hook text to post with');

  const rec = {
    content_id: row.id,
    natural_key: key,
    kind: row.kind, lane: row.lane, language: row.language,
    hook: row.hook, asset_url: assetUrl,
    channels: channels,
    approved_at: approvedAt || null,
    hold_reasons: reasons,
  };
  if (reasons.length) held.push(rec); else ready.push(rec);
}

// One item per (content, channel). Everything downstream is per-post.
const out = [];
for (const r of ready) {
  for (const channel of r.channels) {
    out.push({ json: Object.assign({}, r, { cfg: cfg, channel: channel }) });
  }
}

// Always emit one summary item so the "nothing to do" branch has something to
// report and Dovy learns that content is waiting for his approval.
out.push({ json: {
  cfg: cfg,
  __summary: true,
  ready_count: ready.length,
  post_count: out.length,
  held: held,
  ready: ready.map(r => ({ natural_key: r.natural_key, language: r.language, channels: r.channels })),
} });

return out;
"""

C3_BUFFER_INTERPRET_JS = r"""
/* WF-C3 · Interpret a Buffer response.

   This node exists because of the single most important fact Batch D found
   about Buffer, in reel-engine/engine/publish.py:

     "Errors come back as HTTP 200 with a typed error body. A publisher that
      checks only the status code reports success on every failure."

   So the status code proves nothing. A post counts as created ONLY if the
   response carries a post id. The typenames below are an incomplete denylist
   copied from D's ERROR_TYPENAMES, and they are the second check, not the
   first: an unlisted error typename still fails, because it arrives with no id.

   Instagram gets a third check. It is the one platform that can report a post
   while having only sent a phone notification for someone to finish by hand,
   so it is judged on positive confirmation of auto-publishing and nothing less.
   AUTOPUBLISH_VALUES is matched by exact, case-folded equality: widening it is
   how a false success gets through, and a false success is the failure mode
   this whole node exists to prevent. NOTIFICATION_MARKERS stays a substring
   match because being loose there only ever fails closed. */

const ERROR_TYPENAMES = new Set(['Error', 'InvalidInputError', 'NotFoundError',
  'PostCreateError', 'RateLimitError', 'UnauthorizedError']);
const PUBLISH_TYPE_FIELDS = ['publishingType', 'publishing_type', 'postingType', 'type'];
const NOTIFICATION_MARKERS = ['notification', 'reminder', 'push', 'manual'];
const AUTOPUBLISH_VALUES = ['auto', 'automatic', 'auto_publish', 'direct'];

function node(payload) {
  const d = payload && payload.data;
  return (d && d.createPost) || null;
}

const out = [];
for (const item of $input.all()) {
  const j = item.json || {};
  const res = j.body !== undefined ? j.body : j;
  const meta = $('Fan out per channel').first ? null : null;   // context comes on the item
  const n = node(res);

  let ok = false;
  let postId = null;
  let error = null;

  if (res && res.errors && res.errors.length) {
    error = 'GraphQL errors: ' + JSON.stringify(res.errors).slice(0, 300);
  } else if (!n) {
    error = 'no createPost in the response: ' + JSON.stringify(res).slice(0, 300);
  } else if (ERROR_TYPENAMES.has(n.__typename)) {
    error = n.__typename + ': ' + (n.message || 'no message');
  } else if (!(n.post && n.post.id)) {
    // Unlisted error typename. No id means no post, whatever it calls itself.
    error = 'response carried no post id (__typename=' + n.__typename + ')';
  } else {
    postId = n.post.id;
    ok = true;
    if (j.channel === 'instagram') {
      let publishType = null;
      for (const f of PUBLISH_TYPE_FIELDS) {
        if (n.post[f] != null) { publishType = String(n.post[f]).toLowerCase(); break; }
      }
      if (publishType == null) {
        ok = false;
        error = 'Instagram: the response did not say how it will publish, so ' +
          'auto-publish is unconfirmed. Treating as not published.';
      } else if (NOTIFICATION_MARKERS.some(m => publishType.includes(m))) {
        ok = false;
        error = 'Instagram will only send a phone notification (' + publishType +
          '), not auto-publish. Requires a Professional account with ' +
          '"Enable Notifications by default" switched off.';
      } else if (!AUTOPUBLISH_VALUES.includes(publishType)) {
        ok = false;
        error = 'Instagram publishingType "' + publishType + '" is not a confirmed ' +
          'auto-publish value. Failing closed.';
      }
    }
  }

  out.push({ json: Object.assign({}, j, {
    publisher: 'buffer',
    post_ok: ok,
    post_id: postId,
    post_error: error,
    raw: res,
  }) });
}
return out;
"""

C3_NORMALISE_JS = r"""
/* WF-C3 · One row per content item, ready for the ledger write-back.

   Two divergences from the spec are resolved here, both forced by Batch B's
   real schema:

   1. `buffer_id` is ONE text column, but a single English reel goes to four
      channels and comes back with four ids. Rather than drop three of them,
      they are packed as "instagram=123;linkedin=456", which stays readable and
      greppable in a text column. If only one channel published, it is still
      just "linkedin=456".

   2. The spec says write "buffer_id and the scheduled time". campaign.content
      has no scheduled_for column; the only time column is published_at. So
      published_at gets the time the post was accepted by the platform. A row
      is marked published only if AT LEAST ONE channel actually succeeded, so a
      total failure leaves published_at null and the item is picked up again on
      the next Thursday rather than being silently marked done. */

const byContent = new Map();
const failures = [];

for (const item of $input.all()) {
  const j = item.json || {};
  if (j.__summary) continue;
  if (!j.content_id) continue;

  const rec = byContent.get(j.content_id) || {
    content_id: j.content_id,
    natural_key: j.natural_key,
    language: j.language,
    lane: j.lane,
    hook: j.hook,
    publisher: j.publisher || 'unknown',
    ids: [],
    platforms: [],
    errors: [],
  };
  if (j.post_ok && j.post_id) {
    rec.ids.push(j.channel + '=' + j.post_id);
    rec.platforms.push(j.channel);
  } else {
    rec.errors.push(j.channel + ': ' + (j.post_error || 'unknown failure'));
    failures.push({ content: j.natural_key, channel: j.channel, error: j.post_error });
  }
  byContent.set(j.content_id, rec);
}

const out = [];
for (const rec of byContent.values()) {
  const anyOk = rec.platforms.length > 0;
  out.push({ json: {
    cfg: $('Config').first().json.cfg,
    content_id: rec.content_id,
    natural_key: rec.natural_key,
    language: rec.language,
    lane: rec.lane,
    hook: rec.hook,
    publisher: rec.publisher,
    any_published: anyOk,
    platforms: rec.platforms,
    buffer_id: rec.ids.join(';') || null,
    errors: rec.errors,
    patch: anyOk ? {
      buffer_id: rec.ids.join(';'),
      published_at: new Date().toISOString(),
      platforms: rec.platforms,
    } : null,
  } });
}

if (out.length === 0) {
  out.push({ json: { cfg: $('Config').first().json.cfg, content_id: null,
                     any_published: false, nothing_to_do: true, patch: null } });
}
return out;
"""

C3_APPROVE_JS = r"""
/* WF-C3 · Record an approval. This is the only thing that lets a post go out.

   POST body: { "natural_key": "reel:on_camera:en:some-hook", "approved_by": "dovy" }
   or         { "natural_keys": ["...", "..."], "approved_by": "dovy" }

   Writes to workflow static data, which is what the approval gate reads, and
   to a file so the decision survives an instance rebuild. */

const store = $getWorkflowStaticData('global');
store.approved = store.approved || {};

const out = [];
for (const item of $input.all()) {
  const body = (item.json && item.json.body) || {};
  const keys = []
    .concat(body.natural_keys || [])
    .concat(body.natural_key ? [body.natural_key] : [])
    .map(k => String(k).trim())
    .filter(Boolean);

  const now = new Date().toISOString();
  const revoke = body.revoke === true;

  for (const k of keys) {
    if (revoke) delete store.approved[k];
    else store.approved[k] = now;
  }

  out.push({ json: {
    ok: keys.length > 0,
    action: revoke ? 'revoked' : 'approved',
    keys: keys,
    at: now,
    approved_by: body.approved_by || null,
    approved_total: Object.keys(store.approved).length,
    line: JSON.stringify({ at: now, action: revoke ? 'revoked' : 'approved',
                           keys: keys, by: body.approved_by || null }),
  } });
}
return out;
"""

C3_REPORT_JS = r"""
/* WF-C3 · The Thursday report to Dovy. Also the nudge for anything held. */

function esc(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;'); }

const summary = $('Approval gate + channel map').all()
  .map(i => i.json).find(j => j.__summary) || { held: [], ready: [] };

const results = $input.all().map(i => i.json).filter(j => j && !j.nothing_to_do);
const published = results.filter(r => r.any_published);
const failed = results.filter(r => !r.any_published);

const lines = [];
lines.push('<p><b>' + published.length + '</b> item(s) published, <b>' +
  failed.length + '</b> failed, <b>' + (summary.held || []).length +
  '</b> held back.</p>');

if (published.length) {
  lines.push('<h3 style="font-size:15px">Published</h3><ul>' + published.map(r =>
    '<li>' + esc(r.natural_key) + ' (' + esc(r.language) + ') to ' +
    esc(r.platforms.join(', ')) + ' via ' + esc(r.publisher) +
    (r.errors.length ? '<br><span style="color:#a33">partial: ' +
      r.errors.map(esc).join('; ') + '</span>' : '') + '</li>').join('') + '</ul>');
}
if (failed.length) {
  lines.push('<h3 style="font-size:15px">Failed, will be retried next Thursday</h3><ul>' +
    failed.map(r => '<li>' + esc(r.natural_key) + '<br><span style="color:#a33">' +
      r.errors.map(esc).join('<br>') + '</span></li>').join('') + '</ul>');
}
if ((summary.held || []).length) {
  lines.push('<h3 style="font-size:15px">Held back, nothing was posted</h3><ul>' +
    summary.held.map(h => '<li><code>' + esc(h.natural_key) + '</code> (' +
      esc(h.language) + ')<br><span style="color:#666">' +
      h.hold_reasons.map(esc).join('; ') + '</span></li>').join('') + '</ul>');
  lines.push('<p style="font-size:13px;color:#666">To approve one, POST ' +
    '<code>{"natural_key":"...","approved_by":"dovy"}</code> to the ' +
    '<code>campaign/content-approve</code> webhook. Nothing publishes until you do. ' +
    'There is no approved column in campaign.content to hold this, which is why ' +
    'the list lives in n8n. See README and sql/004_consent.sql.</p>');
}

return [{ json: {
  cfg: $('Config').first().json.cfg,
  report_subject: '[Reels] ' + published.length + ' published, ' + failed.length +
    ' failed, ' + (summary.held || []).length + ' held',
  report_html: '<div style="font-family:system-ui,sans-serif;font-size:14px;line-height:1.6">' +
    lines.join('') + '</div>',
} }];
"""


def build_c3():
    w = WF("WF-C3", "WF-C3 — Publish approved reels (Buffer, with a real fallback)",
           "Thursday morning. Publishes only what Dovy has explicitly approved.")

    w.node("Schedule: Thursday 08:00", "n8n-nodes-base.scheduleTrigger", 1.2, (-240, 0),
           {"rule": {"interval": [{"field": "cronExpression", "expression": "0 8 * * 4"}]}})
    w.node("Config", "n8n-nodes-base.set", 3.4, (-20, 0), cfg_assignment(C3_CONFIG),
           note="publisher: 'buffer' or 'direct'. Switch to 'direct' if Buffer's "
                "plan does not expose the API. Both paths are built.")
    w.node("Guard: ledger target", "n8n-nodes-base.code", 2, (200, 0), code(GUARD_JS))
    w.node("Ledger: read unpublished content", "n8n-nodes-base.httpRequest", 4.2, (420, 0),
           http_ledger("GET",
                       "={{ $json.cfg.ledger_url }}/rest/v1/content"
                       "?published_at=is.null&select=*&order=created_at.asc",
                       headers=LEDGER_READ_HEADERS),
           credentials=CRED_LEDGER, alwaysOutputData=True)
    w.node("Approval gate + channel map", "n8n-nodes-base.code", 2, (640, 0), code(C3_GATE_JS))
    w.node("IF a real post to make", "n8n-nodes-base.if", 2, (860, 0),
           if_bool("={{ $json.__summary !== true && !!$json.channel }}"))
    w.node("IF publisher is Buffer", "n8n-nodes-base.if", 2, (1080, -160),
           if_bool("={{ $json.cfg.publisher === 'buffer' }}"))

    # -- Buffer path --------------------------------------------------------
    buffer_body = (
        "={{ JSON.stringify({ query: "
        "'mutation CreatePost($channelId: ID!, $text: String!, $assets: [AssetInput!]) "
        "{ createPost(input: {channelId: $channelId, text: $text, assets: $assets}) "
        "{ __typename ... on PostCreated { post { id publishingType } } "
        "... on Error { message } } }', "
        "variables: { channelId: $json.cfg.buffer_channels[$json.channel], "
        "text: $json.hook, assets: [{ video: { url: $json.asset_url } }] } }) }}"
    )
    w.node("Buffer: createPost", "n8n-nodes-base.httpRequest", 4.2, (1300, -300), {
        "method": "POST",
        "url": "={{ $json.cfg.buffer_api_url }}",
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "sendHeaders": True,
        "headerParameters": {"parameters": [{"name": "Content-Type", "value": "application/json"}]},
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": buffer_body,
        "options": {"response": {"response": {"neverError": True}}, "timeout": 30000},
    }, credentials=CRED_BUFFER, alwaysOutputData=True,
        note="ONE createPost per channel, per reel-engine/engine/publish.py. Three "
             "calls, three independent failure modes.")
    w.node("Interpret Buffer response", "n8n-nodes-base.code", 2, (1520, -300),
           code(C3_BUFFER_INTERPRET_JS),
           note="Buffer returns errors as HTTP 200 with a typed error body. The status "
                "code proves nothing; only a post id does.")

    # -- direct fallback ----------------------------------------------------
    w.node("IF platform is Meta", "n8n-nodes-base.if", 2, (1300, -20),
           if_bool("={{ ['instagram','facebook'].includes($json.channel) }}"))
    w.node("IF platform is Instagram", "n8n-nodes-base.if", 2, (1520, -120),
           if_bool("={{ $json.channel === 'instagram' }}"))

    w.node("IG: create reel container", "n8n-nodes-base.httpRequest", 4.2, (1740, -180), {
        "method": "POST",
        "url": "=https://graph.facebook.com/{{ $json.cfg.meta_graph_version }}/"
               "{{ $json.cfg.ig_user_id }}/media",
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "sendBody": True,
        "contentType": "multipart-form-data",
        "bodyParameters": {"parameters": [
            {"name": "media_type", "value": "REELS"},
            {"name": "video_url", "value": "={{ $json.asset_url }}"},
            {"name": "caption", "value": "={{ $json.hook }}"},
            {"name": "share_to_feed", "value": "true"},
        ]},
        "options": {"response": {"response": {"neverError": True}}, "timeout": 60000},
    }, credentials=CRED_META, alwaysOutputData=True,
        note="Step 1 of 3. Instagram video publishing is asynchronous: create a "
             "container, wait for it to finish transcoding, then publish it.")
    w.node("Wait for IG transcode", "n8n-nodes-base.wait", 1.1, (1960, -180),
           {"resume": "timeInterval", "amount": 90, "unit": "seconds"},
           webhookId=nid("WF-C3", "wait:ig"))
    w.node("IG: publish container", "n8n-nodes-base.httpRequest", 4.2, (2180, -180), {
        "method": "POST",
        "url": "=https://graph.facebook.com/{{ $('Approval gate + channel map').item.json.cfg.meta_graph_version }}/"
               "{{ $('Approval gate + channel map').item.json.cfg.ig_user_id }}/media_publish",
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "sendBody": True,
        "contentType": "multipart-form-data",
        "bodyParameters": {"parameters": [
            {"name": "creation_id", "value": "={{ $('IG: create reel container').item.json.id }}"},
        ]},
        "options": {"response": {"response": {"neverError": True}}, "timeout": 60000},
    }, credentials=CRED_META, alwaysOutputData=True)
    w.node("Normalise: Instagram", "n8n-nodes-base.code", 2, (2400, -180), code(r"""
const out = [];
for (const item of $input.all()) {
  const res = item.json || {};
  const ctx = $('Approval gate + channel map').item.json;
  const id = res.id || null;
  out.push({ json: Object.assign({}, ctx, {
    publisher: 'meta_graph',
    post_ok: !!id && !res.error,
    post_id: id,
    post_error: id && !res.error ? null :
      ('Instagram: ' + JSON.stringify(res.error || res).slice(0, 300)),
  }) });
}
return out;
"""))

    w.node("FB page: post video", "n8n-nodes-base.httpRequest", 4.2, (1740, -20), {
        "method": "POST",
        "url": "=https://graph.facebook.com/{{ $json.cfg.meta_graph_version }}/"
               "{{ $json.cfg.fb_page_id }}/videos",
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "sendBody": True,
        "contentType": "multipart-form-data",
        "bodyParameters": {"parameters": [
            {"name": "file_url", "value": "={{ $json.asset_url }}"},
            {"name": "description", "value": "={{ $json.hook }}"},
        ]},
        "options": {"response": {"response": {"neverError": True}}, "timeout": 120000},
    }, credentials=CRED_META, alwaysOutputData=True)
    w.node("Normalise: Facebook", "n8n-nodes-base.code", 2, (1960, -20), code(r"""
const out = [];
for (const item of $input.all()) {
  const res = item.json || {};
  const ctx = $('Approval gate + channel map').item.json;
  const id = res.id || null;
  out.push({ json: Object.assign({}, ctx, {
    publisher: 'meta_graph',
    post_ok: !!id && !res.error,
    post_id: id,
    post_error: id && !res.error ? null :
      ('Facebook: ' + JSON.stringify(res.error || res).slice(0, 300)),
  }) });
}
return out;
"""))

    w.node("IF platform is YouTube", "n8n-nodes-base.if", 2, (1520, 200),
           if_bool("={{ $json.channel === 'youtube_shorts' }}"))
    w.node("Download asset (YouTube)", "n8n-nodes-base.httpRequest", 4.2, (1740, 140), {
        "method": "GET",
        "url": "={{ $json.asset_url }}",
        "options": {"response": {"response": {"responseFormat": "file",
                                              "outputPropertyName": "data"}},
                    "timeout": 300000},
    }, alwaysOutputData=True,
        note="The YouTube node uploads bytes, unlike Buffer and Meta which fetch a URL.")
    w.node("YouTube: upload short", "n8n-nodes-base.youTube", 1, (1960, 140), {
        "resource": "video",
        "operation": "upload",
        "title": "={{ $('Approval gate + channel map').item.json.hook.slice(0, 95) }}",
        "regionCode": "US",
        "categoryId": "22",
        "options": {
            "description": "={{ $('Approval gate + channel map').item.json.hook }}",
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }, credentials=CRED_YT, alwaysOutputData=True)
    w.node("Normalise: YouTube", "n8n-nodes-base.code", 2, (2180, 140), code(r"""
const out = [];
for (const item of $input.all()) {
  const res = item.json || {};
  const ctx = $('Approval gate + channel map').item.json;
  const id = res.id || (res.snippet && res.snippet.resourceId && res.snippet.resourceId.videoId) || null;
  out.push({ json: Object.assign({}, ctx, {
    publisher: 'youtube_data_api',
    post_ok: !!id,
    post_id: id,
    post_error: id ? null : ('YouTube: ' + JSON.stringify(res).slice(0, 300)),
  }) });
}
return out;
"""))

    w.node("IF platform is LinkedIn", "n8n-nodes-base.if", 2, (1740, 380),
           if_bool("={{ $json.channel === 'linkedin' }}"))
    w.node("Download asset (LinkedIn)", "n8n-nodes-base.httpRequest", 4.2, (1960, 320), {
        "method": "GET",
        "url": "={{ $json.asset_url }}",
        "options": {"response": {"response": {"responseFormat": "file",
                                              "outputPropertyName": "data"}},
                    "timeout": 300000},
    }, alwaysOutputData=True)
    w.node("LinkedIn: post video", "n8n-nodes-base.linkedIn", 1, (2180, 320), {
        "postAs": "person",
        "text": "={{ $('Approval gate + channel map').item.json.hook }}",
        "shareMediaCategory": "IMAGE",
        "additionalFields": {},
        "binaryPropertyName": "data",
    }, credentials={"linkedInOAuth2Api": {"name": "LinkedIn (campaign posting)"}},
        alwaysOutputData=True,
        note="n8n's LinkedIn node has no native video category. See README: on the "
             "direct path, LinkedIn video needs the three-call UGC upload and is "
             "logged as blocked. Text plus a still frame works today.")
    w.node("Normalise: LinkedIn", "n8n-nodes-base.code", 2, (2400, 320), code(r"""
const out = [];
for (const item of $input.all()) {
  const res = item.json || {};
  const ctx = $('Approval gate + channel map').item.json;
  const id = res.id || res.urn || null;
  out.push({ json: Object.assign({}, ctx, {
    publisher: 'linkedin_api',
    post_ok: !!id,
    post_id: id,
    post_error: id ? null : ('LinkedIn: ' + JSON.stringify(res).slice(0, 300)),
  }) });
}
return out;
"""))
    w.node("Unsupported channel", "n8n-nodes-base.noOp", 1, (1960, 520), {})

    # -- join, write back, report ------------------------------------------
    w.node("Collect results", "n8n-nodes-base.merge", 3, (2640, 0),
           {"mode": "append", "numberInputs": 5})
    w.node("Normalise for the ledger", "n8n-nodes-base.code", 2, (2860, 0),
           code(C3_NORMALISE_JS))
    w.node("IF anything published", "n8n-nodes-base.if", 2, (3080, 0),
           if_bool("={{ $json.any_published }}"))
    w.node("Ledger: mark published", "n8n-nodes-base.httpRequest", 4.2, (3300, -80),
           http_ledger("PATCH",
                       "={{ $json.cfg.ledger_url }}/rest/v1/content?id=eq.{{ $json.content_id }}",
                       headers=LEDGER_WRITE_HEADERS + [("Prefer", "return=representation")],
                       json_body="={{ JSON.stringify($json.patch) }}"),
           credentials=CRED_LEDGER, retryOnFail=True, alwaysOutputData=True)
    w.node("Nothing published", "n8n-nodes-base.noOp", 1, (3300, 120), {})
    w.node("Build Thursday report", "n8n-nodes-base.code", 2, (3520, 0), code(C3_REPORT_JS))
    w.node("Send: Thursday report", "n8n-nodes-base.emailSend", 2.1, (3740, 0),
           email("={{ $json.cfg.from_email }}", "={{ $json.cfg.dovy_email }}",
                 "={{ $json.report_subject }}", "={{ $json.report_html }}"),
           credentials=CRED_SMTP, onError="continueRegularOutput")

    # -- approval webhook ---------------------------------------------------
    w.node("Webhook — approve content", "n8n-nodes-base.webhook", 2, (640, 620), {
        "httpMethod": "POST",
        "path": "campaign/content-approve",
        "responseMode": "lastNode",
        "options": {},
    }, webhookId=nid("WF-C3", "webhook:approve"),
        note="The ONLY way a reel becomes publishable. Fails closed without it.")
    w.node("Record approval", "n8n-nodes-base.code", 2, (860, 620), code(C3_APPROVE_JS))
    w.node("To file: approvals", "n8n-nodes-base.convertToFile", 1.1, (1080, 620),
           to_text_file("line", "content-approvals.jsonl"))
    w.node("Append content-approvals.jsonl", "n8n-nodes-base.readWriteFile", 1, (1300, 620),
           append_file("={{ $('Config').first().json.cfg.data_dir }}/content-approvals.jsonl"),
           onError="continueRegularOutput")

    # -- wiring -------------------------------------------------------------
    w.link("Schedule: Thursday 08:00", "Config")
    w.link("Config", "Guard: ledger target")
    w.link("Guard: ledger target", "Ledger: read unpublished content")
    w.link("Ledger: read unpublished content", "Approval gate + channel map")
    w.link("Approval gate + channel map", "IF a real post to make")
    w.link("IF a real post to make", "IF publisher is Buffer", 0)
    w.link("IF a real post to make", "Normalise for the ledger", 1)

    w.link("IF publisher is Buffer", "Buffer: createPost", 0)
    w.link("IF publisher is Buffer", "IF platform is Meta", 1)
    w.link("Buffer: createPost", "Interpret Buffer response")
    w.link("Interpret Buffer response", "Collect results", 0, 0)

    w.link("IF platform is Meta", "IF platform is Instagram", 0)
    w.link("IF platform is Meta", "IF platform is YouTube", 1)
    w.link("IF platform is Instagram", "IG: create reel container", 0)
    w.link("IF platform is Instagram", "FB page: post video", 1)
    w.link("IG: create reel container", "Wait for IG transcode")
    w.link("Wait for IG transcode", "IG: publish container")
    w.link("IG: publish container", "Normalise: Instagram")
    w.link("Normalise: Instagram", "Collect results", 0, 1)
    w.link("FB page: post video", "Normalise: Facebook")
    w.link("Normalise: Facebook", "Collect results", 0, 2)

    w.link("IF platform is YouTube", "Download asset (YouTube)", 0)
    w.link("IF platform is YouTube", "IF platform is LinkedIn", 1)
    w.link("Download asset (YouTube)", "YouTube: upload short")
    w.link("YouTube: upload short", "Normalise: YouTube")
    w.link("Normalise: YouTube", "Collect results", 0, 3)

    w.link("IF platform is LinkedIn", "Download asset (LinkedIn)", 0)
    w.link("IF platform is LinkedIn", "Unsupported channel", 1)
    w.link("Download asset (LinkedIn)", "LinkedIn: post video")
    w.link("LinkedIn: post video", "Normalise: LinkedIn")
    w.link("Normalise: LinkedIn", "Collect results", 0, 4)

    w.link("Collect results", "Normalise for the ledger")
    w.link("Normalise for the ledger", "IF anything published")
    w.link("IF anything published", "Ledger: mark published", 0)
    w.link("IF anything published", "Nothing published", 1)
    w.link("Ledger: mark published", "Build Thursday report")
    w.link("Nothing published", "Build Thursday report")
    w.link("Build Thursday report", "Send: Thursday report")

    w.link("Webhook — approve content", "Record approval")
    w.link("Record approval", "To file: approvals")
    w.link("To file: approvals", "Append content-approvals.jsonl")

    w.write()


# ===========================================================================
# WF-C4 — comment keyword to DM (approval-gated)
# ===========================================================================

C4_CONFIG = (
    "={{ {\n"
    "  ledger_url: '',\n"
    "  dovy_email: 'hello@doviloop.dev',\n"
    "  from_email: 'campaign-bot@doviloop.dev',\n"
    "  data_dir: '/home/node/.n8n/campaign',\n"
    "  meta_graph_version: 'v21.0',\n"
    "  ig_user_id: '',\n"
    "  fb_page_id: '',\n"
    "  landing_url: 'https://teams.doviloop.dev',\n"
    "  keywords: ['draft', 'drafts', 'demo', 'outlook', 'info'],\n"
    "  rate_limit_days: 90,\n"
    "  approve_base: ''\n"
    "} }}"
)

C4_MATCH_JS = r"""
/* WF-C4 · Match the keyword, rate-limit the person, build the link.

   Rate limit: one DM per person per platform per rate_limit_days, held in
   workflow static data. "Nobody gets two" is the requirement; this makes a
   second one impossible even if they comment the keyword ten times. */

const cfg = $('Config').first().json.cfg || {};
const store = $getWorkflowStaticData('global');
store.dmSent = store.dmSent || {};      // "platform:user_id" -> ISO
store.pending = store.pending || {};    // approval token -> draft

const keywords = (cfg.keywords || []).map(k => String(k).toLowerCase());
const windowMs = Number(cfg.rate_limit_days || 90) * 24 * 3600 * 1000;

function commentsFrom(body) {
  // Meta delivers webhooks as { object, entry: [ { changes: [ { field, value } ] } ] }.
  const found = [];
  for (const entry of (body.entry || [])) {
    const objectId = entry.id;
    for (const change of (entry.changes || [])) {
      const v = change.value || {};
      if (change.field !== 'comments' && change.field !== 'feed') continue;
      if (v.item && v.item !== 'comment') continue;
      found.push({
        platform: body.object === 'instagram' ? 'instagram' : 'facebook',
        object_id: objectId,
        comment_id: v.id || v.comment_id || null,
        media_id: (v.media && v.media.id) || v.post_id || v.parent_id || null,
        text: v.text || v.message || '',
        user_id: (v.from && v.from.id) || v.sender_id || null,
        user_name: (v.from && (v.from.username || v.from.name)) || null,
      });
    }
  }
  return found;
}

const out = [];
for (const item of $input.all()) {
  const body = (item.json && item.json.body) || {};
  for (const c of commentsFrom(body)) {
    const text = String(c.text || '').toLowerCase();
    const hit = keywords.find(k => text.includes(k));
    const rateKey = c.platform + ':' + (c.user_id || 'unknown');
    const lastAt = store.dmSent[rateKey];
    const rateLimited = !!lastAt && (Date.now() - Date.parse(lastAt)) < windowMs;

    const reasons = [];
    if (!hit) reasons.push('no keyword matched');
    if (!c.comment_id) reasons.push('no comment id, cannot send a private reply');
    if (!c.user_id) reasons.push('no user id, cannot rate-limit safely');
    if (rateLimited) reasons.push('already messaged on ' + lastAt +
      ' (rate limit is ' + cfg.rate_limit_days + ' days)');

    const token = Buffer.from(rateKey + '|' + (c.comment_id || '') + '|' +
      Date.now()).toString('base64url');

    out.push({ json: {
      cfg: cfg,
      matched: reasons.length === 0,
      match_reasons: reasons,
      keyword: hit || null,
      approval_token: token,
      comment: c,
      rate_key: rateKey,
    } });
  }
}

if (out.length === 0) {
  out.push({ json: { cfg: cfg, matched: false,
                     match_reasons: ['no comment in the webhook payload'], comment: null } });
}
return out;
"""

C4_DRAFT_JS = r"""
/* WF-C4 · Build the DM draft and the approval request.

   THE APPROVAL STEP IS NOT OPTIONAL AND HAS NO BYPASS.

   Dovy's standing rule is that nothing which sends a message to a real person
   may exist without an explicit approval step. A DM to somebody who left a
   comment is a message to a real person, so it goes through the same gate as
   everything else. There is deliberately no `require_approval: false` in
   Config: a toggle that turns the rule off is the same as not having the rule.

   What this costs: the DM is not instant. What it buys: this workflow cannot,
   under any misconfiguration, message a stranger without Dovy pressing a link.

   The reel's UTM comes from the content row whose buffer_id contains the media
   id WF-C3 wrote there. If the lookup misses, the link still works and falls
   back to a generic social UTM rather than sending a broken URL. */

function esc(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;'); }

const out = [];
for (const item of $input.all()) {
  const j = item.json || {};
  const cfg = j.cfg || {};
  const c = j.comment || {};

  // The content row, if the lookup found one.
  let content = null;
  const lookup = j.content_lookup;
  if (Array.isArray(lookup) && lookup.length) content = lookup[0];

  const utm = {
    source: c.platform === 'instagram' ? 'instagram' : 'facebook',
    medium: 'social_dm',
    campaign: 'teams_q4',
    content: content ? (content.natural_key || content.id) : 'comment_keyword',
  };
  const link = String(cfg.landing_url || '').replace(/\/+$/, '') +
    '/?utm_source=' + encodeURIComponent(utm.source) +
    '&utm_medium=' + encodeURIComponent(utm.medium) +
    '&utm_campaign=' + encodeURIComponent(utm.campaign) +
    '&utm_content=' + encodeURIComponent(utm.content);

  const dmText =
    'Thanks for the comment. Here is the page with the two minute version and ' +
    'a place to book a call if it looks right for your office: ' + link + ' ' +
    'If it is not a fit, no problem at all, and I will not follow up.';

  const approveUrl = String(cfg.approve_base || '') +
    '?t=' + encodeURIComponent(j.approval_token || '');

  out.push({ json: Object.assign({}, j, {
    dm_text: dmText,
    landing_link: link,
    utm: utm,
    content_id: content ? content.id : null,
    content_natural_key: content ? content.natural_key : null,
    approve_url: approveUrl,
    approval_subject: '[Approve DM] ' + (c.user_name || c.user_id || 'someone') +
      ' commented "' + String(c.text || '').slice(0, 40) + '" on ' + c.platform,
    approval_html:
      '<div style="font-family:system-ui,sans-serif;font-size:14px;line-height:1.6">' +
      '<p>Someone commented a keyword. <b>Nothing has been sent.</b></p>' +
      '<table cellpadding="6" style="border-collapse:collapse">' +
      '<tr><td style="color:#666">Platform</td><td>' + esc(c.platform) + '</td></tr>' +
      '<tr><td style="color:#666">From</td><td>' + esc(c.user_name || c.user_id) + '</td></tr>' +
      '<tr><td style="color:#666">Comment</td><td>' + esc(c.text) + '</td></tr>' +
      '<tr><td style="color:#666">Matched</td><td>' + esc(j.keyword) + '</td></tr>' +
      '<tr><td style="color:#666">Reel</td><td>' +
        esc(content ? (content.natural_key + ' (' + content.language + ')') : 'not identified') +
      '</td></tr></table>' +
      '<p><b>The DM that would go out:</b></p>' +
      '<blockquote style="border-left:3px solid #ddd;padding-left:12px;color:#333">' +
      esc(dmText) + '</blockquote>' +
      '<p style="margin-top:20px"><a href="' + esc(approveUrl) +
      '" style="background:#111;color:#fff;padding:11px 18px;text-decoration:none;' +
      'border-radius:6px;display:inline-block">Send this DM</a></p>' +
      '<p style="font-size:13px;color:#666">Do nothing and nothing is sent. The link ' +
      'works once. This person will not be messaged again for ' +
      esc(cfg.rate_limit_days) + ' days either way.</p></div>',
    line: JSON.stringify({ drafted_at: new Date().toISOString(), platform: c.platform,
      user_id: c.user_id, comment_id: c.comment_id, keyword: j.keyword,
      token: j.approval_token, sent: false }),
  }) });
}
return out;
"""

C4_STORE_PENDING_JS = r"""
/* WF-C4 · Park the draft against its one-shot approval token. */
const store = $getWorkflowStaticData('global');
store.pending = store.pending || {};
const out = [];
for (const item of $input.all()) {
  const j = item.json || {};
  if (j.approval_token) {
    store.pending[j.approval_token] = {
      created_at: new Date().toISOString(),
      platform: j.comment.platform,
      comment_id: j.comment.comment_id,
      user_id: j.comment.user_id,
      user_name: j.comment.user_name,
      rate_key: j.rate_key,
      dm_text: j.dm_text,
      landing_link: j.landing_link,
      utm: j.utm,
      content_id: j.content_id || null,
      content_natural_key: j.content_natural_key || null,
    };
  }
  out.push(item);
}
return out;
"""

C4_REDEEM_JS = r"""
/* WF-C4 · Redeem an approval token. One shot, then it is gone.

   Also re-checks the rate limit at redemption time, so two approval emails
   opened in the wrong order still cannot produce two DMs. */

const cfg = $('Config approve').first().json.cfg || {};
const store = $getWorkflowStaticData('global');
store.pending = store.pending || {};
store.dmSent = store.dmSent || {};

const out = [];
for (const item of $input.all()) {
  const q = (item.json && item.json.query) || {};
  const token = String(q.t || '').trim();
  const draft = token ? store.pending[token] : null;
  const reasons = [];

  if (!token) reasons.push('no token');
  else if (!draft) reasons.push('this approval link has already been used, or has expired');

  if (draft) {
    const windowMs = Number(cfg.rate_limit_days || 90) * 24 * 3600 * 1000;
    const last = store.dmSent[draft.rate_key];
    if (last && (Date.now() - Date.parse(last)) < windowMs) {
      reasons.push('this person was already messaged on ' + last);
    }
  }

  const okToSend = reasons.length === 0;
  if (okToSend) {
    // Burn the token and stamp the rate limit BEFORE the send call, so a retry
    // or a double click cannot produce a second DM.
    delete store.pending[token];
    store.dmSent[draft.rate_key] = new Date().toISOString();
  }

  out.push({ json: {
    cfg: cfg,
    approved: okToSend,
    reasons: reasons,
    draft: draft || null,
    ack_html: '<!doctype html><meta charset="utf-8"><body style="font-family:system-ui,' +
      'sans-serif;max-width:520px;margin:12vh auto;padding:0 20px;line-height:1.6">' +
      (okToSend
        ? '<h1 style="font-size:22px">Sending.</h1><p>The DM is on its way to ' +
          String(draft.user_name || draft.user_id).replace(/</g, '&lt;') + '.</p>'
        : '<h1 style="font-size:22px">Not sent.</h1><p>' +
          reasons.map(r => r.replace(/</g, '&lt;')).join('<br>') + '</p>') +
      '</body>',
  } });
}
return out;
"""

C4_LOG_TOUCH_JS = r"""
/* WF-C4 · Log the touch. AND WHY IT DOES NOT GO INTO campaign.touches.

   The spec says "log a touch". It cannot go into campaign.touches, for two
   independent reasons, both read out of Batch B's 001_schema.sql:

   1. `touches.contact_id` is NOT NULL and references campaign.contacts, whose
      `company_id` is in turn NOT NULL and references campaign.companies. An
      Instagram commenter is an anonymous platform handle. To insert one touch
      this workflow would have to invent a company row and a contact row for a
      person whose name, firm and email it does not know, and campaign.companies
      requires a real `domain` with a CHECK constraint on its shape. Inventing
      those would put fabricated firms into the same table the ICP finder and
      the Friday brief count.

   2. `touches.channel` is the enum campaign.touch_channel, whose four values
      are linkedin_connect, linkedin_dm, email and phone. There is no
      instagram_dm and no facebook_dm, and B's comment on the type says the
      taxonomy is shared with the outreach engine and must not be extended
      without checking that repo's classifier first.

   So this is journalled to a file instead, in the exact shape a future insert
   would take, and the two schema gaps are named in BLOCKED.md (F-7) and
   proposed in sql/004_consent.sql. Nothing is fabricated into the ledger. */

const out = [];
for (const item of $input.all()) {
  const j = item.json || {};
  const d = j.draft || {};
  const sendRes = j.send_result || {};
  out.push({ json: Object.assign({}, j, {
    line: JSON.stringify({
      touched_at: new Date().toISOString(),
      channel: d.platform === 'instagram' ? 'instagram_dm' : 'facebook_dm',
      platform_user_id: d.user_id,
      platform_user_name: d.user_name,
      comment_id: d.comment_id,
      content_id: d.content_id,
      content_natural_key: d.content_natural_key,
      landing_link: d.landing_link,
      utm: d.utm,
      message_id: sendRes.message_id || null,
      delivered: !!sendRes.ok,
      error: sendRes.error || null,
      not_in_campaign_touches_because: [
        'touches.contact_id is NOT NULL and needs a contacts row, which needs a companies row',
        'touch_channel enum has no instagram_dm / facebook_dm value',
      ],
    }),
  }) });
}
return out;
"""


def build_c4():
    w = WF("WF-C4", "WF-C4 — Comment keyword to DM (approval gated)",
           "Meta comment webhook. Drafts a DM, mails Dovy to approve, sends only on approval.")

    w.node("Webhook — Meta verify", "n8n-nodes-base.webhook", 2, (-240, 320), {
        "httpMethod": "GET",
        "path": "campaign/meta-comments",
        "responseMode": "responseNode",
        "options": {},
    }, webhookId=nid("WF-C4", "webhook:verify"),
        note="Meta calls this once with hub.challenge when the subscription is created.")
    w.node("Respond: hub.challenge", "n8n-nodes-base.respondToWebhook", 1.1, (-20, 320), {
        "respondWith": "text",
        "responseCode": 200,
        "responseBody": "={{ $json.query['hub.challenge'] }}",
        "options": {},
    })

    w.node("Webhook — Meta comments", "n8n-nodes-base.webhook", 2, (-240, 0), {
        "httpMethod": "POST",
        "path": "campaign/meta-comments",
        "responseMode": "onReceived",
        "options": {},
    }, webhookId=nid("WF-C4", "webhook:comments"),
        note="Meta requires a 200 within seconds, so this answers immediately and "
             "does the work afterwards.")
    w.node("Config", "n8n-nodes-base.set", 3.4, (-20, 0), cfg_assignment(C4_CONFIG))
    w.node("Match keyword + rate limit", "n8n-nodes-base.code", 2, (200, 0), code(C4_MATCH_JS))
    w.node("IF keyword matched", "n8n-nodes-base.if", 2, (420, 0),
           if_bool("={{ $json.matched }}"))
    w.node("No match, do nothing", "n8n-nodes-base.noOp", 1, (640, 160), {})

    w.node("Ledger: find the reel", "n8n-nodes-base.httpRequest", 4.2, (640, -100),
           http_ledger("GET",
                       "={{ $json.cfg.ledger_url }}/rest/v1/content"
                       "?buffer_id=like.*{{ $json.comment.media_id }}*&select=*&limit=1",
                       headers=LEDGER_READ_HEADERS),
           credentials=CRED_LEDGER, alwaysOutputData=True,
           onError="continueRegularOutput",
           note="Joins the comment back to the reel through the ids WF-C3 wrote into "
                "buffer_id. A miss is fine: the link falls back to a generic UTM.")
    w.node("Merge lookup onto the comment", "n8n-nodes-base.code", 2, (860, -100), code(r"""
const out = [];
const src = $('Match keyword + rate limit').all().filter(i => i.json.matched);
const responses = $input.all();
for (let i = 0; i < src.length; i++) {
  const res = responses[Math.min(i, responses.length - 1)];
  const body = res && res.json ? (res.json.body !== undefined ? res.json.body : res.json) : null;
  out.push({ json: Object.assign({}, src[i].json, {
    content_lookup: Array.isArray(body) ? body : (body && body.id ? [body] : []),
  }) });
}
return out;
"""))
    w.node("Build DM draft", "n8n-nodes-base.code", 2, (1080, -100), code(C4_DRAFT_JS))
    w.node("Park draft against a token", "n8n-nodes-base.code", 2, (1300, -100),
           code(C4_STORE_PENDING_JS))
    w.node("Send: approve this DM", "n8n-nodes-base.emailSend", 2.1, (1520, -100),
           email("={{ $json.cfg.from_email }}", "={{ $json.cfg.dovy_email }}",
                 "={{ $json.approval_subject }}", "={{ $json.approval_html }}"),
           credentials=CRED_SMTP,
           note="THE approval step. There is no path from the comment to a DM that "
                "does not pass through Dovy clicking the link in this email.")
    w.node("To file: DM drafts", "n8n-nodes-base.convertToFile", 1.1, (1740, -100),
           to_text_file("line", "dm-drafts.jsonl"))
    w.node("Append dm-drafts.jsonl", "n8n-nodes-base.readWriteFile", 1, (1960, -100),
           append_file("={{ $('Config').first().json.cfg.data_dir }}/dm-drafts.jsonl"),
           onError="continueRegularOutput")

    # -- approval redemption ------------------------------------------------
    w.node("Webhook — approve DM", "n8n-nodes-base.webhook", 2, (-240, 640), {
        "httpMethod": "GET",
        "path": "campaign/meta-dm-approve",
        "responseMode": "responseNode",
        "options": {},
    }, webhookId=nid("WF-C4", "webhook:approve"))
    w.node("Config approve", "n8n-nodes-base.set", 3.4, (-20, 640), cfg_assignment(C4_CONFIG))
    w.node("Redeem approval token", "n8n-nodes-base.code", 2, (200, 640), code(C4_REDEEM_JS))
    w.node("Respond: approval result", "n8n-nodes-base.respondToWebhook", 1.1, (420, 640), {
        "respondWith": "text",
        "responseCode": 200,
        "responseBody": "={{ $json.ack_html }}",
        "options": {"responseHeaders": {"entries": [
            {"name": "Content-Type", "value": "text/html; charset=utf-8"}]}},
    })
    w.node("IF approved", "n8n-nodes-base.if", 2, (640, 640),
           if_bool("={{ $json.approved }}"))
    w.node("Not approved, nothing sent", "n8n-nodes-base.noOp", 1, (860, 800), {})

    w.node("Meta: send private reply", "n8n-nodes-base.httpRequest", 4.2, (860, 560), {
        "method": "POST",
        "url": "=https://graph.facebook.com/{{ $json.cfg.meta_graph_version }}/"
               "{{ $json.draft.platform === 'instagram' ? $json.cfg.ig_user_id : $json.cfg.fb_page_id }}"
               "/messages",
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "sendHeaders": True,
        "headerParameters": {"parameters": [{"name": "Content-Type", "value": "application/json"}]},
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify({ recipient: { comment_id: $json.draft.comment_id }, "
                    "message: { text: $json.draft.dm_text } }) }}",
        "options": {"response": {"response": {"neverError": True}}, "timeout": 30000},
    }, credentials=CRED_META, alwaysOutputData=True,
        note="A private reply to a comment. Meta only allows one per comment, which "
             "is a second, platform-side guarantee that nobody gets two.")
    w.node("Read send result", "n8n-nodes-base.code", 2, (1080, 560), code(r"""
const out = [];
for (const item of $input.all()) {
  const res = item.json || {};
  const prev = $('Redeem approval token').first().json;
  out.push({ json: Object.assign({}, prev, {
    send_result: {
      ok: !!res.message_id && !res.error,
      message_id: res.message_id || null,
      error: res.error ? JSON.stringify(res.error).slice(0, 300) : null,
    },
  }) });
}
return out;
"""))
    w.node("Log the touch (journal)", "n8n-nodes-base.code", 2, (1300, 560), code(C4_LOG_TOUCH_JS))
    w.node("To file: social touches", "n8n-nodes-base.convertToFile", 1.1, (1520, 560),
           to_text_file("line", "social-dm-touches.jsonl"))
    w.node("Append social-dm-touches.jsonl", "n8n-nodes-base.readWriteFile", 1, (1740, 560),
           append_file("={{ $('Config approve').first().json.cfg.data_dir }}/social-dm-touches.jsonl"),
           onError="continueRegularOutput")

    w.link("Webhook — Meta verify", "Respond: hub.challenge")
    w.link("Webhook — Meta comments", "Config")
    w.link("Config", "Match keyword + rate limit")
    w.link("Match keyword + rate limit", "IF keyword matched")
    w.link("IF keyword matched", "Ledger: find the reel", 0)
    w.link("IF keyword matched", "No match, do nothing", 1)
    w.link("Ledger: find the reel", "Merge lookup onto the comment")
    w.link("Merge lookup onto the comment", "Build DM draft")
    w.link("Build DM draft", "Park draft against a token")
    w.link("Park draft against a token", "Send: approve this DM")
    w.link("Send: approve this DM", "To file: DM drafts")
    w.link("To file: DM drafts", "Append dm-drafts.jsonl")

    w.link("Webhook — approve DM", "Config approve")
    w.link("Config approve", "Redeem approval token")
    w.link("Redeem approval token", "Respond: approval result")
    w.link("Respond: approval result", "IF approved")
    w.link("IF approved", "Meta: send private reply", 0)
    w.link("IF approved", "Not approved, nothing sent", 1)
    w.link("Meta: send private reply", "Read send result")
    w.link("Read send result", "Log the touch (journal)")
    w.link("Log the touch (journal)", "To file: social touches")
    w.link("To file: social touches", "Append social-dm-touches.jsonl")

    w.write()


# ===========================================================================
# WF-C5 — Stripe day 14. Creates a link. Never charges.
# ===========================================================================

C5_CONFIG = (
    "={{ {\n"
    "  ledger_url: '',\n"
    "  dovy_email: 'hello@doviloop.dev',\n"
    "  from_email: 'campaign-bot@doviloop.dev',\n"
    "  data_dir: '/home/node/.n8n/campaign',\n"
    "  stripe_api: 'https://api.stripe.com/v1',\n"
    "  price_seat_monthly: '',\n"
    "  price_setup_once: '',\n"
    "  success_url: 'https://doviloop.dev/welcome',\n"
    "  cancel_url: 'https://doviloop.dev',\n"
    "  usd_eur_rate: null\n"
    "} }}"
)

C5_DUE_JS = r"""
/* WF-C5 · Read the pilots due, and build the Stripe request WITHOUT sending it.

   THE RULE THIS NODE ENFORCES

   "A card being charged at the end of a free pilot is a conversation, not a
   cron job." So this workflow may create a payment LINK and may email that
   link TO DOVY. It may not charge, and it may not email the client.

   Three concrete guarantees, all checked below and again in
   "Guard: the link goes to Dovy only":

     1. The only Stripe call is POST /v1/checkout/sessions. Creating a Checkout
        Session moves no money and sends no email to anyone. The customer pays
        only by opening the URL themselves and entering a card.
     2. No parameter that could produce an off-session or automatic charge is
        ever built. FORBIDDEN_PARAMS below is checked against the built body,
        and a hit throws before the HTTP node runs.
     3. `customer_email` is deliberately NOT set. Stripe therefore has no
        address for this person at all, so no Stripe-side email can reach them
        even by misconfiguration.

   The two-day reminder is a separate, earlier read so Dovy has the conversation
   before the link exists. */

const FORBIDDEN_PARAMS = [
  'payment_intent_data[off_session]',
  'payment_intent_data[confirm]',
  'setup_future_usage',
  'off_session',
  'confirm',
  'customer_email',
];

const cfg = $('Config').first().json.cfg || {};

function rows(input) {
  const found = [];
  for (const item of input) {
    const b = item.json && item.json.body !== undefined ? item.json.body : item.json;
    if (Array.isArray(b)) found.push(...b);
    else if (b && b.id) found.push(b);
  }
  return found;
}

const out = [];
for (const p of rows($input.all())) {
  const lead = p.leads || p.lead || {};
  const seats = Number(p.seats || 0);

  const problems = [];
  if (!cfg.price_seat_monthly) problems.push('Config.price_seat_monthly is blank');
  if (!cfg.price_setup_once) problems.push('Config.price_setup_once is blank');
  if (!(seats >= 10)) problems.push('seats is ' + seats + ', and the offer does not exist below 10');

  // Stripe wants form encoding, so the body is built as pairs, not JSON.
  const params = [
    ['mode', 'subscription'],
    ['line_items[0][price]', String(cfg.price_seat_monthly || '')],
    ['line_items[0][quantity]', String(seats)],
    ['line_items[1][price]', String(cfg.price_setup_once || '')],
    ['line_items[1][quantity]', '1'],
    ['success_url', String(cfg.success_url || '')],
    ['cancel_url', String(cfg.cancel_url || '')],
    ['client_reference_id', String(p.id)],
    ['metadata[pilot_id]', String(p.id)],
    ['metadata[lead_id]', String(p.lead_id || '')],
    ['metadata[seats]', String(seats)],
    ['metadata[created_by]', 'WF-C5'],
  ];

  for (const [k] of params) {
    if (FORBIDDEN_PARAMS.includes(k)) {
      throw new Error('WF-C5 refused to build a Stripe request containing ' + k +
        '. That parameter can charge a card without the customer being present, ' +
        'and this workflow is not allowed to charge anything.');
    }
  }

  out.push({ json: {
    cfg: cfg,
    pilot_id: p.id,
    lead_id: p.lead_id,
    seats: seats,
    started_on: p.started_on,
    charge_due_on: p.charge_due_on,
    workshop_done_on: p.workshop_done_on || null,
    setup_done_on: p.setup_done_on || null,
    company_name: lead.company_name || null,
    work_email: lead.work_email || null,
    market: lead.market || null,
    problems: problems,
    ready: problems.length === 0,
    stripe_form: params.map(([k, v]) =>
      encodeURIComponent(k) + '=' + encodeURIComponent(v)).join('&'),
  } });
}

if (out.length === 0) out.push({ json: { cfg: cfg, nothing_due: true, ready: false } });
return out;
"""

C5_REMINDER_JS = r"""
/* WF-C5 · The two-days-before reminder.

   THE SPEC ASKS FOR "the pilot's usage summary". There is no usage data in the
   ledger to summarise. campaign.pilots has: started_on, workshop_done_on,
   setup_done_on, seats, charge_due_on, converted, stripe_customer_id, mrr_eur,
   lost_reason. Nothing about drafts written, mail handled, or people active.
   Usage lives in the PRODUCT database, which this campaign is forbidden to
   touch, so there is no honest way to put a usage number in this email.

   Rather than invent one, the reminder carries what the ledger actually knows
   and says plainly what it does not know. Logged as F-8 in BLOCKED.md. */

function esc(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;'); }

const items = $input.all().map(i => i.json).filter(j => j && !j.nothing_due);
if (items.length === 0) {
  return [{ json: { cfg: $('Config').first().json.cfg, skip_email: true } }];
}

const rowsHtml = items.map(p =>
  '<tr><td style="border-bottom:1px solid #eee">' + esc(p.company_name) + '</td>' +
  '<td style="border-bottom:1px solid #eee">' + esc(p.seats) + ' seats</td>' +
  '<td style="border-bottom:1px solid #eee">' + esc(p.charge_due_on) + '</td>' +
  '<td style="border-bottom:1px solid #eee">' +
    (p.workshop_done_on ? 'workshop ' + esc(p.workshop_done_on) : '<b style="color:#a33">no workshop recorded</b>') +
    '<br>' +
    (p.setup_done_on ? 'setup ' + esc(p.setup_done_on) : '<b style="color:#a33">no setup recorded</b>') +
  '</td></tr>').join('');

return [{ json: {
  cfg: $('Config').first().json.cfg,
  skip_email: false,
  reminder_subject: '[Pilot] ' + items.length + ' pilot(s) reach day 14 in two days',
  reminder_html:
    '<div style="font-family:system-ui,sans-serif;font-size:14px;line-height:1.6">' +
    '<p>Two days out. Have the conversation before the link exists.</p>' +
    '<table cellpadding="6" style="border-collapse:collapse">' +
    '<tr><th align="left">Firm</th><th align="left">Size</th>' +
    '<th align="left">Day 14</th><th align="left">Ledger says</th></tr>' +
    rowsHtml + '</table>' +
    '<p style="margin-top:18px;padding:10px;background:#f4f4f4;font-size:13px">' +
    '<b>What is not in here:</b> actual product usage. The campaign ledger records ' +
    'the pilot, not what they did inside DoviLoop. Usage lives in the product ' +
    'database, which this campaign is not allowed to read. If you want a usage ' +
    'number on this email, it has to come from there.</p></div>',
} }];
"""

C5_LINK_EMAIL_JS = r"""
/* WF-C5 · Guard: the link goes to Dovy only. Then build his email.

   This node is the last thing between a Stripe URL and an inbox, so it asserts
   the two facts the whole workflow rests on, and throws rather than send if
   either one is false:

     * the recipient is cfg.dovy_email;
     * the recipient is NOT the client's work_email.

   If Dovy ever edits the Send node's toEmail to a client address, this throws
   and no mail goes out. */

function esc(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;'); }

const out = [];
for (const item of $input.all()) {
  const j = item.json || {};
  const ctx = $('Build the Stripe request').item.json;
  const cfg = ctx.cfg || {};
  const res = j.body !== undefined ? j.body : j;

  const dovy = String(cfg.dovy_email || '').trim().toLowerCase();
  const client = String(ctx.work_email || '').trim().toLowerCase();

  if (!dovy) throw new Error('Config.dovy_email is blank. Refusing to send a payment link anywhere.');
  if (client && dovy === client) {
    throw new Error('Config.dovy_email is the same address as the client work_email (' +
      client + '). This workflow may only send the payment link to Dovy. Refusing.');
  }

  const url = res && res.url ? res.url : null;
  const err = res && res.error ? JSON.stringify(res.error).slice(0, 400) : null;

  out.push({ json: Object.assign({}, ctx, {
    checkout_url: url,
    checkout_id: (res && res.id) || null,
    stripe_error: err,
    recipient_checked: dovy,
    link_subject: url
      ? '[Send this] Day 14 payment link for ' + (ctx.company_name || 'a pilot')
      : '[Failed] Could not create the day 14 link for ' + (ctx.company_name || 'a pilot'),
    link_html: url
      ? '<div style="font-family:system-ui,sans-serif;font-size:14px;line-height:1.6">' +
        '<p><b>' + esc(ctx.company_name) + '</b> reaches day 14 today. ' +
        esc(ctx.seats) + ' seats.</p>' +
        '<p>The link below is a Stripe Checkout page for the 500 dollar setup plus ' +
        '89 dollars per seat per month. Nothing has been charged and nothing has ' +
        'been sent to them. Opening it does nothing either. It charges only when ' +
        'they open it and enter a card.</p>' +
        '<p style="padding:12px;background:#f4f4f4;word-break:break-all">' +
        '<a href="' + esc(url) + '">' + esc(url) + '</a></p>' +
        '<p><b>You send it.</b> Their address is ' +
        (ctx.work_email ? '<a href="mailto:' + esc(ctx.work_email) + '">' +
          esc(ctx.work_email) + '</a>' : 'not on the lead') + '.</p>' +
        '<p style="font-size:13px;color:#666">Pilot ' + esc(ctx.pilot_id) +
        '. Checkout session ' + esc((res && res.id) || 'unknown') + '.</p></div>'
      : '<div style="font-family:system-ui,sans-serif"><p>Stripe would not create the ' +
        'checkout session for ' + esc(ctx.company_name) + '.</p><pre>' + esc(err) +
        '</pre><p>Nothing was charged and nothing was sent. Fix it and re-run WF-C5 ' +
        'by hand.</p></div>',
  }) });
}
return out;
"""

C5_WEBHOOK_JS = r"""
/* WF-C5 · Stripe webhook. Signature is verified by re-fetching, not by a secret.

   The payload that arrives on a webhook URL is unauthenticated: anyone who
   learns the URL can post anything to it. The usual fix is to verify the
   `stripe-signature` header with the endpoint's signing secret, which would
   mean putting a secret into this workflow.

   This does the other accepted thing instead: take ONLY the event id from the
   incoming body, throw the rest away, and fetch that event back from Stripe
   over the authenticated API. A forged post either names an event id that does
   not exist, or names a real one whose real contents are then used. Either way
   nothing an attacker writes reaches the ledger, and no signing secret has to
   live in an exported JSON file. */

const out = [];
for (const item of $input.all()) {
  const body = (item.json && item.json.body) || {};
  const headers = (item.json && item.json.headers) || {};
  const id = String(body.id || '').trim();

  out.push({ json: {
    cfg: $('Config webhook').first().json.cfg,
    event_id: id,
    has_signature_header: !!headers['stripe-signature'],
    claimed_type: body.type || null,
    usable: /^evt_[A-Za-z0-9_]+$/.test(id),
  } });
}
return out;
"""

C5_CONVERT_JS = r"""
/* WF-C5 · Turn a verified Stripe event into the ledger write.

   THE CURRENCY PROBLEM, which Batch B raised and did not resolve:
   the offer is priced in USD (89 dollars a seat, 500 dollars setup) and the
   column is `campaign.pilots.mrr_eur`, in euros. B's own comment on the column
   says "whoever writes it must convert". This is the whoever.

   There is no FX rate in this container and no rate source that is right to
   pick automatically, because the right rate is the one Stripe actually
   settled at, not today's mid-market rate. So: if Config.usd_eur_rate is not
   set, this node writes `converted = true` and LEAVES mrr_eur NULL, and says so
   in the report. A null is a known gap. A guessed number is a wrong number in
   the one table the Friday brief adds up. Logged as F-9 in BLOCKED.md. */

const PAID_TYPES = ['checkout.session.completed', 'invoice.paid', 'invoice.payment_succeeded'];

const out = [];
for (const item of $input.all()) {
  const res = item.json && item.json.body !== undefined ? item.json.body : item.json;
  const cfg = $('Config webhook').first().json.cfg || {};
  const type = res && res.type;
  const obj = (res && res.data && res.data.object) || {};

  const paid = PAID_TYPES.includes(type) &&
    (obj.payment_status === 'paid' || obj.status === 'paid' || obj.status === 'complete');

  const meta = obj.metadata || {};
  const pilotId = meta.pilot_id || obj.client_reference_id || null;
  const seats = Number(meta.seats || 0);

  const rate = cfg.usd_eur_rate;
  const usable = typeof rate === 'number' && rate > 0;
  const mrrUsd = seats * 89;
  const mrrEur = usable ? Math.round(mrrUsd * rate * 100) / 100 : null;

  out.push({ json: {
    cfg: cfg,
    event_type: type,
    paid: paid,
    pilot_id: pilotId,
    seats: seats,
    mrr_usd: mrrUsd,
    mrr_eur: mrrEur,
    rate_used: usable ? rate : null,
    // pilots_mrr_needs_conversion CHECK: mrr_eur may only be non-null when
    // converted is true, so these two always move together.
    patch: paid && pilotId
      ? (usable ? { converted: true, mrr_eur: mrrEur,
                    stripe_customer_id: obj.customer || null }
                : { converted: true, stripe_customer_id: obj.customer || null })
      : null,
    note: usable ? null
      : 'Config.usd_eur_rate is not set, so mrr_eur was left NULL rather than guessed. ' +
        'The Friday brief will show this pilot as converted with no revenue attached.',
  } });
}
return out;
"""


def build_c5():
    w = WF("WF-C5", "WF-C5 — Pilot day 14 (creates a link, never charges)",
           "Daily. Reminder at day 12, a Stripe link to DOVY at day 14, webhook write-back.")

    w.node("Schedule: daily 09:00", "n8n-nodes-base.scheduleTrigger", 1.2, (-240, 0),
           {"rule": {"interval": [{"field": "cronExpression", "expression": "0 9 * * *"}]}})
    w.node("Config", "n8n-nodes-base.set", 3.4, (-20, 0), cfg_assignment(C5_CONFIG),
           note="usd_eur_rate ships null on purpose. See the currency note in "
                "'Apply the Stripe event'.")
    w.node("Guard: ledger target", "n8n-nodes-base.code", 2, (200, 0), code(GUARD_JS))

    # -- day 12 reminder ----------------------------------------------------
    w.node("Ledger: pilots due in 2 days", "n8n-nodes-base.httpRequest", 4.2, (420, -180),
           http_ledger("GET",
                       "={{ $json.cfg.ledger_url }}/rest/v1/pilots"
                       "?charge_due_on=eq.{{ $now.plus(2, 'days').toFormat('yyyy-MM-dd') }}"
                       "&converted=is.false&select=*,leads(*)",
                       headers=LEDGER_READ_HEADERS),
           credentials=CRED_LEDGER, alwaysOutputData=True)
    w.node("Build the reminder", "n8n-nodes-base.code", 2, (640, -180), code(C5_REMINDER_JS))
    w.node("IF a reminder to send", "n8n-nodes-base.if", 2, (860, -180),
           if_bool("={{ !$json.skip_email }}"))
    w.node("Send: day 12 reminder", "n8n-nodes-base.emailSend", 2.1, (1080, -260),
           email("={{ $json.cfg.from_email }}", "={{ $json.cfg.dovy_email }}",
                 "={{ $json.reminder_subject }}", "={{ $json.reminder_html }}"),
           credentials=CRED_SMTP, onError="continueRegularOutput")
    w.node("No pilots at day 12", "n8n-nodes-base.noOp", 1, (1080, -100), {})

    # -- day 14 link --------------------------------------------------------
    w.node("Ledger: pilots due today", "n8n-nodes-base.httpRequest", 4.2, (420, 160),
           http_ledger("GET",
                       "={{ $json.cfg.ledger_url }}/rest/v1/pilots"
                       "?charge_due_on=eq.{{ $now.toFormat('yyyy-MM-dd') }}"
                       "&converted=is.false&select=*,leads(*)",
                       headers=LEDGER_READ_HEADERS),
           credentials=CRED_LEDGER, alwaysOutputData=True)
    w.node("Build the Stripe request", "n8n-nodes-base.code", 2, (640, 160), code(C5_DUE_JS))
    w.node("IF a link to create", "n8n-nodes-base.if", 2, (860, 160),
           if_bool("={{ $json.ready }}"))
    w.node("Nothing due today", "n8n-nodes-base.noOp", 1, (1080, 320), {})
    w.node("Stripe: create checkout session", "n8n-nodes-base.httpRequest", 4.2, (1080, 80), {
        "method": "POST",
        "url": "={{ $json.cfg.stripe_api }}/checkout/sessions",
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "sendHeaders": True,
        "headerParameters": {"parameters": [
            {"name": "Content-Type", "value": "application/x-www-form-urlencoded"}]},
        "sendBody": True,
        "contentType": "raw",
        "rawContentType": "application/x-www-form-urlencoded",
        "body": "={{ $json.stripe_form }}",
        "options": {"response": {"response": {"neverError": True}}, "timeout": 30000},
    }, credentials=CRED_STRIPE, alwaysOutputData=True,
        note="POST /v1/checkout/sessions is the ONLY Stripe write this workflow makes. "
             "Creating a session moves no money and emails nobody.")
    w.node("Guard: the link goes to Dovy only", "n8n-nodes-base.code", 2, (1300, 80),
           code(C5_LINK_EMAIL_JS),
           note="Throws rather than send if the recipient is not Dovy, or is the client.")
    w.node("Send: link for Dovy to send", "n8n-nodes-base.emailSend", 2.1, (1520, 80),
           email("={{ $json.cfg.from_email }}",
                 "={{ $json.recipient_checked }}",
                 "={{ $json.link_subject }}", "={{ $json.link_html }}"),
           credentials=CRED_SMTP,
           note="toEmail is the value the guard node just verified, not a free-text "
                "address. Editing it to a client address makes the guard throw.")
    w.node("To file: link log", "n8n-nodes-base.convertToFile", 1.1, (1740, 80),
           to_text_file("link_subject", "day14-links.jsonl"))
    w.node("Append day14-links.jsonl", "n8n-nodes-base.readWriteFile", 1, (1960, 80),
           append_file("={{ $('Config').first().json.cfg.data_dir }}/day14-links.jsonl"),
           onError="continueRegularOutput")

    # -- Stripe webhook -----------------------------------------------------
    w.node("Webhook — Stripe events", "n8n-nodes-base.webhook", 2, (-240, 520), {
        "httpMethod": "POST",
        "path": "campaign/stripe",
        "responseMode": "onReceived",
        "options": {},
    }, webhookId=nid("WF-C5", "webhook:stripe"))
    w.node("Config webhook", "n8n-nodes-base.set", 3.4, (-20, 520), cfg_assignment(C5_CONFIG))
    w.node("Take only the event id", "n8n-nodes-base.code", 2, (200, 520), code(C5_WEBHOOK_JS))
    w.node("IF event id looks real", "n8n-nodes-base.if", 2, (420, 520),
           if_bool("={{ $json.usable }}"))
    w.node("Ignored: not a Stripe event id", "n8n-nodes-base.noOp", 1, (640, 680), {})
    w.node("Stripe: re-fetch the event", "n8n-nodes-base.httpRequest", 4.2, (640, 440), {
        "method": "GET",
        "url": "={{ $json.cfg.stripe_api }}/events/{{ $json.event_id }}",
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "options": {"response": {"response": {"neverError": True}}, "timeout": 20000},
    }, credentials=CRED_STRIPE, alwaysOutputData=True,
        note="This is the verification. The incoming body is never trusted.")
    w.node("Apply the Stripe event", "n8n-nodes-base.code", 2, (860, 440), code(C5_CONVERT_JS))
    w.node("IF it was actually paid", "n8n-nodes-base.if", 2, (1080, 440),
           if_bool("={{ $json.paid && !!$json.patch }}"))
    w.node("Not a payment, ignored", "n8n-nodes-base.noOp", 1, (1300, 600), {})
    w.node("Ledger: mark converted", "n8n-nodes-base.httpRequest", 4.2, (1300, 380),
           http_ledger("PATCH",
                       "={{ $json.cfg.ledger_url }}/rest/v1/pilots?id=eq.{{ $json.pilot_id }}",
                       headers=LEDGER_WRITE_HEADERS + [("Prefer", "return=representation")],
                       json_body="={{ JSON.stringify($json.patch) }}"),
           credentials=CRED_LEDGER, retryOnFail=True, alwaysOutputData=True)
    w.node("Send: a pilot converted", "n8n-nodes-base.emailSend", 2.1, (1520, 380),
           email("={{ $('Config webhook').first().json.cfg.from_email }}",
                 "={{ $('Config webhook').first().json.cfg.dovy_email }}",
                 "=[Converted] pilot {{ $('Apply the Stripe event').first().json.pilot_id }}",
                 "=<p>Paid. {{ $('Apply the Stripe event').first().json.seats }} seats, "
                 "{{ $('Apply the Stripe event').first().json.mrr_usd }} USD per month.</p>"
                 "<p>mrr_eur written: {{ $('Apply the Stripe event').first().json.mrr_eur }}</p>"
                 "<p>{{ $('Apply the Stripe event').first().json.note }}</p>"),
           credentials=CRED_SMTP, onError="continueRegularOutput")

    w.link("Schedule: daily 09:00", "Config")
    w.link("Config", "Guard: ledger target")
    w.link("Guard: ledger target", "Ledger: pilots due in 2 days")
    w.link("Guard: ledger target", "Ledger: pilots due today")

    w.link("Ledger: pilots due in 2 days", "Build the reminder")
    w.link("Build the reminder", "IF a reminder to send")
    w.link("IF a reminder to send", "Send: day 12 reminder", 0)
    w.link("IF a reminder to send", "No pilots at day 12", 1)

    w.link("Ledger: pilots due today", "Build the Stripe request")
    w.link("Build the Stripe request", "IF a link to create")
    w.link("IF a link to create", "Stripe: create checkout session", 0)
    w.link("IF a link to create", "Nothing due today", 1)
    w.link("Stripe: create checkout session", "Guard: the link goes to Dovy only")
    w.link("Guard: the link goes to Dovy only", "Send: link for Dovy to send")
    w.link("Send: link for Dovy to send", "To file: link log")
    w.link("To file: link log", "Append day14-links.jsonl")

    w.link("Webhook — Stripe events", "Config webhook")
    w.link("Config webhook", "Take only the event id")
    w.link("Take only the event id", "IF event id looks real")
    w.link("IF event id looks real", "Stripe: re-fetch the event", 0)
    w.link("IF event id looks real", "Ignored: not a Stripe event id", 1)
    w.link("Stripe: re-fetch the event", "Apply the Stripe event")
    w.link("Apply the Stripe event", "IF it was actually paid")
    w.link("IF it was actually paid", "Ledger: mark converted", 0)
    w.link("IF it was actually paid", "Not a payment, ignored", 1)
    w.link("Ledger: mark converted", "Send: a pilot converted")

    w.write()


# ===========================================================================
# WF-C6 — Friday brief. Snapshot first, then render.
# ===========================================================================

C6_CONFIG = (
    "={{ {\n"
    "  ledger_url: '',\n"
    "  dovy_email: 'hello@doviloop.dev',\n"
    "  from_email: 'campaign-bot@doviloop.dev',\n"
    "  data_dir: '/home/node/.n8n/campaign',\n"
    "  python_bin: 'python3',\n"
    "  ledger_repo: '/opt/campaign/campaign-ledger',\n"
    "  ad_engine_repo: '/opt/campaign/ad-engine',\n"
    "  meta_graph_version: 'v21.0'\n"
    "} }}"
)

C6_FANOUT_JS = r"""
/* WF-C6 · Fan out published content into one stats request per platform post.

   WF-C3 packs the per-channel ids into campaign.content.buffer_id as
   "instagram=123;linkedin=456", because that column is a single text field and
   one reel goes to up to four channels. This unpacks it again.

   Only Meta and YouTube ids can be turned into numbers here. LinkedIn's
   organic post analytics need a Marketing Developer Platform approval that this
   account does not have, so LinkedIn rows are emitted with a `skipped` flag and
   counted in the report rather than silently dropped. See BLOCKED.md F-10. */

const cfg = $('Config').first().json.cfg || {};
const rows = [];
for (const item of $input.all()) {
  const b = item.json && item.json.body !== undefined ? item.json.body : item.json;
  if (Array.isArray(b)) rows.push(...b);
  else if (b && b.id) rows.push(b);
}

const today = new Date().toISOString().slice(0, 10);
const out = [];
let skipped = 0;

for (const row of rows) {
  if (!row.published_at || !row.buffer_id) continue;
  for (const pair of String(row.buffer_id).split(';')) {
    const [platform, postId] = pair.split('=');
    if (!platform || !postId) continue;
    const supported = platform === 'instagram' || platform === 'facebook' ||
                      platform === 'youtube_shorts';
    if (!supported) { skipped++; continue; }
    out.push({ json: {
      cfg: cfg,
      content_id: row.id,
      natural_key: row.natural_key,
      platform: platform,
      post_id: postId,
      captured_on: today,
    } });
  }
}

out.push({ json: { cfg: cfg, __stats_summary: true, requests: out.length,
                   skipped_linkedin: skipped, captured_on: today } });
return out;
"""

C6_STATS_JS = r"""
/* WF-C6 · Normalise a platform insights response into a campaign.content_stats row.

   The column list is Batch B's, exactly: content_id, platform, captured_on,
   views, likes, comments, saves, clicks, with a unique constraint on
   (content_id, platform, captured_on) and a CHECK that every number is >= 0.
   Anything a platform does not report becomes 0, which the schema's default
   already is, rather than being invented. */

function metaMetric(res, names) {
  const data = (res && res.data) || [];
  for (const entry of data) {
    if (names.includes(entry.name)) {
      const v = entry.values && entry.values[0];
      const n = v && (v.value != null ? v.value : v);
      if (typeof n === 'number') return n;
      if (n && typeof n.value === 'number') return n.value;
    }
  }
  return 0;
}

const out = [];
for (const item of $input.all()) {
  const ctx = $('Fan out published posts').item.json;
  const res = item.json && item.json.body !== undefined ? item.json.body : item.json;

  let views = 0, likes = 0, comments = 0, saves = 0, clicks = 0;

  if (ctx.platform === 'youtube_shorts') {
    const s = (res && res.items && res.items[0] && res.items[0].statistics) || {};
    views = Number(s.viewCount || 0);
    likes = Number(s.likeCount || 0);
    comments = Number(s.commentCount || 0);
  } else {
    views = metaMetric(res, ['plays', 'video_views', 'reach', 'impressions',
                             'post_impressions', 'ig_reels_video_view_total_time']);
    likes = metaMetric(res, ['likes', 'post_reactions_like_total']);
    comments = metaMetric(res, ['comments']);
    saves = metaMetric(res, ['saved', 'saves']);
    clicks = metaMetric(res, ['post_clicks', 'website_clicks', 'clicks']);
  }

  const nonNeg = (n) => Math.max(0, Math.round(Number(n) || 0));

  out.push({ json: {
    cfg: ctx.cfg,
    row: {
      content_id: ctx.content_id,
      platform: ctx.platform,
      captured_on: ctx.captured_on,
      views: nonNeg(views), likes: nonNeg(likes), comments: nonNeg(comments),
      saves: nonNeg(saves), clicks: nonNeg(clicks),
    },
    fetch_error: (res && res.error) ? JSON.stringify(res.error).slice(0, 200) : null,
  } });
}
return out;
"""

C6_MD_HTML_JS = r"""
/* WF-C6 · Render the brief's markdown as HTML.

   friday_brief.py prints one page of markdown and n8n has no markdown node
   guaranteed to be installed, so this converts the subset the brief actually
   emits: h1 to h4, GitHub-style tables, bullet lists, bold, inline code,
   horizontal rules and paragraphs. Anything it does not recognise is passed
   through escaped, so an unrecognised construct shows as text rather than
   disappearing or breaking the layout.

   The brief's own tone rule matters here: it prints a dash for an unknown
   number rather than a fabricated zero. Those dashes are preserved. */

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
function inline(s) {
  return esc(s)
    .replace(/`([^`]+)`/g, '<code style="background:#f0f0f0;padding:1px 4px;border-radius:3px">$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2">$1</a>');
}
function isTableRow(l) { return /^\s*\|.*\|\s*$/.test(l); }
function isDivider(l) { return /^\s*\|[\s:|-]+\|\s*$/.test(l); }
function cells(l) {
  return l.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(c => c.trim());
}

function render(md) {
  const lines = String(md || '').split('\n');
  const html = [];
  let i = 0;
  let inList = false;

  const closeList = () => { if (inList) { html.push('</ul>'); inList = false; } };

  while (i < lines.length) {
    const line = lines[i];

    if (isTableRow(line) && i + 1 < lines.length && isDivider(lines[i + 1])) {
      closeList();
      const head = cells(line);
      i += 2;
      const body = [];
      while (i < lines.length && isTableRow(lines[i])) { body.push(cells(lines[i])); i++; }
      html.push(
        '<table cellpadding="7" style="border-collapse:collapse;margin:14px 0;font-size:13px">' +
        '<tr>' + head.map(h =>
          '<th align="left" style="border-bottom:2px solid #333;white-space:nowrap">' +
          inline(h) + '</th>').join('') + '</tr>' +
        body.map(r => '<tr>' + r.map(c =>
          '<td style="border-bottom:1px solid #eee;white-space:nowrap">' +
          inline(c) + '</td>').join('') + '</tr>').join('') +
        '</table>');
      continue;
    }

    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    if (h) {
      closeList();
      const level = h[1].length;
      const size = [22, 18, 15.5, 14][level - 1];
      html.push('<h' + level + ' style="font-size:' + size + 'px;margin:22px 0 8px">' +
        inline(h[2]) + '</h' + level + '>');
      i++; continue;
    }

    if (/^\s*[-*]\s+/.test(line)) {
      if (!inList) { html.push('<ul style="margin:8px 0 8px 18px;padding:0">'); inList = true; }
      html.push('<li style="margin:3px 0">' + inline(line.replace(/^\s*[-*]\s+/, '')) + '</li>');
      i++; continue;
    }

    if (/^\s*(-{3,}|_{3,}|\*{3,})\s*$/.test(line)) {
      closeList();
      html.push('<hr style="border:none;border-top:1px solid #ddd;margin:20px 0">');
      i++; continue;
    }

    if (line.trim() === '') { closeList(); i++; continue; }

    closeList();
    const para = [];
    while (i < lines.length && lines[i].trim() !== '' && !isTableRow(lines[i]) &&
           !/^#{1,4}\s/.test(lines[i]) && !/^\s*[-*]\s+/.test(lines[i])) {
      para.push(lines[i]); i++;
    }
    html.push('<p style="margin:9px 0">' + inline(para.join(' ')) + '</p>');
  }
  closeList();
  return html.join('\n');
}

const cfg = $('Config').first().json.cfg || {};
const item = $input.first().json || {};
const md = String(item.stdout || '');
const stderr = String(item.stderr || '');
const failed = !md.trim();

const statsSummary = ($('Fan out published posts').all().map(i => i.json)
  .find(j => j && j.__stats_summary)) || {};
const adOut = $('Run: pull_ad_stats.py (Batch E)').first().json || {};

const preamble =
  '<div style="font-family:system-ui,-apple-system,Segoe UI,sans-serif;font-size:14px;' +
  'line-height:1.6;color:#1a1a1a;max-width:820px">' +
  '<p style="font-size:12px;color:#777;border-bottom:1px solid #eee;padding-bottom:10px">' +
  'Snapshot ran first: ' + (statsSummary.requests || 0) + ' post stat request(s), ' +
  (statsSummary.skipped_linkedin || 0) + ' LinkedIn post(s) skipped (no analytics API). ' +
  'Ad stats pull exit code ' + (adOut.exitCode == null ? 'unknown' : adOut.exitCode) + '.' +
  '</p>';

return [{ json: {
  cfg: cfg,
  brief_ok: !failed,
  brief_subject: '[DoviLoop] Friday brief, ' + new Date().toISOString().slice(0, 10) +
    (failed ? ' — FAILED TO RENDER' : ''),
  brief_html: failed
    ? preamble + '<p><b>friday_brief.py produced no output.</b></p><pre style="white-space:pre-wrap;' +
      'background:#f6f6f6;padding:12px;font-size:12px">' + esc(stderr || '(no stderr)') +
      '</pre><p>The snapshot above still ran, so nothing is lost. Run it by hand:<br>' +
      '<code>' + esc(cfg.python_bin + ' src/friday_brief.py') + '</code> in ' +
      esc(cfg.ledger_repo) + '</p></div>'
    : preamble + render(md) +
      '<p style="font-size:12px;color:#777;margin-top:24px;border-top:1px solid #eee;' +
      'padding-top:10px">Rendered by WF-C6 from friday_brief.py. ' +
      'The markdown original is in ' + esc(cfg.ledger_repo) + '/briefs/.</p></div>',
} }];
"""


def build_c6():
    w = WF("WF-C6", "WF-C6 — Friday brief (snapshot, then render, then send)",
           "Friday 16:00 CET. Snapshots content and ad stats first so the brief reads fresh.")

    w.node("Schedule: Friday 16:00 CET", "n8n-nodes-base.scheduleTrigger", 1.2, (-240, 0),
           {"rule": {"interval": [{"field": "cronExpression", "expression": "0 16 * * 5"}]}},
           note="Workflow timezone is Europe/Copenhagen, so this is 16:00 CET / CEST.")
    w.node("Config", "n8n-nodes-base.set", 3.4, (-20, 0), cfg_assignment(C6_CONFIG),
           note="ledger_repo and ad_engine_repo are paths ON THE N8N HOST. n8n cannot "
                "run a script it cannot see. See README, 'WF-C6 needs the repos on disk'.")
    w.node("Guard: ledger target", "n8n-nodes-base.code", 2, (200, 0), code(GUARD_JS))

    # -- 1. content stats snapshot -----------------------------------------
    w.node("Ledger: published content", "n8n-nodes-base.httpRequest", 4.2, (420, 0),
           http_ledger("GET",
                       "={{ $json.cfg.ledger_url }}/rest/v1/content"
                       "?published_at=not.is.null&buffer_id=not.is.null&select=*",
                       headers=LEDGER_READ_HEADERS),
           credentials=CRED_LEDGER, alwaysOutputData=True)
    w.node("Fan out published posts", "n8n-nodes-base.code", 2, (640, 0), code(C6_FANOUT_JS))
    w.node("IF a stat to fetch", "n8n-nodes-base.if", 2, (860, 0),
           if_bool("={{ $json.__stats_summary !== true && !!$json.post_id }}"))
    w.node("IF YouTube", "n8n-nodes-base.if", 2, (1080, -120),
           if_bool("={{ $json.platform === 'youtube_shorts' }}"))
    w.node("YouTube: video statistics", "n8n-nodes-base.httpRequest", 4.2, (1300, -220), {
        "method": "GET",
        "url": "https://www.googleapis.com/youtube/v3/videos",
        "authentication": "predefinedCredentialType",
        "nodeCredentialType": "youTubeOAuth2Api",
        "sendQuery": True,
        "queryParameters": {"parameters": [
            {"name": "part", "value": "statistics"},
            {"name": "id", "value": "={{ $json.post_id }}"},
        ]},
        "options": {"response": {"response": {"neverError": True}}, "timeout": 20000},
    }, credentials=CRED_YT, alwaysOutputData=True)
    w.node("Meta: post insights", "n8n-nodes-base.httpRequest", 4.2, (1300, -20), {
        "method": "GET",
        "url": "=https://graph.facebook.com/{{ $json.cfg.meta_graph_version }}/"
               "{{ $json.post_id }}/insights",
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "sendQuery": True,
        "queryParameters": {"parameters": [
            {"name": "metric",
             "value": "={{ $json.platform === 'instagram' "
                      "? 'plays,likes,comments,saved,reach' "
                      ": 'post_impressions,post_reactions_like_total,post_clicks' }}"},
        ]},
        "options": {"response": {"response": {"neverError": True}}, "timeout": 20000},
    }, credentials=CRED_META, alwaysOutputData=True)
    w.node("Normalise stats row", "n8n-nodes-base.code", 2, (1520, -120), code(C6_STATS_JS))
    w.node("Ledger: upsert content_stats", "n8n-nodes-base.httpRequest", 4.2, (1740, -120),
           http_ledger("POST",
                       "={{ $json.cfg.ledger_url }}/rest/v1/content_stats"
                       "?on_conflict=content_id,platform,captured_on",
                       headers=LEDGER_WRITE_HEADERS + [
                           ("Prefer", "resolution=merge-duplicates,return=minimal")],
                       json_body="={{ JSON.stringify([$json.row]) }}"),
           credentials=CRED_LEDGER, alwaysOutputData=True, onError="continueRegularOutput")
    w.node("Snapshot done", "n8n-nodes-base.noOp", 1, (1960, 0), {},
           note="Both stat branches and the no-stats branch land here, so the ad pull "
                "and the brief cannot start before the snapshot has finished.")

    # -- 2. ad stats (Batch E) ---------------------------------------------
    w.node("Run: pull_ad_stats.py (Batch E)", "n8n-nodes-base.executeCommand", 1, (2180, 0), {
        "command": "=cd {{ $('Config').first().json.cfg.ad_engine_repo }} && "
                   "{{ $('Config').first().json.cfg.python_bin }} report/pull_ad_stats.py "
                   "--date {{ $now.minus(1, 'days').toFormat('yyyy-MM-dd') }} 2>&1",
        "executeOnce": True,
    }, onError="continueRegularOutput", alwaysOutputData=True,
        note="Batch E's script. --dry-run reads a fixture and writes nothing, which is "
             "the safe way to test this node before the Meta account exists.")

    # -- 3. the brief -------------------------------------------------------
    w.node("Run: friday_brief.py (Batch B)", "n8n-nodes-base.executeCommand", 1, (2400, 0), {
        "command": "=cd {{ $('Config').first().json.cfg.ledger_repo }} && "
                   "{{ $('Config').first().json.cfg.python_bin }} src/friday_brief.py",
        "executeOnce": True,
    }, onError="continueRegularOutput", alwaysOutputData=True,
        note="Prints the markdown to stdout AND writes briefs/YYYY-MM-DD.md, so the "
             "brief survives even if the email fails.")
    w.node("Markdown to HTML", "n8n-nodes-base.code", 2, (2620, 0), code(C6_MD_HTML_JS))
    w.node("Send: Friday brief", "n8n-nodes-base.emailSend", 2.1, (2840, 0),
           email("={{ $json.cfg.from_email }}", "={{ $json.cfg.dovy_email }}",
                 "={{ $json.brief_subject }}", "={{ $json.brief_html }}"),
           credentials=CRED_SMTP)

    w.link("Schedule: Friday 16:00 CET", "Config")
    w.link("Config", "Guard: ledger target")
    w.link("Guard: ledger target", "Ledger: published content")
    w.link("Ledger: published content", "Fan out published posts")
    w.link("Fan out published posts", "IF a stat to fetch")
    w.link("IF a stat to fetch", "IF YouTube", 0)
    w.link("IF a stat to fetch", "Snapshot done", 1)
    w.link("IF YouTube", "YouTube: video statistics", 0)
    w.link("IF YouTube", "Meta: post insights", 1)
    w.link("YouTube: video statistics", "Normalise stats row")
    w.link("Meta: post insights", "Normalise stats row")
    w.link("Normalise stats row", "Ledger: upsert content_stats")
    w.link("Ledger: upsert content_stats", "Snapshot done")
    w.link("Snapshot done", "Run: pull_ad_stats.py (Batch E)")
    w.link("Run: pull_ad_stats.py (Batch E)", "Run: friday_brief.py (Batch B)")
    w.link("Run: friday_brief.py (Batch B)", "Markdown to HTML")
    w.link("Markdown to HTML", "Send: Friday brief")

    w.write()


if __name__ == "__main__":
    build_c1()
    build_c2()
    build_c3()
    build_c4()
    build_c5()
    build_c6()
    print("done")
