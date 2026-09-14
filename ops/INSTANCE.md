# What is actually on the n8n instance

Instance: `https://viniflow-u57383.vm.elestio.app`. Last reconciled **2026-09-14**.

All six workflows are imported. Workflow ids are instance-specific; they are not
secret, unlike the credential ids, which stay out of git (`ops/CREDENTIAL-IDS.md`).

| | id | active | executions |
|---|---|---|---|
| WF-C1 Qualifier intake | `iaNNhNu7OA4aHCKv` | **yes** | 1, success |
| WF-C2 Under-10 nurture | `kOby8XpvzVW5HOGG` | no | 0 |
| WF-C3 Publish approved reels | `LIw7T5Ch7OQ7khzJ` | no | 0 |
| WF-C4 Comment keyword to DM | `VAgGkEsMrWzUtl5T` | no | 0 |
| WF-C5 Pilot day 14 | `jQphbCjQAQFs4TiR` | no | 0 |
| WF-C6 Friday brief | `q1ntjCUP1lnKv9hY` | no | 0 |

Every credential slot was bound by id and verified by reading the node back and
diffing id **and** name. Where no credential exists the slot was **dropped**
rather than sent as a bare name - see `ops/CREDENTIAL-IDS.md` for why that
distinction is the whole ballgame.

## What blocks each one from being switched on

**C1 — nothing. It works.** Proven end to end on 2026-09-14: webhook to
`campaign.leads` to Dovy's inbox. See `ops/SMOKE-TEST.md`.

**C2 — consent.** It may not email anyone until there is a durable record of
opt-in. That means migration 004 (`campaign-ledger/migrations/004_consent.sql`,
not applied) and the 1-9 opt-in becoming a real POST instead of a `mailto:`.

**C3 — the data directory.** `/home/node/.n8n/campaign` does not exist on the
host. `Append content-approvals.jsonl` is `onError: continueRegularOutput`, so
an approval would report success and vanish. Fix that before activating:

```
docker exec -u root <n8n> sh -c 'mkdir -p /home/node/.n8n/campaign && chown node:node /home/node/.n8n/campaign'
```

`publisher` is `direct` because no Buffer credential exists. Buffer, YouTube and
LinkedIn nodes are unbound and will fail if reached. `ig_user_id` is empty on
purpose - there is no Instagram account - so the Instagram branch cannot run.

**C4 — a Meta webhook subscription.** `campaign/meta-comments` has to be
registered in the Meta app; it stays unauthenticated by design, verified by
Meta's own challenge handshake (`ops/DECISIONS.md`). `fb_page_id` is set;
`ig_user_id` is empty, same reason as C3.

**C5 — Stripe, twice over.** There is no `Stripe secret key (campaign)`
credential, so `Stripe: create checkout session` and `Stripe: re-fetch the
event` are unbound and have **no `onError`** - they hard-fail if reached. Even
with a key, `price_seat_monthly` and `price_setup_once` are empty and
`usd_eur_rate` is null, so no valid checkout session could be built. Needs a
credential and three config values, not one.

**C6 — YouTube, and two paths on the host.** No `YouTube Data API (campaign)`
credential, so `YouTube: video statistics` is unbound with no `onError`. That is
harmless while nothing has published and a landmine the first time a reel does:
the brief fails at the stats step rather than sending without stats. The two
`executeCommand` nodes also shell out on the **n8n host**, to
`/opt/campaign/campaign-ledger/src/friday_brief.py` and
`/opt/campaign/ad-engine/report/pull_ad_stats.py`. Neither repo is known to be
checked out there. `campaign.content_stats` does exist (001, applied), so the
ledger side of C6 is fine.

## Reconciling this file

```
python3 tools/import_workflow.py workflows/WF-CX.json          # dry run
python3 tools/import_workflow.py workflows/WF-CX.json --apply  # import + verify
```

The importer only ever creates. Updating an existing workflow is a `PUT` to
`/workflows/<id>` carrying `name`, `nodes`, `connections`, `settings` - and on
an **active** workflow, snapshot it first and check `active` survived, because
a PUT re-registers the webhook.
