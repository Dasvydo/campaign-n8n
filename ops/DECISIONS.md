# Decisions taken autonomously — 2026-09-08 night run

Dovy authorised: *"decide where the evidence is clear, document the reasoning, keep every change a
small revertible commit; park anything genuinely 50/50 or outward-facing."*

Every entry below says what was decided, the evidence, and **how to reverse it**. Nothing here
touched a `campaign/*` branch, `main`, a database, or any live service.

---

## D-1 — Cross-batch docs live in `campaign-n8n/ops/`

**Decided:** put the campaign-wide documents (`STATUS.md`, `NEW-PC-SETUP.md`, this file,
`NIGHT-RUN.md`, `HANDOFF.md`) in `campaign-n8n/ops/`.

**Why:** they have to live in a repo or they die with the container, and there is no
`campaign-specs` repository. `campaign-n8n` is the integration repo and already carries
campaign-wide material — `CREDENTIALS.md` covers all seven credentials for the whole campaign, and
`sql/004_consent.sql` is a proposed migration *for a different repo*. The precedent is established.

**Reverse:** they are plain markdown with no inbound links from code. `git mv` them anywhere.

---

## D-2 — `requirements.txt` added to `campaign-ledger` and `ad-engine`

**Decided:** declare `sqlglot` for B, and `Pillow` + `pytest` for E.

**Why, B:** `README.md:265` documented `pip install sqlglot` in prose only. From a clean clone
`tests/run_local_proof.py` reported **45 passed, 1 failed** — the sqlglot parse check erroring on
`ModuleNotFoundError`, which reads like a schema problem. With it declared and installed the gate is
**46/46**, which is what `RUN-REPORT.md` claims.

**Why, E:** the repo had no manifest at all, and two things were missing on a clean machine.
`creative/static/vet.py:23` does `from PIL import Image` — without Pillow the statics ship unvetted.
And the suite is plain pytest functions with no `__main__` runner, so running a test file directly
defines them and exits 0 having asserted nothing. Under pytest it is **89 passed**.

Both runtimes keep their zero-dependency stance: `campaign_db.py` still uses `urllib`, and
`audience.py` still uses only `hashlib`, `re`, `csv` and `json` — which matters because it handles
raw PII before hashing.

**Reverse:** `git rm requirements.txt`. No code imports changed.

---

## D-3 — `.gitignore` added to `campaign-n8n`

**Decided:** add one. It was the only repo of the six without any.

**Why:** this is the repo that will hold n8n material. Raw exports pulled back down from a live
instance carry credential ids, and the workflows append runtime `.jsonl` journals on the n8n host.
Neither belongs in git.

**Safety check run before committing:** `git check-ignore` over every tracked path — nothing already
in the repo becomes ignored. Verified again after: zero tracked files match.

**Reverse:** `git rm .gitignore`.

---

## D-4 — All six repos moved onto `claude/campaign-build-status-9j9194`, based on their real batch branch

**Decided:** rebase the working branch of each repo onto its `campaign/<letter>-*` branch and push.

**Why:** three repos (`outreach-engine`, `reel-engine`, `ad-engine`) had `main` checked out — a bare
scaffold — and the real batch work was on `campaign/c-outreach`, `campaign/d-reels` and
`campaign/e-ads`. An audit written against those scaffolds concluded three batches had never been
done. They had: 7,449 / 9,537 / 3,886 insertions respectively.

**One piece of housekeeping worth knowing:** `ad-engine` and `reel-engine` had their `claude/*`
branch briefly pushed from `main` before this was discovered. `reel-engine` fast-forwarded onto the
correct base cleanly. `ad-engine` carries a single `-s ours` merge (`5cc3fa5`) that absorbs the
superseded tip instead of force-pushing over it. Nothing was discarded and no `campaign/*` branch
was touched.

**Reverse:** every `campaign/*` branch is untouched and remains the source of truth. Delete the
`claude/*` branches and nothing of the batches' own work is lost.

---

## D-5 — Test dependencies installed in this container

**Decided:** `pip install sqlglot dnspython pytest Pillow` plus `reel-engine/requirements.txt`.

**Why:** three suites were reported "broken" by an earlier audit purely because their dependencies
were absent. They were never broken. This established the true baseline:

| Repo | Result |
|---|---|
| campaign-ledger | 46 passed, 0 failed |
| outreach-engine | 138 passed, 0 failed |
| ad-engine | 89 passed |
| reel-engine | 441 passed (render/browser tests error — see below) |
| campaign-n8n | 157 nodes / 0 errors, self-test 16/16, node harness 135/0 |

**Not decided, deliberately:** `reel-engine`'s render tests error because this container's
Playwright wants `chromium_headless_shell-1234` and the image ships `-1194`. That is a container
mismatch, not a repo defect, and it was **not** "fixed" in the repo. On a real machine
`python3 -m playwright install chromium` resolves it.

**Reverse:** container-local only. Nothing committed.

---

## Parked for Dovy — NOT decided

### P-1 — The 9x ROI figure does not survive the price change

The landing page (all three locales) and WF-C2's email 2 both claim roughly **9x** return. At the
confirmed price that arithmetic does not hold:

- ~400 EUR/month claimed saving per seat
- 89 USD/seat/month ≈ **82 EUR**
- 400 / 82 ≈ **4.9x**, not 9x

9x holds against a seat near 45 EUR — which is exactly where the **withdrawn $49** design-partner
rate sat. The figure appears to have survived the 2026-09-06 price decision that invalidated it.
Batch F flagged the same thing independently in its `BLOCKED.md` F-5 and F-9.

**Why this was not changed autonomously:** it is public marketing copy, live in English, Danish and
Lithuanian, and in an outbound email. Changing a headline number across three languages is a
founder's call, not a night-run edit. Two clean options:

1. **Restate the multiple as ~5x** and leave the model as it is. One number changes in
   `campaign-site/src/content/{en,da,lt}.ts` and in WF-C2's `ROI_BLOCK`.
2. **Keep 9x and write down the model that produces it** at the current price — which requires
   either a higher assumed monthly saving or a different basis. Whatever it is, it must be written
   down, because `ad-engine/claims/evidence.json` only permits the ROI figures when the same copy
   calls them a model.

Either way the copy already says "a model, not a customer result" in every place the figure appears,
so nothing is currently claiming a measurement. This is an accuracy problem, not a compliance one.

### P-2 — Whether the under-10 nurture opt-in becomes a real POST

Batch A's 1-9 result screen offers "Send me the three emails" as a **`mailto:`**
(`Qualifier.tsx`, `nurtureHref`), so a genuine opt-in never reaches n8n. WF-C2 therefore requires
five `optin.*` fields it has no automated way of receiving, and Dovy starts the nurture by hand.

Batch F costs the fix at ~15 minutes: change the button to POST at `campaign/nurture-optin` with the
same five fields, and run `sql/004_consent.sql` so the consent record lives in the ledger.

**Why this was not done autonomously:** it changes the shared contract, adds a webhook path, and
depends on a migration that only Dovy runs. It is also the one place where the campaign deliberately
chose legal caution over automation — three batches reached that conclusion independently. Undoing
that by hand at night would be wrong.

### P-5 — reel-engine's golden frames: byte-identity, or a tolerance?

**Measured 2026-09-09, not decided.** `tests/test_golden_reel_b.py` renders six frames and compares
them **byte-for-byte** against goldens captured on another machine. Five of the six differ here:

| frame | mean absolute difference |
|---|---|
| 0 | 0.248 / 255 |
| 243 | 0.030 / 255 |
| 450 | 0.332 / 255 |
| 600 | 0.127 / 255 |
| 749 | 0.085 / 255 |

That is **0.01% to 0.13%** — the signature of a browser or encoder version difference, not a
creative change, which would differ by orders of magnitude more. Frame 360 still matches exactly.

**Why it is not just "loosen it".** The byte-identity rule is load-bearing. The file's own docstring
says *"Reproduces today's behaviour exactly" is the load-bearing claim of the Phase 2 migration.
This is what checks it, rather than the commit message.* A tolerance weakens the thing the test
exists to prove. The author also already built the diagnostic for this exact ambiguity — the failure
message reports the magnitude precisely so drift can be told from regression — which suggests the
question was foreseen and deliberately left open.

**The three options, with what each costs:**

1. **Re-capture the goldens** (`tools/capture_goldens.py`) on whichever machine is now canonical.
   Cheapest, keeps byte-identity, and moves the problem to the next machine that renders them.
2. **Add a tolerance**, e.g. fail above ~1.0/255. Makes the gate pass anywhere, at the cost of no
   longer proving byte-exact reproduction. If you take this, the threshold should be written down
   with the numbers above as its justification.
3. **Leave it.** The gate stays red on any machine that did not capture the goldens, and the five
   failures become background noise people learn to skip past — which is how a real regression gets
   through.

Given the campaign is about to go live and nobody is actively migrating reel-b's rendering, option 1
is probably right and option 3 is the one to avoid. But it is a call about what the test is *for*,
so it is yours.

---

### P-6 — Two pixel events campaign-site never sends, and one Meta audience that cannot be built

**Found 2026-09-09 by reconciling `ad-engine/campaigns/pixel-install.md` against Batch A's shipped
code. Not applied — it is a one-line change in a file `ad-engine` does not own, and it changes what
is collected about real visitors in an EU campaign.**

**Confirmed by measurement the same day, in Chromium.** `campaign-site/scripts/verify-browser.py`
builds the site with a placeholder pixel id, blocks every Meta request at the route level and reads
`window.fbq.queue` — a complete record of every call the page makes. Scrolling the pricing band
into view produces **no pixel call whatsoever**, and the submit sends `["track", "Lead", null]`.
So this is no longer inferred from source: both gaps are observed. The only `ViewContent` the site
sends is `demo_video`, fired by playing the demo. The check that proves it was itself proved, by
injecting a `ViewContent(content_name='pricing')` and watching it fail.

**Gap 1 is the one that matters.** `campaign-site/src/LocalePage.tsx` wires
`<Price onView={() => track('pricing_view')} />` — PostHog only, with **no `pixelTrack` call at
all**. The single `ViewContent` the site sends carries `content_name: 'demo_video'`, from the demo
video. `ad-engine/campaigns/structure.md` builds **Audience 3, "Pricing section viewers, 90 days"**,
on `ViewContent` where `content_name` equals `pricing`, and ranks it the *highest intent pool*. It
would have stayed permanently empty, and the failure looks like "retargeting just isn't working"
weeks after launch.

**Gap 2.** `pixelTrack('Lead')` is called with no properties, so no `content_category` carrying the
routing outcome. The exclusion on audiences 1, 2 and 3 keys on it, as does the future `too_small`
exclusion. PostHog still receives the routing detail on `form_submit`, so the system of record is
intact — only Meta's audience builder is blind.

**The patch, both in `campaign-site/src/LocalePage.tsx`:**

```ts
<Price c={c} onView={() => { track('pricing_view');
  pixelTrack('ViewContent', { content_name: 'pricing' }); }} ... />

pixelTrack('Lead', { content_name: 'qualifier', content_category: outcome });
```

**Why it is yours and not mine.** Adding pixel events changes what Meta is told about EU visitors.
This campaign has already made one deliberate privacy call (P-2, the nurture opt-in), and the same
judgement applies: more tracking is a decision, not a bug fix. It is also worth deciding *with*
gap 2, because `content_category` would carry the routing outcome — which is business data about a
named visit.

**Nothing misfires today.** `VITE_META_PIXEL_ID` is unset, so the pixel is inert. That is precisely
why this survived both batches' own QA: neither side could see the other, and nothing was firing.

**Reverse:** the two lines above are additive; removing them restores today's behaviour exactly.

---

### P-4 — Five of the six repos are PUBLIC, and they document unauthenticated webhooks

**Found 2026-09-08 while checking whether a `campaign-specs` repo existed. Not changed — this is
yours to decide, and it should be decided before anything is activated in n8n.**

Repository visibility, from the GitHub API:

| Repo | Visibility |
|---|---|
| campaign-site, campaign-ledger, campaign-n8n, ad-engine, outreach-engine | **public** |
| reel-engine | private |

No secret is committed anywhere — that scan is clean and was re-run on the correct branches. The
issue is the *combination* of three public facts:

1. **The n8n instance hostname** is in a public file: `campaign-n8n/README.md:342` reads
   `N8N=https://viniflow-u57383.vm.elestio.app`. It also appears in `AUDIT.md:14` and
   `BLOCKED.md:205`.
2. **All eight webhook paths** are in the public workflow exports: `campaign/qualifier`,
   `campaign/nurture-optin`, `campaign/unsubscribe`, `campaign/content-approve`,
   `campaign/meta-comments`, `campaign/meta-dm-approve`, `campaign/stripe`.
3. **None of the eight sets `authentication`.** Every webhook node reads
   `authentication: NONE`.

So once these workflows are activated, the full URL of every endpoint is publicly derivable, and
each one accepts an unauthenticated POST. In rough order of how much it would cost:

- **`campaign/content-approve` is the one that matters most.** `campaign-n8n/README.md` says WF-C3
  "is the only workflow in the campaign that publishes in public, so the gate here is the one that
  matters most", that it fails closed, and that it "only ever moves content Dovy has marked
  approved". That approval list is written by this webhook, and the node carries no token or secret
  check. Anyone who can reach it can mark content approved for Instagram, Facebook, YouTube Shorts
  and LinkedIn.
- **`campaign/meta-dm-approve`** is the same shape for outbound DMs.
- **`campaign/qualifier`** additionally sets `allowedOrigins: "*"`, so fabricated leads can be
  written into `campaign.leads` from any origin. Idempotency is on `natural_key`, which does not
  help against varied input.
- **`campaign/unsubscribe`** would let a third party suppress arbitrary addresses.
- **`campaign/stripe`** reads the `stripe-signature` header but the check is a presence test
  (`signature_header: !!headers['stripe-signature']`), not a cryptographic verification against the
  `whsec_` signing secret.

**Why this was not fixed autonomously.** Three reasons, any one of which is sufficient. Repository
visibility is an outward-facing change. Adding webhook authentication means regenerating the
workflow JSON through `tools/build_workflows.py` *and* configuring the matching credential inside
n8n, and only you can do the second half — a change to one without the other breaks the campaign's
one working end-to-end path. And the Stripe fix needs the real signing secret.

**Options, roughly cheapest first:**

1. **Make the repos private.** One setting each. It removes the discoverability, though it is
   defence in depth rather than a fix — the endpoints remain unauthenticated.
2. **Add n8n header auth** to the four webhooks that take instructions rather than public
   submissions (`content-approve`, `meta-dm-approve`, `nurture-optin`, `unsubscribe`). n8n supports
   this natively on the webhook node; it needs a matching credential created in the instance.
3. **Verify the Stripe signature properly** in WF-C5 rather than testing for the header's presence.
4. **Leave `campaign/qualifier` open** — it has to accept posts from the public landing page — but
   consider a shared secret header, which `campaign-site` already demonstrates it can send: it
   sends `X-DoviLoop-Dedupe` today.

`campaign/meta-comments` legitimately must stay open and unauthenticated: Meta calls it, and it is
verified by Meta's own challenge handshake.

---

### P-3 — Where `sql/004_consent.sql` should live

It is a migration for `campaign-ledger` that sits in `campaign-n8n`, because batch F may not write
to a sibling repo. It is marked `STATUS: NOT RUN. NOT APPLIED.` If Dovy accepts it, it should move
to `campaign-ledger/migrations/004_consent.sql` and run in sequence after 003. That is his call
because running it is his action.
