# New PC setup — get the whole campaign running from a clean machine

Written 2026-09-08 for the move to a new computer. Everything here was verified in a clean
container tonight; where something could not be verified, it says so.

The campaign is **six repositories**. There is no monorepo and no parent project. Clone all six
into one folder — several tools reach across repos by relative path, so the folder layout matters.

---

## 1. Prerequisites

| Tool | Version | Needed by |
|---|---|---|
| `git` | any recent | all |
| `python3` | 3.11+ | B, C, D, E |
| `pip` | any recent | B, C, D, E |
| `node` | 20+ | A, F |
| `npm` | 10+ | A |
| `ffmpeg` | any recent | D only (reel rendering) |

`ffmpeg` is only needed if you intend to render reels on this machine. Everything else in the
campaign works without it.

---

## 2. Clone all six into one parent folder

The folder name is up to you; the **sibling layout is not**. Batch F's `WF-C6` runs
`friday_brief.py` and `pull_ad_stats.py` by path on the n8n host, and batch E reads batch C's
output by relative path.

```bash
mkdir -p ~/campaign && cd ~/campaign

git clone https://github.com/Dasvydo/campaign-site.git
git clone https://github.com/Dasvydo/campaign-ledger.git
git clone https://github.com/Dasvydo/outreach-engine.git
git clone https://github.com/Dasvydo/reel-engine.git
git clone https://github.com/Dasvydo/ad-engine.git
git clone https://github.com/Dasvydo/campaign-n8n.git
```

You should end up with:

```
~/campaign/
  campaign-site/       batch A   landing page, teams.doviloop.dev
  campaign-ledger/     batch B   Postgres schema + PostgREST client + Friday brief
  outreach-engine/     batch C   cold outreach: registry -> enrich -> gate -> sequence -> export
  reel-engine/         batch D   content engine: scripts, render, captions, publish
  ad-engine/           batch E   Meta ads: audiences, creative, claims gate
  campaign-n8n/        batch F   six importable n8n workflows (this repo)
```

### Which branch to check out

Each repo has **two** branches that matter. `main` is in most cases only a scaffold — do not
work from it.

```bash
cd ~/campaign
for r in campaign-site campaign-ledger outreach-engine reel-engine ad-engine campaign-n8n; do
  ( cd "$r" && git fetch origin && git checkout claude/campaign-build-status-9j9194 )
done
```

| Repo | Batch branch (the real work) | Also on | Notes |
|---|---|---|---|
| campaign-site | `campaign/a-site` | `claude/campaign-build-status-9j9194` | no `main` on the remote |
| campaign-ledger | `campaign/b-ledger` | `claude/campaign-build-status-9j9194` | no `main` on the remote |
| outreach-engine | `campaign/c-outreach` | `claude/campaign-build-status-9j9194` | `main` is the bare scaffold |
| reel-engine | `campaign/d-reels` | `claude/campaign-build-status-9j9194` | `main` is the pre-campaign engine |
| ad-engine | `campaign/e-ads` | `claude/campaign-build-status-9j9194` | `main` is the bare scaffold |
| campaign-n8n | `campaign/f-n8n` | `claude/campaign-build-status-9j9194` | `main` is the bare scaffold |

> **This is the single easiest way to lose a day.** Three of these repos have a `main` that looks
> like a real project but is only the initial scaffold. An audit of this build was written against
> those scaffolds and concluded three batches had never been done. They had. Check the branch.

---

## 3. Install and prove each repo

Run these in order. Each one ends with a command that proves the repo works, and the expected
result. If a number differs from what is written here, that is a real signal — investigate before
moving on.

### B — campaign-ledger

```bash
cd ~/campaign/campaign-ledger
pip install -r requirements.txt          # sqlglot; the runtime itself has no dependencies
python3 tests/run_local_proof.py         # expect: 46 passed, 0 failed
python3 tools/validate_sql.py            # expect: 3 files ok, 67 statements parsed
```

The proof runs entirely offline against a SQLite mirror. It never connects to Supabase.

### C — outreach-engine

```bash
cd ~/campaign/outreach-engine
pip install -r requirements.txt          # dnspython, PyYAML
python3 -m pytest tests/ -q              # expect: all pass
```

### D — reel-engine

```bash
cd ~/campaign/reel-engine
pip install -r requirements.txt          # Pillow, playwright, edge-tts, imageio-ffmpeg, google-genai
python3 -m playwright install chromium   # needed by the render and verify tests
python3 -m pytest -q -m "not slow and not network"   # expect: ~441 passed
```

The `slow` marker renders a full 750-frame reel and takes minutes; `network` calls edge-tts and
will fail on a rate limit. Both are excluded above on purpose.

> Tonight's container could not run D's render tests: its Playwright build wanted
> `chromium_headless_shell-1234` and the image shipped `-1194`. That is an environment mismatch,
> not a repo bug. On your own machine `playwright install chromium` resolves it.

### E — ad-engine

```bash
cd ~/campaign/ad-engine
pip install -r requirements.txt          # Pillow (for creative/static/vet.py), pytest
python3 -m pytest tests/ -q              # expect: 89 passed
```

### F — campaign-n8n

No dependencies. Node only.

```bash
cd ~/campaign/campaign-n8n
node tools/validate.mjs                  # expect: 6 files, 157 nodes, 0 errors, 0 warnings
node tools/validate-selftest.mjs         # expect: 16 passed, 0 failed
node test/run-code-nodes.mjs             # expect: 135 passed, 0 failed
```

`validate-selftest.mjs` is the one to trust: it takes the real WF-C1 export, breaks it fifteen
ways, and asserts each break is caught. A validator that has never failed is indistinguishable
from one that cannot fail.

### A — campaign-site

```bash
cd ~/campaign/campaign-site
npm install
npm run build                            # tsc -b && vite build
npm run verify:payload                   # boots a local mock and posts a real payload at it
```

---

## 4. The things only you can do

None of the below can be automated from a container — they need your accounts. They are ordered
by how much they unblock.

### 4.1 Expose the `campaign` schema — one minute, unblocks everything

Supabase dashboard → project **`oqpeebtwtikdzorgouxd`** → **Settings → API → Exposed schemas** →
add `campaign` → save.

Until this is done, every ledger write from batches C, D, E and the Friday brief returns
`PGRST106 (schema not in search path)`. This is the highest-leverage minute in the whole project.

### 4.2 Run the migrations

In the Supabase SQL editor, on project `oqpeebtwtikdzorgouxd`, in this order:

```
campaign-ledger/migrations/001_schema.sql
campaign-ledger/migrations/002_rls.sql
campaign-ledger/migrations/003_views.sql
```

Every statement is guarded (`IF NOT EXISTS` / `DO $$ ... EXCEPTION WHEN duplicate_object`), so the
files are safe to re-run.

**Check the project ref in the URL bar first.** If it reads `kngcxwcybozgqgnoweyt`, stop — that is
the product database. The migrations deliberately do not contain that string anywhere, so nothing
you paste from them can aim at it.

There is a fourth, **proposed** migration at `campaign-n8n/sql/004_consent.sql`. It is marked
`STATUS: NOT RUN. NOT APPLIED.` and adds a consent record, a `leads.opt_out` column, a
`content.approved_at` column, and a `social_touches` table. Read its reasoning before deciding.
If you accept it, move it into `campaign-ledger/migrations/` as `004_` so it lives with the others.

### 4.3 Set the ledger credentials, and connect the engines to the ledger

**Only `campaign-ledger` reads the Supabase variables.** Copy its `.env.example` to `.env` and
fill in:

```
SUPABASE_URL=https://oqpeebtwtikdzorgouxd.supabase.co
SUPABASE_SERVICE_KEY=<the service role key for THAT project>
```

**Note the variable name.** The client reads `SUPABASE_SERVICE_KEY`, not
`SUPABASE_SERVICE_ROLE_KEY`. That is deliberate: many environments already export the latter
pointing at the product database, and reading a different name means the ledger can never pick it
up by accident. `campaign_db.py` also refuses at startup if `SUPABASE_URL` contains the product
ref.

The other repos have their own `.env.example` files carrying **their own** API keys —
`outreach-engine` wants Google CSE, Instantly and Anthropic keys plus `CAMPAIGN_DB_URL`;
`reel-engine` wants Gemini, Higgsfield and YouTube keys; `ad-engine` wants the Meta trio. None of
them reads `SUPABASE_*`.

#### How the engines actually reach the ledger

Batches C, D and E each try `import campaign_db` and **fall back to a local JSONL shim** when it is
not importable. That is why they were buildable while batch B was still being written. To make them
write to Postgres instead of JSONL, put batch B's `src` on the Python path:

```bash
export PYTHONPATH=~/campaign/campaign-ledger/src
```

Verified tonight — this flips all three from shim to real:

```bash
cd ~/campaign/outreach-engine
python3 -c "import sys; sys.path.insert(0,'.'); from engine import ledger; print(ledger.using_real_ledger())"
#   without PYTHONPATH -> False        with PYTHONPATH -> True

cd ~/campaign/reel-engine
python3 -c "import sys; sys.path.insert(0,'.'); from engine import ledger; print(ledger.available())"
#   without PYTHONPATH -> False        with PYTHONPATH -> True
```

The seam is proven by each engine's own contract suite, run **with** the ledger on the path:

```bash
cd ~/campaign/outreach-engine && PYTHONPATH=~/campaign/campaign-ledger/src python3 -m pytest tests/test_ledger_contract.py -q   # 28 passed
cd ~/campaign/reel-engine     && PYTHONPATH=~/campaign/campaign-ledger/src python3 -m pytest tests/test_ledger_contract.py -q   # 8 passed
cd ~/campaign/ad-engine       && PYTHONPATH=~/campaign/campaign-ledger/src python3 -m pytest tests/test_ad_stats.py -q          # 13 passed
```

> ### ⚠ Do not set PYTHONPATH globally, then run outreach-engine's full suite
>
> `outreach-engine` is **138 passed** on its own, and **3 failed + 9 errors** with
> `campaign-ledger/src` on the path. Nothing is broken. Its test fixtures call
> `engine.ledger.use_shim_dir()`, which deliberately raises
> `RuntimeError: use_shim_dir() must never run against the real ledger` (`engine/ledger.py:725`)
> so a test run can never write to a real database. The guard is correct and should stay.
>
> **The rule:** run each engine's *full* suite with `PYTHONPATH` unset, and its
> `test_ledger_contract.py` with `PYTHONPATH` set. `ad-engine` is unaffected either way — 89 passed
> with and without.

With the ledger connected, every table in `campaign` has a writer:

| Table | Written by | Function |
|---|---|---|
| `companies` | C | `upsert_company` |
| `contacts` | C | `upsert_contact` |
| `touches` | C | `log_touch`, `record_reply` |
| `leads` | F (WF-C1) | `insert_lead` |
| `content` | D | `upsert_content` |
| `content_stats` | D | `snapshot_content_stats` |
| `ad_stats` | E | `snapshot_ad_stats` |
| `meetings`, `pilots` | F (WF-C5) | via PostgREST |

### 4.4 Import the six workflows into n8n

Follow `campaign-n8n/README.md`, which gives the activation order and the reasoning. Summary:

1. **WF-C1** qualifier intake — activate first, it is the lead path
2. **WF-C2** under-10 nurture — safe to activate; it sends nothing without an opt-in
3. **WF-C6** Friday brief — needs `campaign-ledger` and `ad-engine` checked out on the n8n host
4. **WF-C3** reel publishing — start with `publisher: 'buffer'`
5. **WF-C4** comment-to-DM — needs the Meta comments webhook
6. **WF-C5** Stripe day 14 — activate with a **test** key and watch one full run first

Then create the seven credentials named in `campaign-n8n/CREDENTIALS.md`. The exports reference
them **by name only** and carry no values, so the names must match exactly.

Before activating WF-C1, check no existing workflow already binds a `campaign/…` webhook path —
batch F could not verify this without access to your instance (`BLOCKED.md` F-2, two minutes).

### 4.5 Wire up campaign-site

Copy WF-C1's **production** webhook URL out of n8n, then set five variables in the Vercel project
(Production **and** Preview). They are documented individually in `campaign-site/.env.example`:

```
VITE_LEAD_WEBHOOK_URL     from WF-C1's webhook node
VITE_BOOKING_URL          Google Calendar appointment schedule share link
VITE_POSTHOG_KEY          posthog.com, EU cloud, project API key (starts phc_)
VITE_POSTHOG_HOST         https://eu.i.posthog.com  (already defaulted)
VITE_META_PIXEL_ID        Meta Events Manager, 15-16 digits
```

Every one of these degrades safely when empty — the page never breaks — but with
`VITE_LEAD_WEBHOOK_URL` unset in production, leads land in a localStorage recovery queue instead
of the ledger. Set it before spending an ad euro.

Then drop in the two assets the page has slots for: `public/demo.mp4` (plus
`public/demo-poster.jpg`) and `public/logo.png`, and fill the `company` block in each of
`src/content/{en,da,lt}.ts` with the registered company name, number, address and privacy URL.

### 4.6 Still needing a human, not a machine

- **A native Danish and Lithuanian read** of `campaign-site/src/content/{da,lt}.ts`. Both files are
  headed `NEEDS NATIVE CHECK`. This matters more than usual: the campaign runs paid Meta traffic
  into an EU audience and Denmark's marketing rules are stricter.
- **The Danish marketing-law position.** Danish cold email is banned campaign-wide until you
  confirm it. WF-C2 requires `dk_marketing_law_confirmed: true` set by hand in its Config, *and*
  the same flag on the lead. Neither alone is enough.
- **The 9x ROI figure.** See `ops/DECISIONS.md` — the arithmetic does not support it at the
  current price, and it is live copy in three languages.

---

## 5. Where the campaign-wide documents live

There is no `campaign-specs/` repository — the spec the code cites was never in any repo and is
not on any machine we can see. What exists lives here, in `campaign-n8n/ops/`:

| File | What it is |
|---|---|
| `ops/STATUS.md` | Full audit of all six batches, corrected 2026-09-08 |
| `ops/NEW-PC-SETUP.md` | This file |
| `ops/DECISIONS.md` | Calls made autonomously, with reasoning, and how to reverse each |
| `ops/NIGHT-RUN.md` | The overnight task plan and its live status |
| `ops/HANDOFF.md` | What happened overnight and what to pick up |

They are in `campaign-n8n` because it is the integration repo — it already carries campaign-wide
material (`CREDENTIALS.md`, and a proposed migration for `campaign-ledger`). If you would rather
they lived somewhere else, they are plain markdown and move cleanly.
