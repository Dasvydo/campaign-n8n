# ACTIVATION PRECHECK

Everything that must exist, be named, or be filled in **before** the six
workflows in `workflows/` are imported into a live n8n instance.

Every fact below was read out of the exported JSON in this repo, not out of
prose. Where this document disagrees with a narrative document, the export
wins — it is what n8n actually imports.

**Nothing here has been imported, activated, or called.** This document was
produced from a clean clone with `node`, `python3` and `git` only.

Ordered by the activation order in `README.md#activation-order`:
**WF-C1 → WF-C2 → WF-C6 → WF-C3 → WF-C4 → WF-C5.** That is a dependency
order, not a preference: WF-C1 is what fills the ledger the others read,
WF-C2 is what makes the unsubscribe link in its own emails resolve, and
WF-C6 needs only the two credentials the first stage already required.

---

## READ THIS FIRST — every webhook is unauthenticated, in public

This is parked decision **P-4** in `ops/DECISIONS.md`. It is described here,
not fixed here. Do not treat the rest of this document as a green light until
P-4 is settled.

**All eight webhook bindings carry no authentication.** Not "authentication is
set to none" — the `authentication` key is *absent* from all eight webhook
nodes' parameters, which is n8n's `None` default. Verified across all six
exports:

| # | Workflow | Node | Method | Path | `authentication` key |
|---|---|---|---|---|---|
| 1 | WF-C1 | Webhook — qualifier | POST | `campaign/qualifier` | **absent → None** |
| 2 | WF-C2 | Webhook — record opt-in | POST | `campaign/nurture-optin` | **absent → None** |
| 3 | WF-C2 | Webhook — unsubscribe | GET | `campaign/unsubscribe` | **absent → None** |
| 4 | WF-C3 | Webhook — approve content | POST | `campaign/content-approve` | **absent → None** |
| 5 | WF-C4 | Webhook — Meta verify | GET | `campaign/meta-comments` | **absent → None** |
| 6 | WF-C4 | Webhook — Meta comments | POST | `campaign/meta-comments` | **absent → None** |
| 7 | WF-C4 | Webhook — approve DM | GET | `campaign/meta-dm-approve` | **absent → None** |
| 8 | WF-C5 | Webhook — Stripe events | POST | `campaign/stripe` | **absent → None** |

Eight bindings on **seven distinct paths** — `campaign/meta-comments` is bound
twice, GET for Meta's `hub.challenge` handshake and POST for comment events.

**Five of the six campaign repos are public**, `campaign-n8n` among them. This
repo publishes both halves of every URL: the n8n hostname is in
`README.md:366` (`N8N=https://viniflow-u57383.vm.elestio.app`), and the paths
are in the exports above. Once a workflow is activated, the full production URL
of its endpoint is publicly derivable and accepts an unauthenticated request.

**The sharpest case is `campaign/content-approve`.** This repo's own README
calls WF-C3's gate "the one that matters most because it is what publishes in
public", and the node's own `notes` field reads: *"The ONLY way a reel becomes
publishable. Fails closed without it."* That gate is a POST webhook with no
token check. Its output is appended to `content-approvals.jsonl` by an
unauthenticated request; anything that reaches it is approved for Instagram,
Facebook, YouTube Shorts and LinkedIn. `campaign/meta-dm-approve` is the same
shape for outbound DMs.

Two further details, both read from the exports:

- `campaign/qualifier` also sets `options.allowedOrigins: "*"`.
- WF-C5 checks the `stripe-signature` header for **presence**, not validity.
  That is a deliberate trade documented in `CREDENTIALS.md` (WF-C5 re-fetches
  the event from Stripe over the authenticated API and never trusts the body),
  but it is not signature verification, and `campaign/stripe` accepts any POST.

`campaign/meta-comments` legitimately must stay open — Meta calls it, and it is
verified by Meta's own challenge handshake.

**Do not read past this section as "ready to activate".** See P-4 in
`ops/DECISIONS.md` for the options and why none were taken autonomously.

---

## Cross-check: credentials in the exports vs `CREDENTIALS.md`

**Result: zero discrepancies.** Seven credential names are referenced across
the six exports; `CREDENTIALS.md` documents exactly those seven. Nothing is
referenced-but-undocumented, and nothing is documented-but-unreferenced. The
per-workflow "Used by" column in `CREDENTIALS.md` also matches node-for-node.

The exports carry credential **names only** — `validate.mjs` asserts on every
run that nothing but `{ name }` appears under a `credentials` key. n8n matches
by name at import time, so **a name that does not match exactly is a silent
failure at run time**, not an import error.

| Name in n8n (exact) | Type key in JSON | Nodes | Workflows |
|---|---|---|---|
| `DoviLoop campaign SMTP` | `smtp` | 13 | C1, C2, C3, C4, C5, C6 |
| `Campaign Ledger (Supabase, campaign schema)` | `supabaseApi` | 9 | C1, C3, C4, C5, C6 |
| `Meta Graph API page token` | `httpHeaderAuth` | 5 | C3, C4, C6 |
| `YouTube Data API (campaign)` | `youTubeOAuth2Api` | 2 | C3, C6 |
| `Stripe secret key (campaign)` | `httpHeaderAuth` | 2 | C5 |
| `Buffer API token` | `httpHeaderAuth` | 1 | C3 |
| `LinkedIn (campaign posting)` | `linkedInOAuth2Api` | 1 | C3 |

Two credentials — SMTP and the Supabase ledger — gate the entire first stage.
Everything else can wait until the account it belongs to exists.

---

## Instance-wide, before any import

- **Exposed schema.** The ledger lives in Postgres schema `campaign`, not
  `public`. Supabase → Settings → API → Exposed schemas → add `campaign`.
  Without it every ledger call in C1, C3, C4, C5 and C6 returns
  `PGRST106 schema must be one of the following`.
- **Ledger project must be the campaign project** `oqpeebtwtikdzorgouxd`, never
  the product project `kngcxwcybozgqgnoweyt`. **Four** workflows carry a
  `Guard: ledger target` node that throws on the product ref — C1, C3, C5, C6 —
  proved by `test/run-code-nodes.mjs`. Do not remove those nodes.
  **Five workflows touch the ledger. WF-C4 is the one without a guard** (see
  its section below), so its `ledger_url` is the one value in this campaign you
  have to check by eye.
- **`data_dir` must exist and be writable by the n8n process.** All six Config
  nodes ship `data_dir: '/home/node/.n8n/campaign'`, and eight append-only
  files are written under it. This directory is not created by the import:

  | File | Written by | What is lost if the path is not writable |
  |---|---|---|
  | `dead-letter.jsonl` | C1 | failed ledger writes |
  | `parked-under-10.jsonl` | C1 | under-10-seat leads |
  | `opt-outs.jsonl` | C2 | **the suppression list** |
  | `nurture-parked.jsonl` | C2 | leads held for missing consent |
  | `content-approvals.jsonl` | C3 | **the approval list WF-C3 publishes from** |
  | `dm-drafts.jsonl` | C4 | pending DM drafts |
  | `social-dm-touches.jsonl` | C4 | the 90-day per-person rate limit |
  | `day14-links.jsonl` | C5 | the checkout links created for Dovy |
- **Timezone.** All six exports set `settings.timezone: "Europe/Copenhagen"`.
  Every cron below is wall-clock in Copenhagen (CET/CEST), so the UTC offset
  moves with DST.
- **All six ship `active: false`** — asserted by `test/run-code-nodes.mjs` for
  each workflow. Importing them activates nothing; you activate deliberately.
- **Execute Command node must be available.** WF-C6 uses two
  `n8n-nodes-base.executeCommand` nodes. That node does not exist on n8n Cloud
  and can be disabled by `NODES_EXCLUDE` on a self-hosted instance. The
  documented host is self-hosted (Elestio), so this should hold — confirm it
  before Stage 1 rather than at 16:00 on a Friday.
- **Path collision: CHECKED AND CLEAR, 2026-09-10.** Queried the live instance
  directly (`GET /api/v1/workflows?limit=250`): 125 workflows, 21 active, 47
  bound webhook paths, and **not one begins `campaign/`**. All eight paths this
  repo needs are free. `BLOCKED.md` F-2 carries the full list. Nothing to do
  here any more.
- **The campaign shares its n8n instance with the live product.** Same host as
  WF1, WF4, WF5-v2, WF6, WF9 and the needs-you redraft path. Activate one at a
  time and watch a full run of each, per the order below - that advice was
  already here, and this is the reason it matters.

---

# 1. WF-C1 — Qualifier intake (`teams.doviloop.dev`)

24 nodes, 1 trigger. Stage 1. Needs only SMTP + Supabase.

**Credentials**

| Credential | Node |
|---|---|
| `Campaign Ledger (Supabase, campaign schema)` | Ledger: upsert lead |
| `DoviLoop campaign SMTP` | Send: new lead |
| `DoviLoop campaign SMTP` | Send: malformed submission |
| `DoviLoop campaign SMTP` | Send: ledger write failed |

**Webhooks**

| Method | Path | Auth | Respond mode | Notes |
|---|---|---|---|---|
| POST | `campaign/qualifier` | **None** | `responseNode` | `options.allowedOrigins: "*"`, `rawBody: false` |

**Schedules** — none. Webhook-driven only.

**Sibling scripts** — none.

**Config fields — nothing is blank, but three values must be confirmed**

```
ledger_url        'https://oqpeebtwtikdzorgouxd.supabase.co'   confirm: campaign, not product
dovy_email        'hello@doviloop.dev'                          confirm: accepts mail
from_email        'campaign-bot@doviloop.dev'                   confirm: accepts mail
data_dir          '/home/node/.n8n/campaign'                    confirm: exists, writable
dedupe_ttl_hours  72                                            prefilled
```

**After activation, one manual step outside n8n.** Copy this webhook's
**Production URL** into Batch A's `VITE_LEAD_WEBHOOK_URL` in Vercel. The node's
own `notes` says so. Until that is set, every lead sits in the visitor's
browser localStorage queue and nothing reaches the ledger.

---

# 2. WF-C2 — Under-10 nurture (opt-in gated, English only)

27 nodes, 3 triggers. Stage 1. Needs only SMTP.

**Credentials**

| Credential | Node |
|---|---|
| `DoviLoop campaign SMTP` | Send email 1 (day 0) |
| `DoviLoop campaign SMTP` | Send email 2 (day 4) |
| `DoviLoop campaign SMTP` | Send email 3 (day 11) |
| `DoviLoop campaign SMTP` | Send: someone unsubscribed |

No ledger credential: WF-C2 never touches Supabase.

**Webhooks**

| Method | Path | Auth | Respond mode | Notes |
|---|---|---|---|---|
| POST | `campaign/nurture-optin` | **None** | `lastNode` | For a *future* server-side opt-in capture. Batch A's current opt-in is a `mailto:` and never reaches this. |
| GET | `campaign/unsubscribe` | **None** | `responseNode` | One click, no confirm step — the "trivially easy to stop" requirement. |

**Schedules** — none. The third trigger is a manual start
(`Start: called with a lead + opt-in`); WF-C1 deliberately does **not** call it.

**Sibling scripts** — none.

**Config fields — two blanks BLOCK activation, one gates Denmark**

```
unsubscribe_base            ''      *** BLANK — must be filled before activating ***
postal_address              ''      *** BLANK — must be filled before activating ***
dk_marketing_law_confirmed  false   *** gates all Danish email — see below ***
from_email                  'dovy@doviloop.dev'      (a human wrote these; a human gets the replies)
reply_to                    'hello@doviloop.dev'
pricing_url                 'https://doviloop.dev/pricing'
ledger_url / dovy_email / data_dir   prefilled
```

The Config node's own `notes` field says it outright: *"unsubscribe_base and
postal_address must both be filled before this workflow is activated."*
Nothing throws if they are blank — the unsubscribe URL is built by string
concatenation, so a blank base produces a broken link in all three emails, and
a blank postal address silently omits the postal-address block.

## `dk_marketing_law_confirmed` — the two-key gate on Danish email

**Both keys are required. Neither alone is enough.** This is enforced in
WF-C2's consent-gate Code node, which reads:

```
if (String(lead.market || '') === 'dk') {
  if (optin.dk_marketing_law_confirmed !== true)  → parked
  if (cfg.dk_marketing_law_confirmed   !== true)  → parked
}
```

| Key | Where you set it | Scope |
|---|---|---|
| `cfg.dk_marketing_law_confirmed` | **WF-C2's Config node**, in n8n | instance-wide, once |
| `optin.dk_marketing_law_confirmed` | **on the lead**, in the `optin` object passed in | per lead |

Set the Config flag and leave it off a Danish lead: parked, nothing sent. Set
it on the lead and leave Config `false`: parked, nothing sent. The node's own
error text explains why — *"Denmark needs Dovy to confirm the marketing-law
position once, in Config, before ANY Danish address can be emailed by this
campaign."*

The gate has five further requirements that apply to **every** market, not just
Denmark, and all five must be present or the lead is parked and nothing is
sent: `optin.granted === true`, a non-empty `optin.source`, a non-empty
`optin.evidence`, an ISO-8601 `optin.recorded_at`, and an `optin.work_email`
that matches the lead's `work_email`. A previously unsubscribed address is
never re-enrolled.

Parking is the correct outcome, not an error — the node named
`Park: no opt-in, send nothing` says so.

---

# 3. WF-C6 — Friday brief (snapshot, then render, then send)

16 nodes, 1 trigger. Stage 1. **This is the only workflow that leaves n8n and
this repo entirely.**

**Credentials**

| Credential | Node |
|---|---|
| `Campaign Ledger (Supabase, campaign schema)` | Ledger: published content |
| `Campaign Ledger (Supabase, campaign schema)` | Ledger: upsert content_stats |
| `YouTube Data API (campaign)` | YouTube: video statistics |
| `Meta Graph API page token` | Meta: post insights |
| `DoviLoop campaign SMTP` | Send: Friday brief |

The two stats credentials are Stage-2 accounts. Without them the brief still
sends — the no-stats branch joins at `Snapshot done`.

**Webhooks** — none.

**Schedules**

| Cron | In plain English |
|---|---|
| `0 16 * * 5` | 16:00 every Friday, Europe/Copenhagen (CET/CEST) |

**Sibling scripts — both run on the n8n host, in repos beside this one**

| Node | Command shape | Script | Repo (batch) |
|---|---|---|---|
| Run: pull_ad_stats.py (Batch E) | `cd {{cfg.ad_engine_repo}} && {{cfg.python_bin}} report/pull_ad_stats.py --date <yesterday> 2>&1` | `report/pull_ad_stats.py` | **ad-engine** (E) |
| Run: friday_brief.py (Batch B) | `cd {{cfg.ledger_repo}} && {{cfg.python_bin}} src/friday_brief.py` | `src/friday_brief.py` | **campaign-ledger** (B) |

Both paths are verified against real checkouts by
`node tools/check-sibling-invocations.mjs`, which parses the commands out of
the export rather than hardcoding them. With the siblings absent it skips
loudly and verifies nothing.

Ordering is enforced, not incidental: `Snapshot done` collects both stat
branches *and* the no-stats branch, so the ad pull and the brief cannot start
before the snapshot has finished. Three assertions in
`test/run-code-nodes.mjs` cover this.

**Config fields — three host paths you must set by hand**

```
python_bin      'python3'                        confirm it resolves for the n8n user
ledger_repo     '/opt/campaign/campaign-ledger'  *** must be a real checkout ON THE N8N HOST ***
ad_engine_repo  '/opt/campaign/ad-engine'        *** must be a real checkout ON THE N8N HOST ***
meta_graph_version 'v21.0'
ledger_url / dovy_email / from_email / data_dir   prefilled
```

The Config node's `notes` field: *"ledger_repo and ad_engine_repo are paths ON
THE N8N HOST. n8n cannot run a script it cannot see."*

**Environment variables — set in the n8n *process* environment, not in Config**

These are read by the sibling scripts, not by n8n, so they cannot be set from
a Config node. No workflow in this repo references `$env` at all.

| Variable | Read by | Consequence if unset |
|---|---|---|
| `SUPABASE_URL` | `campaign-ledger/src/campaign_db.py` | `friday_brief.py` cannot reach the ledger |
| `SUPABASE_SERVICE_KEY` | `campaign-ledger/src/campaign_db.py` | same — **note the name**: `SERVICE_KEY`, not `SERVICE_ROLE_KEY` |
| `META_AD_ACCOUNT_ID` | `ad-engine/report/pull_ad_stats.py` | script logs an error and **exits 2**; no ad numbers in the brief |
| `META_ACCESS_TOKEN` | `ad-engine/report/pull_ad_stats.py` | same |

Both must point at the **campaign** project; `campaign_db.py` refuses to
connect if the URL is the product project.

**No pip install is needed for these two scripts.** Both import standard
library only. Each sibling repo has a `requirements.txt`, but in both cases
every entry is test-only (`sqlglot` for campaign-ledger's SQL parse check,
`Pillow`/`pytest` for ad-engine's suite).

`friday_brief.py` also **writes** `briefs/YYYY-MM-DD.md` inside the ledger
checkout, so that directory must be writable by the n8n user — the brief
survives on disk even if the email fails.

**If either script is missing or fails, WF-C6 still emails Dovy** with the
stderr and the command to run by hand. A silent empty brief would be worse than
a loud broken one; `test/run-code-nodes.mjs` asserts this.

---

# 4. WF-C3 — Publish approved reels (Buffer, with a real fallback)

37 nodes, 2 triggers. Stage 2. **The only workflow in the campaign that
publishes in public.**

**Credentials** — which ones you need depends on `publisher`

| Credential | Node | Needed on path |
|---|---|---|
| `Campaign Ledger (Supabase, campaign schema)` | Ledger: read unpublished content | both |
| `Campaign Ledger (Supabase, campaign schema)` | Ledger: mark published | both |
| `DoviLoop campaign SMTP` | Send: Thursday report | both |
| `Buffer API token` | Buffer: createPost | `buffer` only |
| `Meta Graph API page token` | IG: create reel container | `direct` only |
| `Meta Graph API page token` | IG: publish container | `direct` only |
| `Meta Graph API page token` | FB page: post video | `direct` only |
| `YouTube Data API (campaign)` | YouTube: upload short | `direct` only |
| `LinkedIn (campaign posting)` | LinkedIn: post video | `direct` only |

**Webhooks**

| Method | Path | Auth | Respond mode |
|---|---|---|---|
| POST | `campaign/content-approve` | **None** | `lastNode` |

See the P-4 section at the top. This is the gate.

**Schedules**

| Cron | In plain English |
|---|---|
| `0 8 * * 4` | 08:00 every Thursday, Europe/Copenhagen (CET/CEST) |

**Sibling scripts** — none.

**Config fields — six blanks**

```
publisher         'buffer'    choose: 'buffer' or 'direct'. Both paths are fully built.
buffer_channels.instagram       ''   *** BLANK, required on the buffer path ***
buffer_channels.facebook        ''   *** BLANK, required on the buffer path ***
buffer_channels.youtube_shorts  ''   *** BLANK, required on the buffer path ***
buffer_channels.linkedin        ''   *** BLANK, required on the buffer path ***
ig_user_id        ''   *** BLANK, required on the direct path — Instagram Business Account ID ***
fb_page_id        ''   *** BLANK, required on the direct path ***
asset_base_url    ''   *** BLANK — used to build the asset URL when the row carries a relative path ***
buffer_api_url    'https://graph.buffer.com/'
meta_graph_version 'v21.0'
ledger_url / dovy_email / from_email / data_dir   prefilled
```

Choosing `publisher` first tells you which blanks you actually have to fill.
Buffer's API is not on every plan; if yours does not expose it, set `'direct'`
and nothing else changes — except that the direct path cannot post **video** to
LinkedIn (`BLOCKED.md` F-11), and LinkedIn is the only channel Danish and
Lithuanian reels go to. Prefer Buffer if the plan allows it.

Buffer returns errors as **HTTP 200 with a typed error body** — the status code
proves nothing, only a post id does. That is what `Interpret Buffer response`
is for; do not simplify it away.

---

# 5. WF-C4 — Comment keyword to DM (approval gated)

25 nodes, 3 triggers. Stage 2.

**Credentials**

| Credential | Node |
|---|---|
| `Campaign Ledger (Supabase, campaign schema)` | Ledger: find the reel |
| `DoviLoop campaign SMTP` | Send: approve this DM |
| `Meta Graph API page token` | Meta: send private reply |

**Webhooks**

| Method | Path | Auth | Respond mode | Notes |
|---|---|---|---|---|
| GET | `campaign/meta-comments` | **None** | `responseNode` | Meta's `hub.challenge` verification, called once at subscription |
| POST | `campaign/meta-comments` | **None** | `onReceived` | Meta needs a 200 within seconds, so this answers first and works afterwards |
| GET | `campaign/meta-dm-approve` | **None** | `responseNode` | the link in Dovy's approval email |

**Activate before subscribing** the Meta comments webhook, so the
`hub.challenge` verification has something to answer.

**Schedules** — none.

**Sibling scripts** — none.

**Config fields — three blanks, in TWO Config nodes**

WF-C4 has **two** Set nodes named `Config` and `Config approve`, one per
entry path. They are byte-identical today. **Edit both, or the approval link
path will run against stale values.**

```
ig_user_id     ''   *** BLANK — Instagram Business Account ID ***
fb_page_id     ''   *** BLANK ***
approve_base   ''   *** BLANK — the approval URL in Dovy's email is built by concatenation ***
landing_url    'https://teams.doviloop.dev'
keywords       ['draft','drafts','demo','outlook','info']
rate_limit_days 90
meta_graph_version 'v21.0'
ledger_url / dovy_email / from_email / data_dir   prefilled
```

**`ledger_url` in WF-C4 is unguarded — check it by eye, in both Config nodes.**
WF-C4 reads the ledger (`Ledger: find the reel`, a GET against
`{{cfg.ledger_url}}/rest/v1/content`, on the Supabase credential) but is the
only ledger-touching workflow with **no** `Guard: ledger target` node. C1, C3,
C5 and C6 all throw on the product project ref; C4 would not. The read is a
GET and the credential is the campaign one, so the blast radius is small — but
the refusal that protects the other four is genuinely absent here.

There is no path from a comment to a DM that does not pass through Dovy
clicking the link in the approval email. A blank `approve_base` produces a
broken link, which fails closed — no DM is sent.

---

# 6. WF-C5 — Pilot day 14 (creates a link, never charges)

28 nodes, 2 triggers. Stage 3. Activate with a Stripe **test** key and watch
one full run first.

**Credentials**

| Credential | Node |
|---|---|
| `Campaign Ledger (Supabase, campaign schema)` | Ledger: pilots due in 2 days |
| `Campaign Ledger (Supabase, campaign schema)` | Ledger: pilots due today |
| `Campaign Ledger (Supabase, campaign schema)` | Ledger: mark converted |
| `Stripe secret key (campaign)` | Stripe: create checkout session |
| `Stripe secret key (campaign)` | Stripe: re-fetch the event |
| `DoviLoop campaign SMTP` | Send: day 12 reminder |
| `DoviLoop campaign SMTP` | Send: link for Dovy to send |
| `DoviLoop campaign SMTP` | Send: a pilot converted |

Use a **restricted** Stripe key: Checkout Sessions *write*, Events *read*,
everything else `none`. That turns "this workflow must never charge anyone"
from a comment into something the key enforces.

**Webhooks**

| Method | Path | Auth | Respond mode |
|---|---|---|---|
| POST | `campaign/stripe` | **None** | `onReceived` |

In Stripe → Developers → Webhooks, subscribe the endpoint to
`checkout.session.completed` and `invoice.paid`. **There is deliberately no
signing secret** — the workflow takes only the event id from the body and
re-fetches the event over the authenticated API.

**Schedules**

| Cron | In plain English |
|---|---|
| `0 9 * * *` | 09:00 every day, Europe/Copenhagen (CET/CEST) |

**Sibling scripts** — none.

**Config fields — two blanks that hard-block, in TWO Config nodes**

WF-C5 has **two** Set nodes named `Config` and `Config webhook`, one per entry
path, byte-identical today. **Edit both.**

```
price_seat_monthly ''    *** BLANK — Stripe Price id, 89 USD/seat, recurring monthly ***
price_setup_once   ''    *** BLANK — Stripe Price id, 500 USD, one-off ***
usd_eur_rate       null  intentional — see the currency note in 'Apply the Stripe event'
stripe_api  'https://api.stripe.com/v1'
success_url 'https://doviloop.dev/welcome'
cancel_url  'https://doviloop.dev'
ledger_url / dovy_email / from_email / data_dir   prefilled
```

Unlike the other blanks in this document, these two **fail loudly**.
`Build the Stripe request` pushes `'Config.price_seat_monthly is blank'` and
`'Config.price_setup_once is blank'` onto a `problems` list and refuses to
build the request — as it also does when `seats < 10`, because the offer does
not exist below ten seats.

`Guard: the link goes to Dovy only` throws rather than send if the recipient is
not Dovy. The checkout link is created for Dovy to forward by hand; creating a
session moves no money and emails nobody.

---

## What this document does not cover

- **`sql/004_consent.sql` is NOT RUN and NOT APPLIED**, deliberately. Where it
  should live is parked decision **P-3**. Dovy runs migrations, not n8n.
- Six decisions **P-1 … P-6** are parked in `ops/DECISIONS.md` for the founder.
  None was acted on here.
- Nothing in this repo was imported into n8n, and no live API was called, to
  produce this document.
