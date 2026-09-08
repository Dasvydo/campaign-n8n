# Handoff — morning of 2026-09-09

Written at the end of the 2026-09-08 night run. Everything below is pushed to
`claude/campaign-build-status-9j9194` in all six repos.

---

## The one-line version

All six batches were already finished. The night's value was **two real defects in the seams
between them** — the places every batch author correctly reported they could not see — plus making
all six reproducible from a clean clone. The campaign is roughly **half an hour of your account
work** from being live, gated on four decisions.

---

## What was wrong when the night started, and is now right

### Two genuine defects, both verified before and after

**`ad-engine` was sending a creative slug into a `uuid` column** (`56c7469`).
`report/pull_ad_stats.py` derived `v5-pilot` from the ad name and passed it as
`creative_content_id`, which `campaign-ledger/migrations/001_schema.sql:388` declares
`uuid references campaign.content (id)`. Postgres would have rejected it — **on the first live
write, after passing every offline test**, because the JSONL shim accepts any string. All eight
fixture rows were affected. Batch B's own docstring settled the fix: pass `None` rather than guess.
The label is kept as `utm_content`, shown in the dry-run table and summarised once per run.
Verified by simulating the real `campaign_db` signature: 8 rows, all `creative_content_id=None`,
keys exactly the ledger's eight columns. **94 tests, up from 89.**

**Phone leads were being attributed to `direct`, not `outreach`** (`4a624ac`).
The three phone sequences link with `utm_source=phone&utm_medium=call`. `campaign-site`'s
`resolveSource` maps `outreach` only for medium ∈ {outreach, email, dm} or source ∈
{instantly, linkedin} — so every phone lead fell to the `direct` default, in exactly the market
your three-way A/B exists to compare. Cold calling would have looked like it produced nothing.
Fixed with `&source=outreach`, the explicit override `campaign-site` already documents, so no site
code changed. Verified by running the site's real attribution module: phone → `direct` before,
`outreach` after, linkedin and email controls unchanged.

### Reproducibility, which is what would have bitten you on the new PC

- `campaign-ledger` had no `requirements.txt`; a clean clone reported **45/46** because `sqlglot`
  was documented in prose only. Now **46/46** (`850050b`).
- `ad-engine` had no dependency manifest at all. `creative/static/vet.py` needs Pillow, and the
  suite needs pytest — without which running a test file directly asserts *nothing* and exits 0
  (`8906411`).
- `ad-engine`'s `PYTHONPATH` instruction was **off by one directory** (`bb0b453`). Following it
  produced a clean-looking run that wrote to JSONL and never reached Postgres, because the shim
  swallows the ImportError by design.
- `outreach-engine`'s README told a clean machine to run pytest without installing it (`1cac213`).
- `campaign-n8n` had **no `.gitignore`** — the only repo without one (`a5cbcd5`).
- All five sibling repos now point at these documents and state the sibling-directory requirement
  (`ae9c6e1`, `74f59dc`, `4409d1b`, `c67f329`, `9944578`).

### The thing worth knowing about the ledger seam

Batches C, D and E each `import campaign_db` and **fall back to a local JSONL shim** when it is
absent. That is why they were buildable while B was still being written — and it means a
misconfigured path looks exactly like success. **This was never tested end to end before tonight.**
It works: with `campaign-ledger/src` on `PYTHONPATH`, all three switch to the real client and their
contract suites pass against it (28 / 8 / 13). Every table in `campaign` has a writer.

Two traps documented in the engine READMEs:

- **`outreach-engine`'s full suite must run with `PYTHONPATH` unset.** With the real ledger on the
  path it reports 3 failed + 9 errors — that is `use_shim_dir()`'s guard refusing to let a test
  write to a real database (`engine/ledger.py:725`). The guard is correct.
- **The contract tests do not use `PYTHONPATH` at all.** They find `campaign_db.py` by *file path*
  — `../campaign-ledger/src/campaign_db.py` — and load it under a different module name, which is
  precisely why both suites can coexist. Without the sibling checkout they **skip rather than fail**,
  so the suite reads green while 28 seam assertions quietly did not run.

---

## Verified baseline, all six, at handoff

| Repo | Command | Result |
|---|---|---|
| campaign-ledger | `python3 tests/run_local_proof.py` | **46 passed, 0 failed** |
| outreach-engine | `python3 -m pytest tests/ -q` *(PYTHONPATH unset)* | **138 passed** |
| outreach-engine | `python3 -m pytest tests/test_ledger_contract.py -q` | **28 passed** |
| reel-engine | `PYTHONPATH=…/src python3 -m pytest tests/test_ledger_contract.py -q` | **8 passed** |
| ad-engine | `python3 -m pytest tests/ -q` | **94 passed** (was 89) |
| campaign-n8n | `node tools/validate.mjs` | 6 files, 157 nodes, **0 errors** |
| campaign-n8n | `node tools/validate-selftest.mjs` | **16 passed, 0 failed** |
| campaign-n8n | `node test/run-code-nodes.mjs` | **135 passed, 0 failed** |
| campaign-site | `npm ci && npm run build && npm run verify:payload` | build clean, **87 assertions pass** |

`reel-engine`'s render tests error in a container whose Playwright build does not match
(`chromium_headless_shell-1234` wanted, `-1194` shipped). On your machine
`python3 -m playwright install chromium` resolves it. **441 pass** otherwise.

---

## What needs you — in the order that unblocks the most

### 1. Decide the four open questions

These were deliberately not guessed. Full reasoning and options in `ops/DECISIONS.md`.

| | Decision | Why it is yours |
|---|---|---|
| **P-4** | **Repo visibility and webhook auth — settle this BEFORE activating n8n.** Five of six repos are public; they publish your n8n hostname and all eight webhook paths; every webhook is `authentication: NONE`. The sharpest is `campaign/content-approve`, which your own README calls the gate that matters most because it is what publishes in public — and it carries no token check. `campaign/qualifier` also sets `allowedOrigins: "*"`, and WF-C5 tests for a `stripe-signature` header's *presence*, not its validity. | Visibility is outward-facing; adding auth needs a matching credential inside n8n, and half the change breaks the one working path. |
| **P-1** | **The 9x ROI figure.** ~400 EUR/month against an 89 USD (~82 EUR) seat is ~**4.9x**. 9x held at the withdrawn $49 rate. Live in three languages and in WF-C2's email 2. | Public marketing copy in languages nobody has reviewed. |
| **P-2** | **Nurture opt-in.** The 1-9 opt-in is a `mailto:`, so consent never reaches n8n and WF-C2 stays manual. ~15 minutes to make it a POST, but it also needs `sql/004_consent.sql`. | Changes the shared contract and depends on a migration only you run. It is also the one place the campaign chose legal caution deliberately. |
| **P-3** | **Where `sql/004_consent.sql` lives.** It is a `campaign-ledger` migration sitting in `campaign-n8n` because Batch F may not write to a sibling repo. Marked `NOT RUN. NOT APPLIED.` | Running it is your action. |

### 2. Then the account work — about half an hour

Full commands and expected outputs in `ops/NEW-PC-SETUP.md` §4.

1. **Supabase → Settings → API → Exposed schemas → add `campaign`.** One minute, and every ledger
   write in the campaign is behind it.
2. Run `001_schema.sql` → `002_rls.sql` → `003_views.sql` against `oqpeebtwtikdzorgouxd`. Check the
   project ref in the URL bar first — the migrations deliberately contain no reference to the
   product project, so nothing pasted from them can aim at it.
3. Import the six workflows and create the seven credentials named in `CREDENTIALS.md`. They are
   referenced **by name only**, so the names must match exactly. Check no existing workflow already
   binds a `campaign/…` path (Batch F could not, two minutes).
4. Copy WF-C1's production webhook URL into `VITE_LEAD_WEBHOOK_URL`, then set the other four Vercel
   variables. Every one degrades safely when empty — but with that one unset in production, leads
   land in a localStorage recovery queue instead of the ledger.
5. Drop in `public/demo.mp4`, `public/logo.png`, and the footer `company` block in all three locales.

### 3. Standing items, no deadline

- A **native Danish and Lithuanian read** of `campaign-site/src/content/{da,lt}.ts` and
  `outreach-engine/sequences/`. Both are headed `NEEDS NATIVE CHECK`, and the campaign runs paid
  Meta traffic into an EU audience.
- The **Danish marketing-law confirmation** that gates all Danish email. WF-C2 needs
  `dk_marketing_law_confirmed: true` set by hand in its Config *and* on the lead. Neither alone.
- **`reel-engine`'s `propose.yml` cron.** It is not broken. It fails roughly half its runs because
  the **editorial gate rejects the generated script** and stops — which is the gate working. But
  the reason is worth reading: it objects that bookkeeping/VAT questions "require professional
  judgment rather than straightforward database lookups", which is *the same test* as ICP gate G3.
  `docs/ICP-BRIEF.md` says so outright: "A segment that fails the reel gate would also fail as a
  customer." That may be telling you bookkeeping firms are a weaker segment, not that the copy is
  wrong.

---

## What is still open in the plan

`ops/NIGHT-RUN.md` carries the full table. Wave 1 is complete. Wave 2 — mostly tests that pin the
seams, plus a few documentation corrections — is unstarted, and none of it blocks going live. The
deferred items (objection copy refresh, the week-01 re-render, the golden-frame comparison, and
whether to write `ops/CONTRACTS.md`) all need a judgement rather than an hour.

One reversal worth flagging: the plan originally said to reconstruct the lost
`campaign-specs/00-START-HERE.md`. That was dropped deliberately. A reconstructed spec would read
as authoritative while being back-formed from the code, and the next reader could not tell which
lines were decided and which were inferred. The safer shape — an `ops/CONTRACTS.md` documenting the
contract *as implemented*, with `file:line` on both sides and an explicit note that the original is
lost — is left as your call.
