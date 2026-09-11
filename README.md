# campaign-n8n

The wiring for the DoviLoop Teams campaign. Six importable n8n workflows joining
the landing page, the campaign ledger, Buffer, Meta, YouTube, LinkedIn, Stripe
and Dovy's inbox.

Every export is **inactive**, carries **no credential value**, and carries **no
top-level `id`**, so importing one can never overwrite an existing workflow.

```
workflows/WF-C1.json   qualifier intake            24 nodes
workflows/WF-C2.json   under-10 nurture            27 nodes   opt-in gated
workflows/WF-C3.json   publish approved reels      37 nodes   Buffer + fallback
workflows/WF-C4.json   comment keyword to DM       25 nodes   approval gated
workflows/WF-C5.json   pilot day 14                28 nodes   never charges
workflows/WF-C6.json   Friday brief                16 nodes
```

---

# READ THIS FIRST: consent, and why the nurture does not start by itself

The spec for this batch says a `too_small` lead (1-9 seats) "enters a 3-email
nurture" automatically. **It does not, and it must not.** This is the one place
where following the spec literally would have created a legal exposure, and
three separate batches reached the same conclusion independently.

**The facts, each one checked against code and not against prose:**

1. The shared qualifier contract has eleven fields and **not one of them is a
   consent field** (`campaign-site/src/lib/contract.ts`). Nothing that arrives
   at WF-C1's webhook says this person agreed to receive marketing email.
2. **Batch A refused to auto-enrol.** The 1-9 result screen shows an explicit
   opt-in button, "Send me the three emails". That button is a **`mailto:`** to
   `hello@doviloop.dev` (`Qualifier.tsx`, `nurtureHref`). It does not post to
   any webhook, so even the genuine opt-in never reaches n8n on its own.
3. **Batch B raised the same gap** and has no consent column and no opt-out
   column on `campaign.leads`. There is nowhere in the ledger to record the
   answer.
4. **Denmark.** This campaign bans Danish cold email outright, and the stated
   reason is that Danish marketing law is stricter than the rest of the EU on
   unsolicited commercial email. Enrolling a Danish address off a form that
   never asked is exactly the exposure that ban exists to prevent.

**What is built instead:**

- **WF-C1 parks a `too_small` lead.** It writes the lead to `campaign.leads`
  with stage `too_small`, appends a line to `parked-under-10.jsonl`, and starts
  nothing. It does not call WF-C2. There is no connection between them.
- **WF-C2's consent gate** requires all five of `optin.granted === true`,
  `optin.source`, `optin.evidence`, `optin.recorded_at`, and an
  `optin.work_email` that matches the lead. Any one missing and the lead is
  parked and nothing is sent.
- **Denmark needs two more.** `optin.dk_marketing_law_confirmed === true` on the
  lead, **and** `dk_marketing_law_confirmed: true` in WF-C2's Config, which
  Dovy sets once, by hand, after he has confirmed the Danish position. Neither
  alone is enough.
- **An unsubscribed address can never be re-enrolled**, and the suppression list
  is re-checked before **every** send, not just the first, so someone who
  unsubscribes on day 5 does not get email 3 on day 11.

The practical consequence: **the nurture is manual today.** The opt-in lands in
Dovy's inbox as an email he can read. He starts WF-C2 by hand with the lead and
the opt-in evidence. That is the correct amount of friction for sending
marketing email to someone who never agreed on the record.

To make it automatic: change Batch A's opt-in button from a mailto to a POST at
`campaign/nurture-optin` carrying those five fields, and run
`sql/004_consent.sql` so the consent record lives in the ledger. About 15
minutes of Dovy's time. Logged as F-4 in `BLOCKED.md`.

---

## Import order

Order matters only because WF-C1 is the one Batch A needs a URL from.

1. **WF-C1** — qualifier intake
2. **WF-C2** — nurture
3. **WF-C6** — Friday brief
4. **WF-C3** — reel publishing
5. **WF-C4** — comment to DM
6. **WF-C5** — Stripe day 14

In n8n: **Workflows → Import from File**, one at a time.

After each import, open the **Config** node (a Set node, second from the left)
and fill it in. **`ledger_url` ships as `https://yheilbuunzdugfnermfb.supabase.co`**,
the campaign ledger project, confirmed by Dovy on 2026-09-06 (schema
`campaign`; the credential in `CREDENTIALS.md` §1 points at the same project).
Every workflow that touches the ledger still runs a `Guard: ledger target` node
that throws if the URL is blank, if it is not https, or if it contains the
product project ref `kngcxwcybozgqgnoweyt`. That guard mirrors the refusal
Batch B built into `campaign_db.py`. Do not remove it.

### Config values, per workflow

| Workflow | Must fill before it works |
|---|---|
| C1 | `dovy_email`, `from_email`, `data_dir` |
| C2 | `postal_address`, `from_email` — `unsubscribe_base` is now prefilled |
| C3 | `publisher`, `buffer_channels` **or** `ig_user_id` + `fb_page_id`, `asset_base_url` |
| C4 | `ig_user_id`, `fb_page_id`, `keywords` — `approve_base` is now prefilled |
| C5 | `price_seat_monthly` (the 89 USD per seat per month Price), `price_setup_once` (the 500 USD one-off Price), `success_url`, `cancel_url`, and eventually `usd_eur_rate` |
| C6 | `ledger_repo`, `ad_engine_repo`, `python_bin` |

`ledger_url` is pre-filled in all six with the confirmed campaign project and
only needs changing if the ledger ever moves.

`unsubscribe_base` and `approve_base` **are no longer blank.** They used to be
described here as chicken-and-egg — import, copy the production URL off the
webhook node, paste it back — but they never were. A production webhook URL is
`<host>/webhook/<path>`, and both halves are known before the import: the path
is written in this repo's own exports and the host is the instance you import
into. So both are built in `tools/build_workflows.py` from one constant:

```python
N8N_WEBHOOK_BASE = "https://viniflow-u57383.vm.elestio.app/webhook"
```

**If you import into a different instance, change that constant and rebuild** —
do not edit the exports. It is the only place either URL is written, so WF-C4's
two Config nodes cannot drift apart.

⚠️ The editor's **Test URL** is `<host>/webhook-test/<path>` and only listens
while "Listen for test event" is open. A link built on it works once, for
whoever is watching the canvas, and 404s for the person who got the email.
These two values are emailed to real recipients — they must be `/webhook/`.

## Activation order

Activate in stages, not all at once. Nothing below is urgent, and every stage
except the first can wait for an account to exist.

**Stage 1, day one — needs only Supabase and SMTP**

1. `WF-C1` Once it is active, copy the webhook's **Production URL** into Batch
   A's `VITE_LEAD_WEBHOOK_URL` in Vercel. Until that is set, every lead sits in
   the visitor's browser localStorage queue.
2. `WF-C2` Safe to activate immediately: it sends nothing without an opt-in, and
   activating it is what makes the unsubscribe link work.
3. `WF-C6` Needs `campaign-ledger` and `ad-engine` checked out on the n8n host
   (see below). Without them the brief still emails, saying which script failed
   and how to run it by hand.

**Stage 2, when the social accounts exist**

4. `WF-C3` Activate with `publisher: 'buffer'` first. If Buffer's API is not on
   the plan, change one Config value to `'direct'`.
5. `WF-C4` Needs the Meta comments webhook subscription, which needs an approved
   app. Activate it before subscribing so the `hub.challenge` verification has
   something to answer.

**Stage 3, before the first pilot reaches day 14**

6. `WF-C5` Activate with a Stripe **test** key and watch one full run first.

## Webhook paths

All seven are namespaced under `campaign/`. **Before activating, search the five
existing workflows (WF1, WF4, WF5, WF6, WF9) for `campaign/`** — this container
has no copy of them, so a path collision could not be ruled out from here
(`BLOCKED.md` F-2).

| Method | Path | Workflow | What it is |
|---|---|---|---|
| POST | `campaign/qualifier` | C1 | Batch A posts the lead here |
| POST | `campaign/nurture-optin` | C2 | future server-side opt-in capture |
| GET | `campaign/unsubscribe` | C2 | the unsubscribe link in all three emails |
| POST | `campaign/content-approve` | C3 | the only way a reel becomes publishable |
| GET | `campaign/meta-comments` | C4 | Meta's `hub.challenge` verification |
| POST | `campaign/meta-comments` | C4 | Meta comment events |
| GET | `campaign/meta-dm-approve` | C4 | the link in Dovy's approval email |
| POST | `campaign/stripe` | C5 | Stripe events |

## WF-C6 needs the repos on disk

WF-C6 shells out to two Python scripts owned by other batches:

- `campaign-ledger/src/friday_brief.py` (Batch B) renders the brief
- `ad-engine/report/pull_ad_stats.py` (Batch E) pulls Meta ad numbers

n8n cannot run a script it cannot see, so both repos need to be checked out on
the n8n host and their paths set in WF-C6's Config (`ledger_repo`,
`ad_engine_repo`). Both need `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` in the
n8n process environment, pointing at the **campaign** project. Note the variable
name: Batch B reads `SUPABASE_SERVICE_KEY`, not `SUPABASE_SERVICE_ROLE_KEY`, and
refuses to connect if the URL is the product project.

If either script is missing, WF-C6 still sends the email. It says which one
failed, shows the stderr, and gives the command to run by hand. A silent empty
brief would be worse than a loud broken one.

## Buffer or direct: the choice WF-C3 leaves open

One Config value, `publisher`, switches the whole publishing path.

| | `'buffer'` | `'direct'` |
|---|---|---|
| Credentials | one Buffer token | Meta + YouTube + LinkedIn |
| Instagram reels | yes | yes, three-call async flow |
| Facebook page | yes | yes |
| YouTube Shorts | yes | yes |
| LinkedIn **video** | yes | **no** — text plus a still frame only (F-11) |
| Scheduling | Buffer's queue | posts immediately |

**Buffer's API is not on every plan.** Build order per the spec was Buffer
first, so that is the default. If your plan does not expose it, set `'direct'`
and nothing else changes.

**Prefer Buffer if you can.** LinkedIn is the *only* channel Danish and
Lithuanian reels go to, and the direct path cannot post video to LinkedIn
(`BLOCKED.md` F-11), so two of three markets lose their video on that path.

### Buffer's most important behaviour, and why there is a whole node about it

Batch D found and documented it in `reel-engine/engine/publish.py`:

> Errors come back as HTTP 200 with a typed error body. A publisher that checks
> only the status code reports success on every failure.

So `Interpret Buffer response` never looks at the status code. A post counts as
created **only if the response carries a post id**. Instagram gets a third check
on top, because it is the one platform that can report a post while having only
sent a phone notification for someone to finish by hand: it is judged on
positive confirmation of auto-publishing, matched by exact case-folded equality,
and anything else fails closed.

## The approval gate on WF-C3

`campaign.content` has **no approval column**. The spec says to read content
"where `published_at` is null and an approval flag is set", and that flag does
not exist — Batch B's table is `id, kind, lane, language, hook, script_path,
asset_path, platforms, published_at, buffer_id, natural_key, created_at`, and
Batch D asserts the same list in its own tests. Batch D's approval lives in a
GitHub-issue queue on disk that n8n cannot see.

The tempting reading, "published_at is null and asset_path is set", would
publish every rendered reel automatically. **A render is not an approval**, and
this is the one workflow in the campaign that posts in public.

So WF-C3 keeps an explicit approval list, in workflow static data, written only
by the `campaign/content-approve` webhook, and **publishes nothing that is not
on it**. Every Thursday it emails Dovy what it held back and why.

```bash
curl -X POST "$N8N/webhook/campaign/content-approve" \
  -H 'Content-Type: application/json' \
  -d '{"natural_key":"reel:on_camera:en:the-mail-you-answer-twenty-times","approved_by":"dovy"}'
```

`{"natural_keys":[...]}` approves several. `{"natural_key":"...","revoke":true}`
takes one back. `sql/004_consent.sql` §2 proposes the column that would move
this into the ledger.

## What WF-C5 can and cannot do

The offer it prices is **500 USD one-off setup plus 89 USD per seat per month**
(confirmed 2026-09-06). The Checkout Session carries two line items: the
`price_seat_monthly` Price times `seats`, and the `price_setup_once` Price once.
The amounts live on the Stripe Prices, not in the workflow; the only numbers in
the workflow itself are the `89` in the MRR arithmetic and the wording of the
email to Dovy, and both say 89 and 500.

It can create a Stripe Checkout Session and email the link **to Dovy**. It
cannot charge anything. Four independent reasons, not one:

1. The only Stripe write in the workflow is `POST /v1/checkout/sessions`.
   Creating a session moves no money and emails nobody. Payment happens only
   when someone opens that URL and enters a card.
2. `FORBIDDEN_PARAMS` in the request builder throws if `off_session`, `confirm`
   or `setup_future_usage` ever appears in the body.
3. **`customer_email` is deliberately never set**, so Stripe holds no address
   for the client and cannot contact them even by misconfiguration.
4. `Guard: the link goes to Dovy only` throws rather than send if the recipient
   is not `cfg.dovy_email`, or if it equals the client's `work_email`. The Send
   node's `toEmail` is bound to the value that guard just checked, so editing it
   to a client address makes the workflow throw instead of sending.

Use a **restricted** Stripe key with exactly two permissions (Checkout Sessions:
write, Events: read). That turns the promise into something the key enforces.
See `CREDENTIALS.md` §7.

## What WF-C4 can and cannot do

A DM to somebody who left a comment is a message to a real person, so it goes
through the same approval gate as everything else. **The comment webhook cannot
reach the DM send node at all** — they are two disconnected subgraphs, and the
only path into the send node starts at the `campaign/meta-dm-approve` webhook,
which is the link in Dovy's email. There is no config switch that skips it,
because a toggle that turns the rule off is the same as not having the rule.
`test/run-code-nodes.mjs` asserts both of those as graph reachability, not as a
string search.

Rate limiting is belt and braces: an approval token is single-use and is burned
before the send call, the rate limit is stamped at the same moment, the limit is
re-checked at redemption as well as at match time, and Meta itself allows only
one private reply per comment.

The touch WF-C4 journals after a sent DM carries **no reply sentiment**
(`reply_sentiment: null`): it is the DM going out, not a reply coming in. If a
reply is ever classified and written back, the only legal values are the
ledger's `campaign.reply_sentiment` enum: `interested`, `not_now`, `not_a_fit`,
`referred`, `objection`, `unsubscribe` (decided 2026-09-06). WF-C6 does not
classify anything either; it renders whatever `friday_brief.py` prints, and that
script reads the same enum, so the brief uses the new values without any change
here.

---

## Test plan

Nothing here needs a real credential. Run these in order.

### 1. Structural validation, and proof the validator works (30 seconds)

```bash
node tools/validate.mjs                     # all six files
node tools/validate-selftest.mjs            # breaks real exports 18 ways, asserts each is caught (21 with 3 controls)
node tools/check-sibling-invocations.mjs    # WF-C6's two cross-repo scripts still exist
node tools/check-regen.mjs                  # the exports are byte-identical to what the builder emits
```

`check-sibling-invocations.mjs` covers the one thing the other two structurally
cannot: WF-C6 shells out of this repo entirely, running
`ad-engine/report/pull_ad_stats.py` and `campaign-ledger/src/friday_brief.py` on
the n8n host. A rename in either sibling leaves every check here green while the
Friday brief quietly produces nothing, and the first signal is an empty brief on
a Friday morning. It parses the paths out of the export rather than hardcoding
them, skips loudly when the siblings are not checked out beside this repo, and
fails if its own regex ever stops matching - a check that cannot fail being worse
than no check.

`check-regen.mjs` covers the other thing they structurally cannot: whether the
committed JSON is still what `tools/build_workflows.py` produces. "Never
hand-edit an export" was a request in prose and nothing enforced it — an edit
that happens to be structurally valid passes `validate.mjs`, the self-test and
the node harness, because all three read the committed JSON rather than the
source that is meant to generate it. The next rebuild then silently wipes the
edit. It copies the builder into a scratch tree (the builder derives its output
directory from its own `__file__`, so it writes there instead) and compares byte
for byte; it never writes into `workflows/`, on success or on failure. It also
fails on a file the builder emits but nobody committed, and on a file committed
that no builder function emits.

`validate.mjs` checks: valid JSON; `active` is exactly false; no top-level `id`;
every node has a name, unique id, type, typeVersion, `[x,y]` position and a
parameters object; every connection target exists; no node is unreachable from a
trigger; every workflow has a trigger; merge nodes declare enough inputs; every
credential reference carries only `{id, name}`; no JWT, Stripe key, Meta token,
Google API key or private key appears anywhere; the forbidden project ref appears
nowhere; none of the superseded reply sentiment values (`hot_pain`, `curious`,
`endorse`, `unrelated`, `ineligible`) appears anywhere, because the ledger enum
is now `interested, not_now, not_a_fit, referred, objection, unsubscribe` and
would reject them.

### 2. Run the real node code against the real payloads (5 seconds)

```bash
node test/run-code-nodes.mjs      # 130 assertions
```

This reads the Code node bodies **out of `workflows/*.json`** and executes them
in a small n8n shim, so they cannot drift from what n8n would import. It also
evaluates the real IF-node condition strings, so the routing tested is the
routing that ships. It proves, among other things: a malformed payload is
rejected but preserved whole; the dedupe key comes from the header when present
and the derived key when not; a `too_small` lead is parked; Denmark cannot be
emailed without two confirmations; email 2 carries the three ROI figures and, in
the same paragraph, the arithmetic behind them and the words "a model, not a
customer result" (decision of 2026-09-06); WF-C4's journal line carries no reply
sentiment and no workflow names a superseded sentiment value; the direct
path routes all four channels correctly without Buffer; a Buffer error at HTTP
200 is a failure; the Stripe link only ever goes to Dovy.

### 3. Run the sample payloads through the real WF-C1 (10 minutes, needs n8n)

Import WF-C1, fill Config, and **execute it manually** (n8n's "Test workflow")
rather than activating, so you can watch each node. Use the **test** webhook URL.

```bash
N8N=https://viniflow-u57383.vm.elestio.app
P=test/sample-payloads.json

# a qualified lead: expect stage qualified and an email to yourself
curl -sS -X POST "$N8N/webhook-test/campaign/qualifier" \
  -H 'Content-Type: application/json' \
  -H 'X-DoviLoop-Dedupe: b1f2c3d4-0001-4a11-9c22-000000000001' \
  -d "$(jq -c '.wf_c1_qualifier.qualified_outlook_global.body' $P)"

# the SAME submission again: expect deduped, and no second row
curl -sS -X POST "$N8N/webhook-test/campaign/qualifier" \
  -H 'Content-Type: application/json' \
  -H 'X-DoviLoop-Dedupe: b1f2c3d4-0001-4a11-9c22-000000000001' \
  -d "$(jq -c '.wf_c1_qualifier.duplicate_of_qualified.body' $P)"

# a Danish under-10 lead: expect PARKED, and no email to the lead
curl -sS -X POST "$N8N/webhook-test/campaign/qualifier" \
  -H 'Content-Type: application/json' \
  -d "$(jq -c '.wf_c1_qualifier.too_small_dk.body' $P)"

# a half-filled form: expect HTTP 200 with an error body, a dead-letter line,
# and an email to you containing the whole payload
curl -sS -X POST "$N8N/webhook-test/campaign/qualifier" \
  -H 'Content-Type: application/json' \
  -d "$(jq -c '.wf_c1_qualifier.malformed_missing_keys.body' $P)"
```

**What to check afterwards**

- `select stage, count(*) from campaign.leads group by stage` — one `qualified`
  (not two), one `too_small`.
- `<data_dir>/dead-letter.jsonl` has one line, and it contains
  `someone@halfway.example`.
- `<data_dir>/parked-under-10.jsonl` has one line for the Danish lead.
- Your inbox has two emails: one `[Lead] …`, one `[DEAD LETTER] …`. **No email
  went to any of the four fake addresses.**

### 4. The rest, once the accounts exist

```bash
# WF-C3: approve nothing, run it, and confirm it publishes nothing
#        then approve one item and run it again
curl -X POST "$N8N/webhook-test/campaign/content-approve" -H 'Content-Type: application/json' \
  -d "$(jq -c '.wf_c3_content_approval.approve_one.body' $P)"

# WF-C4: a comment that hits a keyword. Expect an approval email and NO DM.
curl -X POST "$N8N/webhook-test/campaign/meta-comments" -H 'Content-Type: application/json' \
  -d "$(jq -c '.wf_c4_meta_comment.instagram_keyword_hit.body' $P)"

# WF-C5: a forged Stripe webhook. Expect it to be ignored.
curl -X POST "$N8N/webhook-test/campaign/stripe" -H 'Content-Type: application/json' \
  -d "$(jq -c '.wf_c5_stripe.forged_no_event_id.body' $P)"
```

For WF-C5's day 14 path, insert one test pilot with `started_on = today - 14`
and a `seats` of 10 or more, run the workflow manually with a Stripe **test**
key, and confirm the link email arrives **at your address** and that Stripe's
dashboard shows a session created and **nothing charged**.

---

## Conventions used, and why

The `n8n-workflow-builder` skill the spec points at does not exist in this
container (`AUDIT.md` §2), so its conventions could not be followed. These are
the ones actually used, written down so a later diff against a skill-produced
workflow shows exactly where they differ.

- **Names `WF-C<n> — purpose`.** Cannot be confused with the existing `WF<n>`.
- **No top-level `id` in any export.** n8n mints a fresh one, so no import can
  overwrite a live workflow. This is the guarantee that actually matters; a name
  clash is cosmetic, an id clash is destructive.
- **Node ids are UUID5** over `workflow:node name`, so a rebuild of the JSON is
  a clean diff rather than a churn of random ids.
- **One `Config` Set node per workflow**, holding a single `cfg` object, always
  the second node. Nothing else in the workflow hardcodes a URL, an address or
  an id.
- **`Guard: ledger target` before the first ledger call** in every workflow that
  makes one. Throws on blank, non-https, or the forbidden product ref.
- **Ledger HTTP nodes use `neverError` + `fullResponse`.** A 4xx or 5xx must
  arrive as data, not as an aborted execution, because aborting on the lead path
  is how a lead gets lost. The following Code node reads `statusCode` and
  decides.
- **Long explanations live in the node's `jsCode`, not in the README.** The
  reason a node is shaped the way it is should be readable by whoever opens that
  node at 2am, not two documents away.
- **Nodes that must not stop the flow carry `onError: continueRegularOutput`.**
  A failed dead-letter file write must not stop the dead-letter email.
- **Everything that sends to a real person is a terminal node behind a gate.**
- **`.jsonl` for every journal**, one JSON object per line, appended, so a
  half-written file is still readable and `jq` works on it.

## Files this repo writes at runtime

All under WF-C1's `cfg.data_dir` (default `/home/node/.n8n/campaign`). Make sure
that directory exists and n8n can write to it.

| File | Written by | What it is |
|---|---|---|
| `dead-letter.jsonl` | C1 | malformed payloads and failed ledger writes, with the whole body |
| `parked-under-10.jsonl` | C1 | under-10 leads awaiting an opt-in |
| `nurture-parked.jsonl` | C2 | leads WF-C2 refused to email, and why |
| `opt-outs.jsonl` | C2 | unsubscribes |
| `content-approvals.jsonl` | C3 | every approve and revoke |
| `dm-drafts.jsonl` | C4 | DMs drafted, before approval |
| `social-dm-touches.jsonl` | C4 | DMs actually sent |
| `day14-links.jsonl` | C5 | payment links generated |

The two "To file" nodes in each chain use n8n's **Convert to File** and
**Read/Write Files from Disk** nodes with `append: true`. If your n8n version
names the text conversion operation differently, those are the nodes to check —
and note that every one of these journals is paired with an email, so nothing is
lost if a file write fails.

## Rebuilding the exports

```bash
python3 tools/build_workflows.py && node tools/validate.mjs && node test/run-code-nodes.mjs
```

`tools/build_workflows.py` is the source of truth for the JSON. Edit the JS node
bodies there rather than in the exported files, or the next rebuild will
overwrite your change. `node tools/check-regen.mjs` is what turns that from a
request into a check — run it after any change under `workflows/`. If you edit a
workflow inside n8n instead, re-export it over the JSON and treat the builder as
stale — `check-regen.mjs` will fail until the builder catches up, which is the
point: say so in a commit message and fix the builder.

## See also

- `AUDIT.md` — the Phase 0 audit, and what is definitively absent
- `BLOCKED.md` — twelve items, what each blocks, what it costs
- `CREDENTIALS.md` — seven credentials, where each comes from
- `RUN-REPORT.md` — what shipped, what did not, and what Dovy has to do
- `sql/004_consent.sql` — a proposed migration for the four missing columns,
  targeting the `campaign` schema of the confirmed ledger project
  `yheilbuunzdugfnermfb`. **Not run. Not applied.** Dovy runs migrations, not n8n.
