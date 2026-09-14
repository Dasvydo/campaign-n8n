# The first lead that ever travelled the chain

**2026-09-14, 10:09:12Z. WF-C1 execution 564522. Status: success.**

Until this ran, WF-C1 had been ACTIVE on the instance with **zero executions**
since import. Every green test in this repo was green on a chain that had never
carried anything, and `campaign.leads` had never held a row. That is no longer
true.

## What was sent

One POST to `https://viniflow-u57383.vm.elestio.app/webhook/campaign/qualifier`,
shaped per `campaign-site/src/lib/contract.ts`:

```
company_name  SMOKE TEST - delete me
work_email    smoketest@doviloop.dev
team_size     10-24          email_client  outlook
submitted_at  2026-09-14T10:09:12Z
```

`10-24` + `outlook` routes to `qualified`. That path was chosen deliberately: it
skips the nurture branch and **every file-append node**, so the missing
`/home/node/.n8n/campaign` directory could not silently eat anything and
confuse the result.

## What came back

```json
{"ok":true,"outcome":"qualified","stage":"qualified",
 "lead_id":"398c1383-77c8-44fb-ab27-e529e5c6fecb",
 "deduped":false,"shows_booking":true,"nurture_started":false,"stored":true}
```

The response body was not taken as proof. The execution was read back over the
API and every node checked individually. All twelve succeeded:

    Webhook — qualifier -> Config -> Validate and route -> IF payload valid
    -> Guard: ledger target -> Ledger: upsert lead -> Read ledger result
    -> Respond: routing outcome -> IF ledger stored -> IF too small
    -> Email Dovy: new lead -> Send: new lead

Three things worth naming, from the execution data rather than from the summary:

- **The row is in the right database.** `Ledger: upsert lead` returned the
  inserted row from `yheilbuunzdugfnermfb`, the ledger project. Not the product
  database. The `Guard: ledger target` node ran and passed rather than throwing.
- **The dedupe key matches Batch B byte-for-byte.**
  `smoketest@doviloop.dev|2026-09-14T10:09:12Z` - `submitted_at` passed through
  verbatim, exactly as `campaign_db.insert_lead` computes it. A normalised
  timestamp here would have produced a different key and broken dedupe against
  anything B writes.
- **The mail actually left.** Gmail returned `250 2.0.0 OK`, accepted for
  `hello@doviloop.dev`, from `dovyvini@doviloop.dev`. Nothing was sent to the
  lead address; the only `emailSend` on this path goes to Dovy.

## Cleaning up — DONE, 2026-09-14 10:58Z

The row is gone. `campaign.leads` is empty again.

Deleting it was harder than it should have been, and the reason is worth
writing down: **there is no ledger credential outside n8n.** The container
running these sessions exports `SUPABASE_URL` and
`SUPABASE_SERVICE_ROLE_KEY`, and both point at the **product** database -
exactly the collision `campaign-ledger/.env.example` predicts when it
insists the ledger reads `SUPABASE_SERVICE_KEY` instead. The ledger's own
key exists only inside the n8n credential, which the public API will not
read back.

So the delete went through n8n, as a temporary workflow that was created,
activated, fired once, and destroyed. Two things bounded it:

- The DELETE was filtered on **both** the row id and
  `work_email=eq.smoketest@doviloop.dev`. A mistyped id could not match a
  real lead, because a real lead does not carry the smoke-test address.
- The URL was a hardcoded literal naming `yheilbuunzdugfnermfb`, asserted
  against the product ref before the workflow was ever posted.

`Prefer: return=representation` made the delete prove itself: the first
call returned the smoke-test row, a second call returned `[]`. Supabase
answered both with header `sb-project-ref: yheilbuunzdugfnermfb`.

The temporary workflow was deactivated and deleted; its webhook now 404s
and the instance is back to the four WF-C workflows.

If you would rather do this by hand next time, it is one statement in the
SQL editor:

```sql
delete from campaign.leads
 where id = '398c1383-77c8-44fb-ab27-e529e5c6fecb';
```

**Worth fixing properly:** routine ledger reads and one-off corrections
currently have no path that does not involve building a workflow. A
service-role key for `yheilbuunzdugfnermfb` in the session environment,
under the name `SUPABASE_SERVICE_KEY` that `campaign_db.py` already
expects, would remove the need for this dance entirely.

## What this does NOT prove

- The `too_small` branch, the nurture enrolment, and every JSONL append are
  still unexercised. They are the paths that need
  `/home/node/.n8n/campaign` to exist, and it still does not.
- WF-C2 through WF-C6 have never executed.
- Dedupe was not tested: `deduped:false` on a first insert says only that this
  key was new. Sending the same payload twice would test it, and would not cost
  a second row.
