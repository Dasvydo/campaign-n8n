# SESSION REPORT — campaign-n8n (batch F)

Branch `claude/campaign-build-status-9j9194`, from a clean clone.
Node, `python3` and `git` only. Nothing was imported into n8n, no live API was
called, no migration was run, no repository visibility was changed.

## Verified

Every number below is what the command printed in this session, not an
expectation copied from a document.

| Command | Result |
|---|---|
| `node tools/validate.mjs` | **6 files, 157 nodes, 0 errors, 0 warnings** |
| `node tools/validate-selftest.mjs` | **16 passed, 0 failed** |
| `node test/run-code-nodes.mjs` | **135 passed, 0 failed** |
| `node tools/check-regen.mjs` | **all 6 workflow exports match `tools/build_workflows.py`** |
| `node tools/check-sibling-invocations.mjs` (before cloning siblings) | **0 verified, 2 skipped** |
| `node tools/check-sibling-invocations.mjs` (after cloning siblings) | **all 2 verified** |

Per-file node counts from `validate.mjs`: C1 24 / C2 27 / C3 37 / C4 25 /
C5 28 / C6 16, with 1 / 3 / 2 / 3 / 2 / 1 triggers respectively.

To make the sibling check real rather than skipped, both siblings were cloned
beside this repo and put on the same branch:

- `../ad-engine` at `59848d3` on `claude/campaign-build-status-9j9194`
- `../campaign-ledger` at `8bc38f3` on `claude/campaign-build-status-9j9194`

It then resolved both invocations WF-C6 shells out to:
`ad-engine/report/pull_ad_stats.py` and `campaign-ledger/src/friday_brief.py`.
Both files exist on that branch today.

All five checks were re-run after the documentation change and returned the
same numbers. No file under `workflows/` was modified in this session, so
`check-regen.mjs` still passes for the reason it should.

## Produced

- **`ops/ACTIVATION-PRECHECK.md`** (commit `9b5d81f`) — everything needed before
  importing the six workflows into a live n8n instance, derived from the JSON
  exports. Ordered WF-C1, WF-C2, WF-C6, WF-C3, WF-C4, WF-C5, the documented
  activation order. For each workflow: every credential by exact name with the
  node that needs it; every webhook path with method, authentication setting
  and respond mode; every cron expression with a plain-English reading; every
  sibling script with the repo it expects beside it; and every Config field
  that must be filled by hand, marked blank / prefilled / confirm.

  It opens with the P-4 warning — all eight webhook bindings unauthenticated
  while five of six repos are public — described, not fixed.

- **`SESSION-REPORT.md`** — this file.

Nothing else was added or changed. `ops/HANDOFF.md`, `NEW-PC-SETUP.md`,
`DECISIONS.md`, `NIGHT-RUN.md` and `STATUS.md` were read for context and left
untouched, as were all six exports, `tools/build_workflows.py`, and
`sql/004_consent.sql` (still NOT RUN, NOT APPLIED — P-3).

## Found

Ordered by how much they would cost.

1. **WF-C4 reads the ledger with no `Guard: ledger target` node.** Five
   workflows carry the Supabase credential; only four carry the guard. C1, C3,
   C5 and C6 throw if `ledger_url` names the forbidden product project
   `kngcxwcybozgqgnoweyt`; WF-C4's `Ledger: find the reel` does not. Three
   documents state the invariant more broadly than the exports support:
   `README.md:91` and `CREDENTIALS.md:57` both say *every* ledger-touching
   workflow runs the guard, and `RUN-REPORT.md:295` says "all four", which is
   the accurate count but not the complete set. The exposure is narrow — it is
   a GET, on the campaign Supabase credential — but the refusal that protects
   the other four is genuinely absent. Not fixed: adding a node means editing
   `tools/build_workflows.py` and regenerating, which changes an export, and
   the guard's placement is a design call on a workflow whose two entry paths
   both reach that node.

2. **WF-C4 and WF-C5 each carry two Config nodes, one per entry path.**
   WF-C4 has `Config` and `Config approve`; WF-C5 has `Config` and
   `Config webhook`. Each pair is byte-identical today. Nothing in the repo
   checks that they stay in sync, and no document mentions the duplication —
   so filling `approve_base` or `price_seat_monthly` in one and not the other
   is a silent half-configuration. Called out in the precheck document; not
   otherwise changed.

3. **WF-C6 needs two environment variables nobody has written down.**
   `README.md` names `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` for the n8n
   process environment. Read directly from the sibling checkouts,
   `ad-engine/report/pull_ad_stats.py:451-452` also requires
   **`META_AD_ACCOUNT_ID`** and **`META_ACCESS_TOKEN`**, and without them exits
   2 with an error rather than producing ad numbers. These are not in
   `README.md` or `CREDENTIALS.md`. They fail loudly and WF-C6 still sends the
   brief, so this costs a Friday's ad figures, not a silent wrong answer. Both
   are now in the precheck document.

4. **`README.md:344` says the node harness is `130 assertions`. It reports
   135.** Stale comment. `ops/DECISIONS.md:95` already has the right number.
   Left alone — it is a one-word fix in a file outside this task.

5. **`ops/DECISIONS.md:256` counts "all eight webhook paths" and then lists
   seven.** Both readings are defensible and the export settles it: there are
   **eight webhook bindings on seven distinct paths**, because
   `campaign/meta-comments` is bound twice, GET for Meta's `hub.challenge`
   handshake and POST for comment events. `README.md`'s webhook table says
   "all seven" and then lists eight rows, which is the same fact from the other
   side. The precheck document states it both ways to end the ambiguity.

6. **`ops/DECISIONS.md:253` cites `campaign-n8n/README.md:342` for the n8n
   hostname; it is now at `README.md:366`.** The content is unchanged and
   correct. Stale line reference only.

7. **Neither sibling script needs a `pip install`.** Both import standard
   library only; every entry in both `requirements.txt` files is test-only
   (`sqlglot` for campaign-ledger, `Pillow`/`pytest` for ad-engine). Worth
   knowing before provisioning the n8n host — it is one less thing to get
   wrong, not a problem.

8. **No workflow references `$env` anywhere.** Every tunable is a Config node
   field. The four environment variables above are read by the *sibling Python
   scripts*, not by n8n, which is why they cannot be set from Config. This is
   a coherent design, recorded so it is not mistaken for an omission.

Restated because it is the largest thing here and it is not mine to touch:
**every one of the eight webhook bindings has the `authentication` key absent
from its parameters** — n8n's `None` — while this public repo publishes both
the instance hostname and every path. `campaign/content-approve` is the gate
this repo's own README calls the one that matters most, and it carries no token
check. That is **P-4**, parked for the founder.

## Blocked

Nothing in the assigned task was blocked. Everything requested was produced and
every check was run and passed.

Out of scope by instruction, listed so the boundary is explicit:

- **P-1 … P-6 in `ops/DECISIONS.md`** were not acted on. P-4 (repo visibility
  and webhook authentication) is described in the precheck document and
  deliberately not fixed: it needs an outward-facing visibility decision, a
  matching credential created inside n8n, and the real Stripe `whsec_` signing
  secret — and half the change breaks the campaign's one working end-to-end
  path.
- **`sql/004_consent.sql`** left NOT RUN and NOT APPLIED (P-3).
- **Finding 1 (WF-C4's missing guard)** needs a decision, then an edit to
  `tools/build_workflows.py` and a regeneration — it cannot be hand-edited into
  the export, and `check-regen.mjs` enforces that.
- **Path-collision check against the five pre-existing workflows** (WF1, WF4,
  WF5, WF6, WF9) could not be done: this container has no copy of them and
  reaching the n8n instance was out of bounds. `BLOCKED.md` F-2 already records
  it; the precheck document repeats it as a pre-activation step, because a
  duplicate `campaign/` webhook path is a live conflict.
- **Nothing was tested against a real Supabase, Meta, Buffer, YouTube, LinkedIn
  or Stripe account.** No credential exists in this container and none was
  asked for. Every claim in the precheck document is derived from the exports
  and from the two sibling checkouts, never from a live call.
