# BLOCKED — Batch F

Everything here was logged and the batch continued. Nothing in this list stopped
a workflow from being built; each one names what is missing and what it affects.

Ordered roughly by how much it costs if it is ignored.

---

## F-5. RESOLVED 2026-09-06. The ROI figures are modelled, and email 2 now says so

**Was missing:** an answer to one question. Were the ROI figures (~9x ROI,
~EUR 400 a month saved, ~40 day payback) ever measured against a real customer?

**The answer (Dovy, 2026-09-06, campaign-wide):** no. They are **modelled, not
measured**. They come from a model that assumes an amount of time saved per seat
and costs it at a salary. No customer has been measured. The same decision is
recorded in `ad-engine/claims/evidence.json` under `roi_model`, which allows the
figures only when the same copy calls them a model or a worked example and not a
measurement.

**What changed:** the `ROI_BLOCK` slot in WF-C2's "Build the three emails" node
is filled. Email 2 now carries the three figures as a worked example: the
assumed 10 hours a month, costed at a mid level salary of about 40 EUR an hour,
giving about 400 EUR a month per seat, about 9x on the seat cost, and about 40
days to pay back the 500 dollar setup fee plus the first month of seats. The
same paragraph says "a model, not a customer result" and "Nothing has been
measured against a real firm yet", and the paragraph after it still says plainly
that no customer numbers exist. `test/run-code-nodes.mjs` now asserts the
figures are present, the arithmetic is shown, and the framing sits in the same
paragraph, and asserts that no measurement or customer is claimed.

**Still worth Dovy's eye:** 400 EUR a month against the 89 USD seat (about 82
EUR) is roughly 5x, not 9x. The 9x holds against a seat near 45 EUR, which is
where the superseded 49 USD price sat. Email 2 words the multiple as "our model
puts the return at about 9x", matching the landing page, rather than deriving it
from the shown division. If 9x is to stay campaign-wide, the model's base for it
should be written down; if not, the one figure to change is in `ROI_BLOCK` and
`campaign-site/src/content/*.ts`.

## F-4. There is no consent signal anywhere on the wire, so WF-C1 does not start the nurture

**Missing:** a consent field on the shared qualifier contract, and any path by
which an opt-in reaches n8n.

**What was checked:**

- `campaign-site/src/lib/contract.ts` has eleven fields. None is consent.
- Batch A's 1-9 result screen offers an explicit opt-in ("Send me the three
  emails"), and it is a **`mailto:`** to `hello@doviloop.dev`
  (`Qualifier.tsx`, `nurtureHref`). It does not post to any webhook, so the
  opt-in never reaches n8n on its own.
- `campaign.leads` has no consent column and no opt-out column, so there is
  nowhere in the ledger to record the answer either.

**What Batch F did:** WF-C1 parks `too_small` leads and starts nothing. WF-C2's
consent gate requires `optin.granted`, `optin.source`, `optin.evidence`,
`optin.recorded_at` and a matching `optin.work_email`, and parks the lead if any
is missing. Denmark additionally requires two separate confirmations.

**Blocks:** the nurture is manual until an opt-in capture exists. Every under-10
lead lands in `parked-under-10.jsonl` and Dovy starts WF-C2 by hand off the
mailto in his inbox.
**Dovy: 15 minutes** to make it automatic, if he wants it: change A's opt-in
button from a mailto to a POST at `campaign/nurture-optin` carrying the same
five fields, and run `sql/004_consent.sql` so the consent record lives in the
ledger instead of in a hand-written payload.

## F-6. `campaign.leads` has no `opt_out` column, so the unsubscribe list lives in n8n

**Missing:** the column WF-C2's spec says to write to. "Unsubscribe link in all
three, honoured by writing an opt-out flag back to `campaign.leads`" — there is
no such flag in `001_schema.sql`.

**What Batch F did:** the opt-out is written to three places: n8n workflow static
data (which is what actually stops the next email), an append-only
`opt-outs.jsonl`, and an email to Dovy.

**Blocks:** nothing today. The unsubscribe works.
**Costs if ignored:** n8n static data does not survive an instance rebuild or a
workflow delete-and-reimport. If that happens, the suppression list is gone and
the JSONL file is the only record. Proposed fix in `sql/004_consent.sql` §1.

## F-7. `campaign.touches` cannot hold a social DM, for two independent reasons

**Missing:** a way to record WF-C4's DM as a touch.

1. `touches.contact_id` is NOT NULL and references `contacts`, whose
   `company_id` is NOT NULL and references `companies`, whose `domain` is NOT
   NULL with a CHECK on its shape. An Instagram commenter is an anonymous
   handle with no firm, name or email. Logging one touch would mean inventing a
   company and a contact into the same tables the ICP finder and the Friday
   brief count.
2. `campaign.touch_channel` is `('linkedin_connect','linkedin_dm','email',
   'phone')`. There is no `instagram_dm` or `facebook_dm`, and Batch B's comment
   on the type says the taxonomy is shared with the outreach engine and must not
   be extended without checking that repo's classifier first.

**What Batch F did:** journalled to `social-dm-touches.jsonl` in the exact shape
a future insert would take, with both reasons recorded in every line. Nothing
fabricated into the ledger.
**Proposed fix:** `sql/004_consent.sql` §3 adds a `campaign.social_touches`
table rather than bending `touches`, and explains why extending the enum was
rejected.

## F-8. There is no usage data anywhere in the campaign ledger

**Missing:** the "pilot's usage summary" WF-C5's spec asks for in the day 12
reminder.

`campaign.pilots` holds `started_on`, `workshop_done_on`, `setup_done_on`,
`seats`, `charge_due_on`, `converted`, `stripe_customer_id`, `mrr_eur`,
`lost_reason`. Nothing about drafts written, mail handled, or people active.
Usage lives in the **product** database, which this campaign is forbidden to
touch.

**What Batch F did:** the reminder carries what the ledger actually knows and
says plainly, in the email, what it does not know and where the number would
have to come from. No usage figure is invented.
**Dovy:** if he wants real usage on that email it has to come out of the product
project, which means either a new read path or pasting it in by hand.

## F-9. USD priced, EUR column, and no honest FX rate available

**Missing:** a rate. `campaign.pilots.mrr_eur` is euros; the offer is 89 USD a
seat. Batch B's own comment says "whoever writes it must convert".

**What Batch F did:** WF-C5 refuses to guess. With `Config.usd_eur_rate` unset
it writes `converted = true` and leaves `mrr_eur` NULL, and says so in the
conversion email. A null is a known gap; a guess is a wrong number in the one
table the Friday brief adds up.
**Cost:** until a rate is set, converted pilots show in `v_market_funnel` and
`v_channel_funnel` with 0 revenue.
**Dovy: 1 minute.** Set `usd_eur_rate` in WF-C5's Config, ideally to the rate
Stripe settles at rather than a mid-market rate. `sql/004_consent.sql` §4
proposes storing `mrr_usd` and the rate used so the euro figure is auditable.

## F-2. The existing workflow set is not present, so numbering cannot be verified

**Missing:** WF1, WF4, WF5, WF6, WF9. Four searches, listed in `AUDIT.md` §3,
found no n8n export of any kind on this filesystem.

**What Batch F did:** picked a scheme that cannot collide rather than one that
happens not to. Names are `WF-C<n>`, which cannot be confused with `WF<n>`, and
**no export carries a top-level `id`**, so n8n mints a fresh one on import and
no file here can overwrite a live workflow. No fake local copy of an unseen
workflow was created.

**Largely verified 2026-09-08. No collision.** The DoviLoop workflow exports are
on this filesystem after all, in the product repo, at
`flow-savvy-automations/infra/n8n/sanitized/` (17 files). Batch F's four searches
missed them because they looked for `WF1*`-style filenames and for a
`doviloop`-named directory; the exports are named by n8n workflow id and the repo
is named `flow-savvy-automations`.

`grep -l "campaign/"` across all 17 returns **nothing**. Every webhook path they
bind, in full:

    delete-kb-document      demo-pre-warm         google-callback
    google-demo-simulation  google-voice-analysis microsoft-callback
    n8n-kb                  needs-you-redraft     popup-demo
    team-invitation         voice-analysis

None is namespaced, and none collides with any `campaign/…` path in this repo.
The `WF-C<n>` naming scheme is likewise unused there.

**CLOSED 2026-09-10, against the live instance rather than a snapshot.** The
paragraph that stood here said the committed exports rule out a collision with
DoviLoop's own 16 workflows but not with the whole instance, and asked for 30
seconds against the live API before activating. That has now been done, with the
n8n API key the founder supplied:

    GET /api/v1/workflows?limit=250
    -> 125 workflows, 21 active, 47 bound webhook paths in total

**Not one of them begins `campaign/`.** The full bound set is
`approve-send`, `customer-onboarding`, `delete-kb-document`, `demo-pre-warm`,
`demo-run`, `dsd-ingest`, `g`, `get-token`, `gg`, `google-callback`,
`google-demo-simulation`, `google-voice-analysis`, `microsoft-callback`,
`microsoft-callbac`, `n8n-kb`, `needs-you-redraft`, `nylas-callback`,
`onboard-client`, `onboard-client-tokens`, `pinecone-query`, `pinecone-stats`,
`popup-demo`, `popup-demo-multipage`, `process-document`, `rb2b-visitor`,
`regen-notes`, `run-tier1`, `run-tier2`, `run-tier3`, `sale-intake`,
`shazam-to-spotify`, `sp-pipeline-trigger`, `team-invitation`,
`team-invitation..`, plus three raw-uuid paths. All eight `campaign/…` paths in
this repo are free.

**Worth knowing, and new.** The campaign will share an n8n instance with the
LIVE PRODUCT: `viniflow-u57383` is the same host that runs WF1, WF4, WF5-v2,
WF6, WF9 and the needs-you redraft path. Six more workflows, two of them on
schedules, land beside automation that real customers depend on. That is not a
reason not to do it, but it is a reason to activate them one at a time and watch
one full run of each, exactly as the README's activation order already says.

## F-1. The `n8n-workflow-builder` skill does not exist in this container

**Missing:** the skill the spec says to read and follow. `AUDIT.md` §2 lists
four searches that found nothing.

**Blocks:** its naming, node-id, tagging and error-handling conventions could
not be followed, because they could not be read. The conventions actually used
are written out in `README.md` under "Conventions used, and why", so a later
diff against a skill-produced workflow shows exactly where they differ.

## F-3. The WF4 one-email-per-cycle limitation cannot be verified

**Missing:** WF4 itself. Taken on the spec's word and treated as true.

**Consequence, which is a real design constraint and not a formality:** nothing
in WF-C1..WF-C6 routes through WF4, chains off it, or assumes any throughput
from it. Every workflow sends its own mail through its own SMTP node.

## F-10. LinkedIn organic post analytics are not reachable

**Missing:** an API for per-post LinkedIn stats. It needs Marketing Developer
Platform approval that this account does not have.

**What Batch F did:** WF-C6 emits LinkedIn posts with a `skipped` flag and
reports the count in the brief's preamble, rather than dropping them silently or
writing zeros. A zero would read as "this reel got no views", which is worse
than an honest gap.
**Cost:** `v_content_perf` will have no rows for LinkedIn. That matters more
than it sounds, because **LinkedIn is the only channel Danish and Lithuanian
reels go to**, so two of three markets have no content performance data at all
until this is solved.

## F-11. LinkedIn video posting on the direct path is not built

**Missing:** a video post path for LinkedIn that n8n's built-in node supports.
The node has image and article categories, not video. A real LinkedIn video post
is a three-call UGC upload: register the upload, PUT the bytes, create the post
referencing the asset URN.

**What Batch F did:** wired n8n's LinkedIn node with the image category, which
posts the text plus a still frame today. The node carries a `notes` string
saying exactly this.
**Cost:** on the **direct** path only. The Buffer path handles LinkedIn video
fine, so this only bites if Buffer's API turns out not to be on Dovy's plan.
Combined with F-10, the direct path is the weaker option for `da` and `lt`.
**Dovy:** if the direct path is chosen, this needs three HTTP nodes adding, or
LinkedIn posted by hand for the two localized reels a week.

## F-12. Nothing here has ever run against n8n, a database, or any API

**Missing:** an n8n instance, a campaign database, and every credential.

- The instance at `viniflow-u57383.vm.elestio.app` was never contacted, per the
  spec.
- The only Supabase credential in this container points at the **forbidden
  product project**, confirmed for the fourth time in this campaign. The
  campaign ledger project itself is now confirmed as `yheilbuunzdugfnermfb`
  (Dovy, 2026-09-06) and is pre-filled in every Config node, but no credential
  for it exists here.
- No Buffer, Meta, YouTube, LinkedIn, Stripe or SMTP credential exists here.

**What Batch F did instead of pretending:** wrote `tools/validate.mjs`, proved
it catches real breakage with `tools/validate-selftest.mjs` (18 deliberate
breaks, all caught, plus 3 controls), and wrote `test/run-code-nodes.mjs`, which executes the
actual Code node bodies read out of the exported JSON against the real sample
payloads. 130 assertions pass. What that does and does not prove is stated
honestly in `RUN-REPORT.md`.

**Every seam to a real service in this repo is untested.** That is the truthful
statement, and it is the same untested database seam every other batch reports.
