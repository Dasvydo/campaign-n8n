# AUDIT — Batch F, `campaign-n8n`

Phase 0. Written before any other file in this repo was changed.
Date of run: 2026-09-03. Branch: `campaign/f-n8n`.

Every finding below is backed by a command that was actually run in this
container. Where something is absent, the searches that failed are listed so
the absence is a finding and not a shrug.

---

## 1. The n8n instance — NOT CONTACTED

`viniflow-u57383.vm.elestio.app` was never contacted. No HTTP request, no DNS
lookup, no API call was made against it by this batch. The spec forbids it and
there is nothing in this container that would have authenticated anyway.

Everything in `workflows/` is written as export JSON and validated locally.

## 2. The `n8n-workflow-builder` skill — DEFINITIVELY ABSENT

Commands run:

```
find / -type d -name "*workflow-builder*" -not -path "/proc/*" -not -path "/sys/*"
      -> no output
grep -rl "n8n" /root/.claude/skills /root/.claude/plugins
      -> exactly one hit, and it is not the skill:
         /root/.claude/skills/synced/.../batch-orchestrator/references/hard-stops.md
find / -iname "*n8n*" -not -path "/proc/*" -not -path "/sys/*"
      -> only /home/user/campaign-n8n, its .git refs, the spec file
         /home/user/campaign-specs/F-n8n-flows.md, and the uploaded copy of
         that same spec under /root/.claude/uploads/
ls -R /root/.claude/skills
      -> session-start-hook, plus 20 synced skills, none of them n8n-related
```

**Finding: the skill does not exist in this container.** Not under a different
name, not vendored, not in a plugin directory.

**What it blocks:** I cannot follow its naming, node-id, tagging or
error-handling conventions, because I cannot read them. The conventions used in
this repo are my own, stated in `README.md` under "Conventions used, and why",
so that when Dovy diffs these against a workflow the skill produced he can see
exactly where they differ instead of guessing. Logged as F-1 in `BLOCKED.md`.

## 3. The existing workflow set (WF1, WF4, WF5, WF6, WF9) — ABSENT AT AUDIT TIME, FOUND LATER

> **Correction, 2026-09-08.** The conclusion below was right about this container
> as it stood, and wrong as a general claim. The exports were on the filesystem
> the whole time, in the product repo at
> `flow-savvy-automations/infra/n8n/sanitized/` (17 files, named by n8n workflow
> id). The searches missed them because they looked for `WF1*`-style filenames
> and for a directory named `doviloop*`. Consequence: the webhook-path collision
> question in `BLOCKED.md` F-2 is now answered — no collision. The reasoning that
> followed from the absence (`WF-C<n>` naming, no top-level `id`) was sound and
> is unaffected.

Commands run:

```
grep -rl "n8n-nodes-base" / --include=*.json --exclude-dir=proc --exclude-dir=sys
        --exclude-dir=node_modules
      -> no output. There is not a single n8n workflow export on this filesystem.
grep -rl "Ju1nxQJw6R4mygdt" / --exclude-dir=proc --exclude-dir=sys
      -> 5 hits, every one of them a copy of the spec asking the question or a
         transcript of this session asking it:
           /home/user/campaign-specs/F-n8n-flows.md          (the spec)
           /root/.claude/uploads/.../932e1399-Fn8nflows.md   (the same spec)
           /root/.claude/projects/.../<session>.jsonl        (this transcript)
           /root/.claude/projects/.../subagents/<id>.jsonl   (this transcript)
           /tmp/.../b9uf5rgd8.output                         (this search's own log)
         Zero hits in any workflow file, because there are none.
find / \( -iname "WF1*" -o -iname "WF4*" -o -iname "WF5*" -o -iname "WF6*"
          -o -iname "WF9*" \) -not -path "/proc/*" -not -path "/sys/*"
      -> no output
```

**Finding: no copy of WF1, WF4, WF5, WF6 or WF9 is present.** I did not
reconstruct one from the spec's one-line descriptions, and there is no invented
local stand-in for them anywhere in this repo. A guessed copy of a workflow you
cannot see is worse than no copy, because it reads as evidence.

**What it blocks, precisely:**

- I cannot verify that the new workflows do not collide with the existing set.
  I can only pick a scheme that structurally cannot collide (below).
- I cannot read WF4 to confirm the one-email-per-cycle limitation, its cause,
  or whether it has since been fixed. See section 5.
- I cannot check whether an existing workflow already binds a webhook path I
  have chosen. Mitigation: every webhook path in this repo is namespaced under
  `campaign/`, listed in `README.md`, and Dovy should scan the existing five
  for that prefix before activating. Logged as F-2 in `BLOCKED.md`.

### Numbering scheme chosen, and why it cannot collide

Two independent guarantees:

1. **Names.** Every workflow is named `WF-C<n> — <purpose>`. The existing set is
   named `WF<n>` with no separator. `WF-C1` cannot be read as `WF1` by a human
   or by a string match, and the `C` marks it as campaign-scoped. The digits
   1..6 are reused deliberately: they are namespaced by the `-C`, so `WF-C4`
   and `WF4` are unrelated and obviously so.
2. **IDs.** No exported file carries a top-level `"id"`. n8n mints a fresh ID on
   import, so no export in this repo can overwrite an existing workflow even if
   someone imports it twice or imports it into the wrong instance. This is the
   guarantee that actually matters: a name clash is cosmetic, an ID clash
   overwrites a live workflow.

Node IDs inside each file are UUIDs generated for this repo and are unique
across all six files (asserted by the validator, `tools/validate.mjs`).

## 4. Never modify an existing workflow

Nothing in this repo edits, patches, references-by-ID or imports over WF1, WF4,
WF5, WF6 or WF9. The six new files are additive. No `Execute Workflow` node in
this repo targets any workflow outside this repo.

## 5. The known WF4 limitation (one email per cycle) — CANNOT BE VERIFIED HERE

WF4 is not present (section 3), so the limitation is taken on the spec's word
and treated as true. It is recorded here so nothing new is built on an
assumption it can scale.

**Consequence for this batch, which is a real design constraint and not a
formality:** none of WF-C1..WF-C6 routes work through WF4, chains off it, or
assumes any per-email throughput from it.

- WF-C1 sends its own lead notification through its own SMTP node, one email per
  lead, on the webhook execution. It does not queue into a classifier.
- WF-C2 sends its three nurture emails through its own SMTP node, on its own
  wait timers, one at a time.
- WF-C5 and WF-C6 each send exactly one email per run to one recipient.

If WF4 really can only move one email per cycle, nothing here is affected,
because nothing here is downstream of it. Logged as F-3 in `BLOCKED.md` since
the limitation itself is unverifiable from inside this container.

## 6. Sibling repos — READ ONLY, and what was actually read

No file outside `/home/user/campaign-n8n` was written, moved or deleted by this
batch. `git status` in each sibling repo is unchanged by anything I did.

Read, and reconciled against in `RUN-REPORT.md`:

| Repo | Files read | Why |
|---|---|---|
| `campaign-ledger` (B) | `migrations/001_schema.sql`, `002_rls.sql`, `003_views.sql`, `src/campaign_db.py`, `src/friday_brief.py` | real column names, real enum labels, real constraints, real function signatures, the brief's CLI |
| `campaign-site` (A) | `src/lib/contract.ts`, `src/lib/lead.ts`, `src/lib/env.ts`, `src/components/Qualifier.tsx`, `src/content/en.ts`, `scripts/mock-webhook.mjs`, `.env.example` | what the browser really sends, the dedupe header, the too_small opt-in, the strict payload validator A already wrote |
| `ad-engine` (E) | `report/pull_ad_stats.py`, `claims/evidence.json` | WF-C6's trigger and its CLI flags; the ROI claim status |
| `reel-engine` (D) | `engine/ledger.py`, `engine/publish.py`, `engine/approval.py` | what really lands in `campaign.content`, and D's researched Buffer GraphQL contract |
| `outreach-engine` (C) | `engine/ledger.py`, `sequences/` | what really writes `campaign.touches` |

## 7. The database — NOT CONNECTED, and cannot be

Confirmed for the fourth time in this campaign: the only Supabase credential
reachable from this container points at `kngcxwcybozgqgnoweyt`, the forbidden
product project.

No workflow in this repo contains that project ref. Every workflow that talks to
the ledger reads its base URL from a `Config` Set node that ships **blank**, and
every one of them runs a `Guard` Code node that hard-fails the execution if the
configured URL contains the forbidden ref. That mirrors the same refusal B built
into `campaign_db.py` (`_FORBIDDEN_PROJECT_REF`), so the two layers agree.

No connection to any database was opened by this batch.

## 8. Credentials — none exist in this session

No Buffer, Meta, YouTube, LinkedIn, Stripe, SMTP or Supabase credential exists
here. Every credential-consuming node references a credential **by name only**,
with no `id` and no value. `CREDENTIALS.md` lists all of them and where each one
comes from. The validator asserts that no file contains a value that looks like
a key, token, JWT or password.

## 9. Tooling actually available

```
node --version   -> v22.22.2      (used for the validator and the node-code harness)
python3          -> 3.11.15       (Batch B's brief and Batch E's ad pull both run on it)
git identity     -> Dovy (via Claude Code) <dvinickis@gmail.com>
branch           -> campaign/f-n8n, one commit, placeholder README
```

There is no n8n binary and no `n8n` npm package in this container, so
"import-valid" cannot mean "n8n accepted it". It means: valid JSON, and
structurally conformant to the shape n8n's importer requires, checked by
`tools/validate.mjs`, which is written against that shape and run in CI-style
over all six files. What it checks and what it cannot check is stated in
`README.md` and in `RUN-REPORT.md`.
