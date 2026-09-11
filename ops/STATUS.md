# Campaign build — status report (CORRECTED)

Rewritten 2026-09-08, later the same evening. **The first version of this file was materially wrong
and its main conclusions have been reversed.** What changed, and why, is in §0.

---

## 0. Correction — read this before anything else

The first report concluded that batches C, D and E "did not finish" and that all five repos had been
pushed in violation of the branch rules. **Both conclusions were wrong.** Two mistakes caused it:

**Mistake 1 — I audited the wrong branch in three repos.** Each batch did its work on a branch named
`campaign/<letter>-<name>`. When this session started, `outreach-engine`, `ad-engine` and
`reel-engine` had `main` checked out — the bare scaffold — and I audited what was in front of me
without checking whether it was the batch's branch. The real work was one `git fetch` away the whole
time:

| Repo | What I audited | What I should have audited | Size of what I missed |
|---|---|---|---|
| outreach-engine (C) | `main` @ `037c2af` | `campaign/c-outreach` @ `b9eb1e0` | 44 files, 7,449 insertions |
| reel-engine (D) | `main` @ `342262b` | `campaign/d-reels` @ `0584052` | 69 files, 9,537 insertions |
| ad-engine (E) | `main` @ `a214e58` | `campaign/e-ads` @ `e40f949` | 65 files, 3,886 insertions |

**Mistake 2 — I read local remote-tracking refs as proof of a push.** `git show-ref` listed
`refs/remotes/origin/claude/campaign-build-status-9j9194` in every repo, and I treated that as
evidence the work was on GitHub. Those refs were created locally when the session was set up. Asking
GitHub directly (`list_branches`) showed the branch did not exist on any repo. **There was no rule
violation.** The work was pushed, correctly, to the per-batch `campaign/*` branches.

Everything below reflects the real branches, re-verified from scratch.

**Current state of this workspace:** all six repos are now checked out on
`claude/campaign-build-status-9j9194`, each based on its own `campaign/*` branch, and each pushed.

---

## 1. All six batches finished

Every repo has all three process files. The earlier claim that C, D and E had none was an artifact
of reading `main`.

| Batch | Repo | Branch base | Commits | RUN-REPORT | AUDIT | BLOCKED | Deps manifest |
|---|---|---|---|---|---|---|---|
| A | campaign-site | `campaign/a-site` | 11 | ✅ | ✅ | ✅ | `package.json` |
| B | campaign-ledger | `campaign/b-ledger` | 6 | ✅ | ✅ | ✅ | ✅ *(added tonight)* |
| C | outreach-engine | `campaign/c-outreach` | 12 | ✅ | ✅ | ✅ | ✅ |
| D | reel-engine | `campaign/d-reels` | 120 | ✅ | ✅ | ✅ | ✅ |
| E | ad-engine | `campaign/e-ads` | 11 | ✅ | ✅ | ✅ | ✅ *(added tonight)* |
| F | campaign-n8n | `campaign/f-n8n` | 7 | ✅ | ✅ | ✅ | n/a (node, no deps) |

All six working trees are clean. No repo tracks build junk (`__pycache__`, `.pyc`, `out/`,
`node_modules`) — checked in all six.

---

## 2. Tests — everything passes once dependencies are installed

The first report described three "broken" suites. None were broken. All three were missing a
dependency in this container, and two of the repos had no manifest to install from — which is a real
problem, but a different one, and exactly what would have bitten you on the new PC.

| Repo | Command | Result |
|---|---|---|
| campaign-ledger | `python3 tests/run_local_proof.py` | **46 passed, 0 failed** (needs `sqlglot`) |
| outreach-engine | `python3 -m pytest tests/ -q` | passes (needs `dnspython`, was already declared) |
| ad-engine | `python3 -m pytest tests/ -q` | **89 passed** (needs `Pillow` + `pytest`) |
| reel-engine | `python3 -m pytest -q -m "not slow and not network"` | **441 passed** |
| campaign-n8n | `node tools/validate.mjs` | 6 files, 157 nodes, **0 errors** |
| campaign-n8n | `node tools/validate-selftest.mjs` | **21 passed, 0 failed** |
| campaign-n8n | `node test/run-code-nodes.mjs` | **135 passed, 0 failed** |
| campaign-site | `npm run verify:payload` | **cannot run here** — `node_modules` absent |

**The one genuine test-environment problem is not a repo defect.** `reel-engine`'s render and
browser tests error because Playwright wants `chromium_headless_shell-1234` and this container ships
`-1194`. That is a container mismatch. Do not "fix" it in the repo.

**`campaign-ledger`'s "46 checks, 0 failures" claim is now reproducible.** It previously read 45/1
from a clean clone because `sqlglot` was documented only in prose (`README.md:265`) with no
manifest. That is fixed (§6).

---

## 3. Batch F was right, and I was wrong about it

The first report said batch F cited a file that does not exist —
`reel-engine/engine/ledger.py` with `CONTENT_COLUMNS`. **That file exists**, on `campaign/d-reels`,
with `CONTENT_COLUMNS` defined at line 75 and used at lines 107, 111, 112 and 210. F read it
correctly. The same goes for F's `publish.py` citations, which I had already confirmed verbatim.

Two more retractions:

- **`pull_ad_stats.py` is not missing.** Batch E built it at `ad-engine/report/pull_ad_stats.py`
  (334 lines), with `report/ledger_shim.py`, `report/fixtures/insights_sample.json` and
  `tests/test_ad_stats.py`. Its commit message is *"Part 4: pull_ad_stats.py with fixture, clean dry
  run, and a defensive ledger seam."* Worth confirming that WF-C6's `executeCommand` node invokes it
  at the `report/` path E actually used.
- **The ledger seam exists in C, D and E.** Both C and D ship a `tests/test_ledger_contract.py`
  (505 and 158 lines). D has a commit *"Stop forwarding our own content id into Batch B's
  upsert_content."* The earlier claim that "seven of ten ledger tables have no producer" was a
  consequence of reading scaffold branches and is withdrawn.

---

## 4. The stale-price problem is smaller than it looked, but not gone

`docs/ICP-BRIEF.md` is byte-identical across C, D and E on `main` and carries the old offer —
`$49/seat/mo` design-partner, `$99` standard, `$750` onboarding, locked 2026-08-31. The campaign
(A, B, F) uses **$89/seat/mo + $500 setup**, confirmed by you on 2026-09-06.

**On the real branches this is already handled**, at least in E, whose `campaign/e-ads` copy reads:

> *Price settled by Dovy on 2026-09-06 and recorded in `claims/evidence.json` (`price`, verified).
> The earlier $49 / $99 tiers and the $750 onboarding fee in this table are withdrawn.*

Worth confirming the same correction landed in C's and D's copies of that brief — it is one file
duplicated three ways, which is how it drifted in the first place.

**Still genuinely open: the 9x ROI figure.** Batch F flagged it in `BLOCKED.md` F-5/F-9 and the
arithmetic does not work. ~400 EUR/month against an 89 USD (~82 EUR) seat is roughly **5x**, not 9x.
The 9x holds against a ~45 EUR seat, which is where the withdrawn $49 price sat. The figure is live
on the landing page in three languages and in WF-C2's email 2. This is a **decision for you**, not
something to quietly rewrite — it is public marketing copy.

---

## 5. Safety — clean across all six real branches

Re-run against git-tracked text files only, on the correct branches:

- **Secrets: one hit, and it is deliberate.** `campaign-n8n/tools/validate-selftest.mjs:45` contains
  a fabricated JWT used to prove the secret scanner fires. Nothing else. No `.env` is committed in
  any repo, and all six `.gitignore` files now cover `.env`.
- **Production project `kngcxwcybozgqgnoweyt`:** every reference is a defensive guard or an audit
  note. `campaign_db.py:75` refuses it at startup; four of the six n8n workflows carry a
  `Guard: ledger target` node that throws on it; `tools/validate.mjs:26` fails any workflow
  containing it; `tests/run_local_proof.py` sets it deliberately to assert the refusal, and further
  asserts the ref appears in no `.sql` file at all. The campaign points at `yheilbuunzdugfnermfb`,
  schema `campaign`. **This is handled better than the brief required.**
- **Migrations:** all four are file-only. Nothing executes DDL. `campaign-n8n/sql/004_consent.sql`
  is explicitly headed *"STATUS: NOT RUN. NOT APPLIED."*
- **n8n exports:** all six are `active: false`, carry credential **names** only — no ids, no values,
  no inline Authorization headers — and have no top-level `id`, so importing one cannot overwrite an
  existing workflow.

---

## 6. What changed on disk tonight

Three commits, each pushed to `claude/campaign-build-status-9j9194`:

| Repo | Commit | What |
|---|---|---|
| campaign-n8n | `a5cbcd5` | Added the `.gitignore` the repo never had. Verified with `git check-ignore` that no already-tracked file becomes ignored. |
| campaign-ledger | `850050b` | `requirements.txt` declaring `sqlglot`, so the 46-check gate is reproducible from a clean clone. |
| ad-engine | `8906411` | `requirements.txt` declaring `Pillow` (needed by `creative/static/vet.py`) and `pytest`. The repo had no manifest at all. |

Also done: `reel-engine` was cloned and added to the session; all six repos were moved onto
`claude/campaign-build-status-9j9194` based on their real `campaign/*` branch; and all six branches
now exist on GitHub.

One piece of branch housekeeping worth knowing about: `ad-engine`'s and `reel-engine`'s
`claude/*` branches were briefly pushed from `main` before the mistake in §0 was found.
`reel-engine` fast-forwarded onto the correct base. `ad-engine` carries one `-s ours` merge
(`5cc3fa5`) that absorbs the superseded tip rather than force-pushing over it — nothing was
discarded, and no `campaign/*` branch was touched.

---

## 7. Where this actually stands

The campaign is in far better shape than the first report suggested. Six batches, all finished, all
self-tested, all honest about their own gaps in their own `BLOCKED.md` files. The real remaining
work splits cleanly:

**Blocked on you, and nothing can move it tonight:** exposing schema `campaign` to PostgREST and
running migrations 001–003; importing the six workflows into n8n and creating their seven
credentials; the five Vercel env vars; a Meta Business account; a booking link; PostHog keys; and a
native Danish and Lithuanian copy review.

**Genuinely open decisions:** the 9x vs 5x ROI figure (§4), and whether the under-10 nurture opt-in
becomes a real POST instead of the current `mailto:` (batch F's `BLOCKED.md` F-4).

**Delegable, and being worked tonight:** the ordered plan is in `NIGHT-RUN.md`, and the morning
handoff plus new-PC setup guide will land beside it.

The single highest-leverage thing you can do tomorrow is the one-minute Supabase setting: **Settings
→ API → Exposed schemas → add `campaign`.** Every ledger write in the campaign is behind it.
