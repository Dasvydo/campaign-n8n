# RUN-REPORT — Batch F, `campaign-n8n`

Branch `campaign/f-n8n`. No file outside
`/home/user/campaign-n8n` was written, moved or deleted.

---

## What was built

| File | Nodes | Triggers | State |
|---|---|---|---|
| `workflows/WF-C1.json` | 24 | 1 | complete |
| `workflows/WF-C2.json` | 27 | 3 | complete, gated |
| `workflows/WF-C3.json` | 37 | 2 | complete, both paths |
| `workflows/WF-C4.json` | 25 | 3 | complete, gated |
| `workflows/WF-C5.json` | 28 | 2 | complete |
| `workflows/WF-C6.json` | 16 | 1 | complete |
| | **157** | | |

Plus `AUDIT.md`, `BLOCKED.md`, `CREDENTIALS.md`, `README.md`,
`test/sample-payloads.json`, `sql/004_consent.sql` (proposed, not run),
`tools/build_workflows.py`, `tools/validate.mjs`, `tools/validate-selftest.mjs`,
`test/run-code-nodes.mjs`.

---

# Divergences from spec, and which reality I followed

Nine places where the code on disk disagreed with the specs. **In every case I
followed the code.**

### 1. `gmail_on_request` is a stage, not a flag — followed B

`00-START-HERE.md` describes it as a "ledger flag" on a lead whose stage is
`qualified`. Batch B modelled it as a **value of the `campaign.lead_stage`
enum**: `('qualified', 'gmail_on_request', 'too_small')` in `001_schema.sql`,
with `campaign_db._route_stage()` returning it directly.

**Followed: B.** WF-C1 writes `stage = 'gmail_on_request'` as a stage value.

Worth noting because it looks like a three-way disagreement and is not: Batch A's
`contract.ts` `route()` returns `outcome: 'gmail_on_request'` alongside mirrored
`ledger_stage: 'qualified'` / `ledger_flag: 'gmail_on_request'` fields — and its
own comment says those two are **"Mirrored, not sent"**. They never go on the
wire. A's `outcome` and B's `stage` use the same three labels, so A and F agree
on everything that is actually transmitted.

### 2. Idempotency is two mechanisms, not "work_email + hour" — superseded

My spec says WF-C1 should be "idempotent on `work_email` + hour". **That is
superseded and I did not build it.** An hour bucket is both too loose (two
genuine submissions 5 minutes apart collapse into one) and too tight (a retry
that crosses the hour boundary creates a duplicate).

What exists instead, both used:

- **Primary:** the `X-DoviLoop-Dedupe` header. Batch A mints one id per
  submission (`lead.ts:111`), reuses it across both send attempts, and stores it
  with the queued payload so a localStorage drain re-sends the *same* id.
- **Fallback:** Batch B's derived key, `lower(work_email) + '|' + submitted_at`,
  for any caller that does not send the header.
- **Backstop:** the unique index on `campaign.leads.natural_key`, hit with
  `Prefer: resolution=ignore-duplicates`. Even if the in-flight check misses
  (two n8n workers, a restarted instance), Postgres collapses the duplicate.

**One subtlety that would have been a silent bug:** B's `_iso()` passes a string
`submitted_at` through **unchanged**, so the key uses the timestamp verbatim.
Normalising it in n8n — adding a `Z`, dropping milliseconds, re-serialising —
would produce a different key from the one B computes and break dedupe against
anything B wrote. WF-C1 passes it through byte for byte, and there is a test
asserting exactly that string.

### 3. WF-C1 does NOT auto-enrol `too_small` into the nurture — followed A and B

The routing table says a 1-9 lead "enters a 3-email nurture". There is no
consent field on the contract, A's opt-in is a `mailto:` that never reaches n8n,
and `campaign.leads` has no consent column. Denmark makes it a legal exposure
rather than a preference.

**Followed: A's refusal and B's flag.** WF-C1 parks the lead. WF-C2 requires
five proven opt-in fields, plus two separate Danish confirmations. Full reasoning
at the top of `README.md` and in `BLOCKED.md` F-4.

### 4. WF-C2's email 2 ships with no ROI numbers — followed `evidence.json`

Spec: email 2 carries "the ROI numbers". `ad-engine/claims/evidence.json` says
no measured customer outcome exists and marks such claims UNVERIFIED.

**Followed: the claims ledger.** Email 2 explains the mechanism and states
plainly that no customer numbers exist yet. An empty, clearly marked `ROI_BLOCK`
slot sits in the node source. `BLOCKED.md` F-5.

### 5. `campaign.content` has no approval flag — built an explicit list

Spec: read content "where `published_at` is null and an approval flag is set".
No such column exists in B's table, and D confirms the same column list.

**Followed: the schema, and failed closed.** WF-C3 publishes only what is on an
explicit approval list written by the `campaign/content-approve` webhook. The
tempting alternative ("published_at is null and asset_path is set") would
auto-publish every render, and a render is not an approval. `sql/004_consent.sql`
§2 proposes the column.

### 6. `campaign.leads` has no opt-out column — wrote elsewhere and said so

Spec: unsubscribes are "honoured by writing an opt-out flag back to
`campaign.leads`". There is no such column.

**Followed: the schema.** Opt-outs go to n8n static data (which is what stops
the next email), an append-only file, and an email to Dovy. `BLOCKED.md` F-6.

### 7. `campaign.touches` cannot hold a social DM — journalled instead

Spec: WF-C4 should "log a `touch`". Two independent blockers: `contact_id` is
NOT NULL through a chain that ends at a required company `domain`, and
`touch_channel` has no `instagram_dm` / `facebook_dm` value, with B's comment
saying the enum is shared with the outreach engine.

**Followed: the schema, and refused to fabricate.** Journalled to
`social-dm-touches.jsonl` in the exact shape a future insert would take, with
both reasons recorded in every line. `sql/004_consent.sql` §3 proposes a separate
table and explains why extending the enum was rejected.

### 8. WF-C5's "usage summary" does not exist in the ledger — said so in the email

`campaign.pilots` has no usage data of any kind. Usage lives in the product
database, which this campaign may not touch.

**Followed: the schema.** The day 12 reminder carries what the ledger knows and
states, in the email, what it does not know and where the number would have to
come from. No usage figure was invented. `BLOCKED.md` F-8.

### 9. WF-C1 answers with the routing outcome, and Batch A ignores it

Spec: "Respond to the page with the routing outcome so the client renders the
right screen." Batch A does not read the response body — `submitLead()` checks
only `res.ok` and renders from its own client-side `route()`.

**Followed: both.** WF-C1 responds with the full outcome JSON anyway, because it
costs one node and makes curl testing and any future client work. **A's screen
is not driven by it**, which is worth knowing before anyone tries to change what
a visitor sees by editing the webhook.

**One consequence that is easy to get wrong:** the malformed branch answers
**HTTP 200** with an error body, not a 4xx. A's client retries on `!res.ok` and
would re-post a payload that fails identically, twice, then queue it in
localStorage forever. A 200 with `kept: true` stops that loop and still tells the
truth.

### Two smaller ones

- **`buffer_id` is one text column, and one English reel produces four post
  ids.** Rather than drop three, WF-C3 packs them as
  `instagram=123;facebook=456;youtube_shorts=789`. WF-C4 and WF-C6 both unpack
  the same format, so it is a real format and not a dumping ground.
- **The spec asks WF-C3 to write "the scheduled time"; there is no such column.**
  `published_at` gets the time the platform accepted the post. A row is marked
  published only if **at least one** channel succeeded, so a total failure leaves
  it null and it is retried next Thursday rather than silently marked done.

---

## QA gate, line by line

### - [x] All six JSON files import-valid against the n8n schema

`node tools/validate.mjs` → **6 files, 157 nodes, 0 errors, 0 warnings.**

**Be precise about what that means.** There is no n8n binary in this container,
so this is *not* "n8n accepted it". It is: every file parses, and conforms to the
structural shape n8n's importer requires, checked property by property — node
name / unique id / type / typeVersion / `[x,y]` position / parameters object,
every connection target existing, no unreachable nodes, every workflow having a
trigger, merge nodes declaring enough inputs.

Because a validator that has never failed is indistinguishable from one that
cannot fail, `tools/validate-selftest.mjs` takes the real WF-C1 export, breaks it
**15 ways** and asserts each is caught: `active: true`, a top-level `id`, a
dangling connection target, a missing position, a missing parameters object, a
duplicate node name, a duplicate node id, a credential carrying a value, a live
Stripe key, a JWT, the forbidden project ref, a superseded reply sentiment, an
unreachable node, a workflow with no trigger, and unparseable JSON.
**16 passed, 0 failed** (the sixteenth is the control: the unmodified export
still passes). Re-run and confirmed 2026-09-08.

**What it cannot check, honestly:** that a node's `typeVersion` exists on Dovy's
n8n build; that a parameter name inside `parameters` is spelled the way that node
version expects; that `convertToFile`'s text operation is called `toText` on his
version. Those need an import. The two most likely to bite are called out in
`README.md`, and every file-write node is paired with an email, so a wrong
parameter there costs a log line and not a lead.

### - [x] No credential value, key or token in any file

Asserted on every validator run, two ways. **Structural:** every `credentials`
entry may carry only `{id, name}`; any other key fails. **Content:** every string
in every file is scanned for JWTs, `sk_/rk_live|test`, `whsec_`, Meta `EAA…`
tokens, Slack tokens, GitHub tokens, Google `AIza…` keys and PEM private key
blocks. Self-test proves both fire.

Seven credentials are referenced **by name only** and documented in
`CREDENTIALS.md`. No credential value exists anywhere in this container to leak.

### - [x] Every workflow exported inactive

`"active": false` in all six. Asserted by the validator (`must be exactly false`,
so `"false"` or `0` would fail) and again in the node harness.

### - [x] WF-C1 handles a malformed payload without losing the lead

Proven by executing the real node code, not asserted. `test/run-code-nodes.mjs`
reads `Validate and route` and `Dead letter: malformed` **out of WF-C1.json** and
runs them against three malformed payloads:

- a half-filled form → rejected, and the dead letter still contains
  `someone@halfway.example` and `Halfway Filled Form Ltd`
- an out-of-range enum → rejected, and the problem list names `team_size`
- a body that is not an object at all → rejected, and the raw string survives
  into the dead letter intact

and further:

- the dead letter carries the dedupe key, so replaying it cannot double-create
- the JSONL line is valid JSON on its own
- the branch responds **200**, not 4xx, with `kept: true`
- an extra unknown key is **tolerated**, recorded as non-fatal and stripped
  before the insert, so a real lead is not bounced over a field a future form
  version adds
- **the ledger being down is also handled**: a 503 arrives as data rather than
  killing the execution, the lead is dead-lettered, and Dovy still gets it

Four places the payload survives: the response, the dead-letter file, an email to
Dovy containing the whole body, and n8n's own execution log. **Losing a lead
needs all four to fail.**

### - [x] WF-C3 has a working non-Buffer fallback path

Not a stub. `publisher: 'direct'` routes to real endpoints:
Instagram (`/media` container → 90s wait → `/media_publish`, the async flow reels
actually require), Facebook page `/videos`, YouTube Data API v3 upload via n8n's
YouTube node, LinkedIn via n8n's LinkedIn node.

Proven by evaluating the **real IF-node condition strings taken from the export**
against the real fan-out items: `publisher: 'direct'` bypasses Buffer entirely,
and instagram / facebook / youtube_shorts / linkedin each reach their intended
node. Every branch is verified to terminate in a node wired to the `Collect
results` merge, and the ledger write-back is exercised end to end from
direct-path results (three of four channels succeed → row marked published, all
three ids packed into `buffer_id`, the one failure kept and reported; all four
fail → `published_at` stays null and it retries next Thursday).

**One honest hole:** LinkedIn **video** on the direct path is not built. n8n's
LinkedIn node has no video category; a real one is a three-call UGC upload. Text
plus a still frame works. This matters more than it sounds because LinkedIn is
the *only* channel Danish and Lithuanian reels go to. `BLOCKED.md` F-11, and
`README.md` recommends Buffer partly for this reason.

### - [x] WF-C5 cannot charge a card without Dovy sending the link

Four independent guarantees, all tested:

1. The only Stripe write in the workflow is `POST /v1/checkout/sessions`
   (asserted across every POST node in the file). Creating a session moves no
   money and emails nobody.
2. `FORBIDDEN_PARAMS` throws if `off_session`, `confirm` or `setup_future_usage`
   is ever built into the body.
3. `customer_email` is **never** sent, so Stripe holds no address for the client.
4. `Guard: the link goes to Dovy only` throws rather than send if the recipient
   is not `cfg.dovy_email` or equals the client's `work_email` — **tested by
   setting them equal and asserting the throw**. The Send node's `toEmail` is
   bound to the value that guard just checked.

Plus: the Stripe webhook takes **only the event id** from the incoming body and
re-fetches the event over the authenticated API, so an unsigned endpoint cannot
be used to write to the ledger, and no signing secret has to live in the export.
And `CREDENTIALS.md` specifies a **restricted key** with exactly two permissions,
which makes this enforced by Stripe rather than promised in a comment.

### - [x] Branch `campaign/f-n8n`, nothing pushed *(true as written; superseded 2026-09-08)*

At the time of the batch: `git remote -v` was empty and no push was attempted.
Every sibling repo was untouched.

**Since 2026-09-08** the work is on `claude/campaign-build-status-9j9194` and is
pushed to `github.com/Dasvydo/campaign-n8n`, on Dovy's explicit instruction. The
`campaign/f-n8n` branch it was based on is untouched and remains the batch's own
record. No commit count is quoted here on purpose: it goes stale on every commit,
and `git log --oneline` is authoritative.

### Also delivered beyond the gate

- **WF-C4's DM send node is unreachable from the comment webhook.** Verified as
  graph reachability, not a string search: the only trigger that can reach it is
  `Webhook — approve DM`, the link in Dovy's email. No config switch bypasses it.
- **A `Guard: ledger target` node** in all four ledger-touching workflows,
  throwing on blank, non-https, or the forbidden product ref. Tested: throws on
  all three, passes a real campaign URL.

**Total: `tools/validate.mjs` 0 errors; `validate-selftest.mjs` 15/15;
`test/run-code-nodes.mjs` 130 passed, 0 failed.**

---

## What was skipped, and why

- **Connecting to the n8n instance.** Forbidden by the spec. Never contacted.
- **Connecting to any database.** The only Supabase credential here points at the
  forbidden product project. Nothing connected; a guard node was built instead.
- **Following the `n8n-workflow-builder` skill.** It does not exist in this
  container (`AUDIT.md` §2). Conventions used are written out in `README.md`.
- **Verifying numbering against WF1/WF4/WF5/WF6/WF9.** They are not present
  (`AUDIT.md` §3). A scheme that *cannot* collide was chosen instead: `WF-C<n>`
  names, and no top-level `id` in any file.
- **Applying `sql/004_consent.sql`.** Dovy runs migrations. It also lives in this
  repo rather than `campaign-ledger`, because Batch F may not write to a sibling.
- **LinkedIn video on the direct path** (F-11) and **LinkedIn post analytics**
  (F-10). Both need API access this account does not have.
- **Auto-enrolling `too_small` leads.** Deliberate, and the most important thing
  in this report. See divergence 3.

---

## What I could not verify

Stated plainly, because a QA gate that only lists passes is not a QA gate.

1. **That n8n imports these.** No n8n in the container. Structure is checked;
   per-node parameter spelling for a specific n8n version is not.
2. **That `convertToFile`'s text operation is `toText`** and that
   `readWriteFile` honours `options.append` on Dovy's version. These are the two
   most likely parameter-level misses. Mitigated: every journal is paired with an
   email, so a wrong parameter costs a log line, never a lead.
3. **That no existing workflow binds a `campaign/…` webhook path.** Cannot be
   checked without the existing five. Two minutes for Dovy.
4. **Anything about WF4.** Not present. Nothing here depends on it.
5. **Every credentialed API seam.** Buffer's exact GraphQL host and error
   typenames are Batch D's researched-but-unconfirmed constants, and D says so in
   its own file. Meta's IG reel flow, YouTube upload, LinkedIn posting and Stripe
   Checkout are written against documented shapes and have never seen a real
   response.
6. **That `oqpeebtwtikdzorgouxd` is the right ledger project.** Batch B's own
   migration header says it could not confirm this. Confirm in the dashboard.
7. **Whether the ROI figures are real.** Only Dovy knows. That is why email 2
   ships without them.

---

## What Dovy has to do

### Before anything else — 10 minutes, and it is a decision, not a task

1. **Answer the ROI question.** Were `~9x ROI / ~EUR 400 a month / ~40 day
   payback` ever measured against a real customer? If yes, update
   `ad-engine/claims/evidence.json` and paste the paragraph into `ROI_BLOCK` in
   WF-C2. If no, leave it empty — and fix the landing page copy, which currently
   calls them "estimates from measured usage". **5 min.**
2. **Confirm the ledger project ref** in the Supabase dashboard before pasting it
   into any Config node. **2 min.**
3. **Add `campaign` to Settings → API → Exposed schemas.** Without it every
   PostgREST call returns `PGRST106`. **1 min.**
4. **Search WF1/WF4/WF5/WF6/WF9 for `campaign/`** to rule out a webhook path
   collision. **2 min.**

### Stage 1, day one — about 25 minutes

5. Create credentials 1 and 2 from `CREDENTIALS.md` (Supabase, SMTP). **10 min.**
6. Import WF-C1, WF-C2, WF-C6. Fill each Config node. Note the chicken-and-egg:
   import WF-C2, copy its unsubscribe webhook URL, paste it back into its own
   Config. **10 min.**
7. Create the `data_dir` on the n8n host and make sure n8n can write to it.
   **2 min.**
8. Run the four WF-C1 curls in `README.md` §Test plan against the **test**
   webhook URL and check the four outcomes listed there. **10 min.**
9. Activate WF-C1, then paste its **production** URL into Batch A's
   `VITE_LEAD_WEBHOOK_URL` in Vercel. **3 min.**
10. Activate WF-C2. Safe: it sends nothing without an opt-in, and activating it
    is what makes the unsubscribe link work. **1 min.**

**After stage 1 the funnel is live end to end**: a real lead reaches the ledger
and Dovy's inbox, a duplicate submit cannot create two rows, a malformed one
cannot vanish, and no marketing email can go to anyone who did not ask.

### Stage 2, when the social accounts exist — about 30 minutes

11. Meta page token with the six permissions listed in `CREDENTIALS.md` §4, plus
    `ig_user_id` and `fb_page_id`. **15 min.**
12. Decide Buffer or direct (`README.md` has the comparison). If Buffer, add the
    token and the four channel ids. **10 min.**
13. Import WF-C3 and WF-C4, fill Config, approve one test reel with the curl in
    `README.md`, run WF-C3 manually and confirm it publishes **only** that one.
    **15 min.**

### Stage 3, before the first pilot hits day 14 — about 20 minutes

14. Stripe products (`$500` one-off, `$89`/seat/month) and a **restricted** key
    with Checkout Sessions: write and Events: read. **10 min.**
15. Import WF-C5, fill the two Price ids, add the `campaign/stripe` endpoint in
    Stripe subscribed to `checkout.session.completed` and `invoice.paid`.
    **5 min.**
16. Insert one test pilot with `started_on = today - 14`, run WF-C5 manually with
    a **test** key, confirm the link arrives at *your* address and Stripe shows a
    session created and nothing charged. **10 min.**
17. Set `usd_eur_rate` in WF-C5's Config, or accept that converted pilots show
    with no revenue in the Friday brief. **1 min.**

### Whenever — worth 20 minutes

18. Read `sql/004_consent.sql` and decide on the four columns. Running it removes
    three workarounds that currently keep campaign state inside n8n, where the
    ledger cannot see it and an instance rebuild would lose it.

**Total: roughly 20 minutes for the decisions, 25 for stage 1, and about 50 more
spread across stages 2 and 3 as the accounts come into existence.** The spec
budgeted 20 minutes; that was right for the import itself and did not account for
the accounts not existing yet.

---

## The one thing to take away

Five of the six workflows do something the spec did not ask for: they refuse.
WF-C1 refuses to start a nurture nobody consented to. WF-C2 refuses to email a
Danish address on one confirmation. WF-C3 refuses to publish anything not
explicitly approved. WF-C4 refuses to DM a stranger without a click from Dovy.
WF-C5 refuses to put a payment link in front of anyone but him.

Every one of those refusals is a place where the spec, read literally, would have
sent something to a real person that nobody had approved. They are all cheap to
turn off later once the missing consent, approval or evidence actually exists.
None of them is cheap to undo after it has already sent.

---

## Decisions applied, 2026-09-06

Dovy made four campaign-wide decisions. This section records each one and what
changed in this repo as a result. Branch `campaign/f-n8n`, one commit on top of
`954f7ad`. Nothing outside `/home/user/campaign-n8n` was written.

**1. The ROI figures are modelled, not measured.** The ~9x return, ~400 EUR a
month per seat and ~40 day payback are outputs of a model that assumes time
saved per seat and costs it at a salary. No customer has been measured. Same
decision as `ad-engine/claims/evidence.json` `roi_model`, which allows the
figures only when the same copy calls them a model or a worked example.
*Changed here:* `ROI_BLOCK` in WF-C2's "Build the three emails" node is filled
(`tools/build_workflows.py`, rebuilt into `workflows/WF-C2.json`). Email 2 now
carries the three figures as a worked example: 10 assumed hours a month, costed
at about 40 EUR an hour, giving about 400 EUR a month per seat; about 9x on the
seat cost; about 40 days to pay back the 500 dollar setup fee plus the first
month of seats. The same paragraph says "a model, not a customer result" and
"Nothing has been measured against a real firm yet", and the paragraph after
it still says no customer numbers exist. The node header now records the
decision instead of arguing against the figures. Divergence 4 above is
therefore superseded. `test/run-code-nodes.mjs` replaces its three "no ROI
figure" assertions with six that require the figures, the arithmetic and the
framing in one paragraph, and that no measurement or customer is claimed.
`BLOCKED.md` F-5 is marked resolved. No em dash, English only, casual register.
*One thing left for Dovy, recorded in F-5:* 400 EUR against an 89 USD seat
(about 82 EUR) is roughly 5x; 9x holds against a seat near 45 EUR, where the
superseded 49 USD price sat. The email attributes the 9x to "our model", as the
landing page does, rather than deriving it from the shown division.

**2. Price is 89 USD per seat per month plus 500 USD one-off setup.**
*Changed here:* nothing in the workflows. WF-C5's Checkout Session already
builds `line_items[0]` as the `price_seat_monthly` Price times `seats` and
`line_items[1]` as the `price_setup_once` Price once; its email to Dovy says
"the 500 dollar setup plus 89 dollars per seat per month"; its MRR arithmetic
is `seats * 89`; `CREDENTIALS.md` §7 names the two Prices as 89 USD recurring
and 500 USD one-off. A grep of every file for `49` and `99` finds only the
`25-49` team-size band and unrelated numbers. Neither nurture email states a
price; email 1 says the smaller plan "costs a lot less" and links to pricing.
`README.md` gained a short paragraph under WF-C5 stating the offer and where
the amounts live.

**3. Reply sentiment taxonomy is `interested, not_now, not_a_fit, referred,
objection, unsubscribe`.** The old values (`hot_pain`, `curious`, `endorse`,
`unrelated`, `ineligible`) are gone from the ledger enum.
*Found here:* no workflow node, Code node body, sample payload, README table or
CREDENTIALS note ever named any sentiment value, old or new. WF-C4's touch is
the DM going out, not a reply, so it wrote no sentiment. WF-C6 runs
`friday_brief.py` and renders its markdown; it classifies nothing.
*Changed here:* WF-C4's journal line now carries an explicit
`reply_sentiment: null` with a comment naming the six legal values, so the
shape matches a future `campaign.touches` insert. `tools/validate.mjs` now
errors on any of the five superseded values anywhere in an export, and
`tools/validate-selftest.mjs` proves it (16 cases now). `test/run-code-nodes.mjs`
asserts the null and the absence of superseded values in all six workflows.
`README.md` states both under WF-C4.

**4. Ledger project `oqpeebtwtikdzorgouxd` is confirmed.**
*Changed here:* `ledger_url` in all six Config nodes is pre-filled with
`https://oqpeebtwtikdzorgouxd.supabase.co` instead of shipping blank; the
Config node note and the guard's blank-URL message say so. The guard still
throws on blank, non-https or the product ref `kngcxwcybozgqgnoweyt`.
`CREDENTIALS.md` §1 names the project as confirmed. `README.md`'s import
section and Config table no longer ask Dovy to fill or confirm it, and its
"See also" notes that `sql/004_consent.sql` targets that project's `campaign`
schema; the SQL header says the same. `BLOCKED.md` F-12 notes the project is
confirmed but that no credential for it exists here. Items 1 and 2 of "What
Dovy has to do" above are done by these decisions; item 3 (expose the
`campaign` schema in PostgREST) still stands. This repo has no `.env.example`;
the Config nodes are its equivalent.

**Verification after the changes:** `node tools/validate.mjs` 6 files, 157
nodes, 0 errors, 0 warnings. `node tools/validate-selftest.mjs` 16 passed, 0
failed. `node test/run-code-nodes.mjs` 135 passed, 0 failed. Every export still
has `active: false` and no top-level `id`. No secret-shaped string was added;
the self-test's fake Stripe key is still assembled at runtime from two halves.
