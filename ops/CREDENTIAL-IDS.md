# Credential ids, and why importing by name is unsafe

`tools/import_workflow.py` needs `ops/credential-ids.local.json`. That file is
gitignored and must stay that way: **this repo is public**, and credential ids
are instance-specific.

Create it by hand, keyed by the exact credential **name** the exports carry:

```json
{
  "Campaign Ledger (Supabase, campaign schema)": "<id>",
  "DoviLoop campaign SMTP":                      "<id>",
  "Campaign approval webhook token":             "<id>",
  "Meta Graph API page token":                   "<id>"
}
```

## Why by id

The exports carry credential **names only**, on purpose. n8n's public API
**ignores names and honours ids**. An import that sends a name alone does not
fail and does not warn - the instance picks a credential for you. On
2026-09-11 it picked the product database for 31 of 31 nodes, every ledger node
included.

So the importer binds by id, and for any name with no id it **drops the slot
entirely**. An unbound node fails loudly the first time it runs. A node bound
to a stranger's credential posts to a stranger's account and says nothing. The
first is a bug; the second is an incident.

## Getting an id, and checking one

`GET /credentials` returns **405** - credentials cannot be listed over the API.
Ids come from the n8n UI URL: `/home/credentials/<id>`. Note that
`/projects/<id>/credentials` shows a **project** id, which is not a credential
id and has been pasted in by mistake before.

To check an id without importing anything, POST a throwaway workflow with a
node referencing `{id, name: 'SENTINEL'}` and read it back: n8n **rewrites the
name to whatever the id resolved to**, so a name that comes back as `SENTINEL`
means the id does not exist. Delete the probe afterwards.

## Verification is not optional

`import_workflow.py` reads every node back after the POST and diffs **both id
and name** against what it sent, refuses any product-database reference outside
the `Guard: ledger target` node, and refuses a workflow that has no guard node
at all. It exits non-zero rather than reporting a half-bound import.
