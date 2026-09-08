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

### P-3 — Where `sql/004_consent.sql` should live

It is a migration for `campaign-ledger` that sits in `campaign-n8n`, because batch F may not write
to a sibling repo. It is marked `STATUS: NOT RUN. NOT APPLIED.` If Dovy accepts it, it should move
to `campaign-ledger/migrations/004_consent.sql` and run in sequence after 003. That is his call
because running it is his action.
