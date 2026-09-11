# CREDENTIALS

Eight credentials. **None of their values exist in this repo**, in any exported
JSON, or anywhere in this container. Every node references a credential by NAME
only; n8n matches it to whatever you create with that name at import time.

Create them in n8n under **Credentials → Add credential**, using the exact names
in the "Name in n8n" column. **Create them BEFORE importing the workflows.**

> ### THE PUBLIC API IGNORES CREDENTIAL NAMES. Bind by id.
>
> This box has been wrong twice, and the second version was wrong in a way that
> produced a procedure which cannot work. Both corrections are kept, because the
> shape of the mistake matters more than the conclusion.
>
> **Version 1 said** a name that does not match shows a red "credential not
> found" badge and nothing breaks. False.
>
> **Version 2 said** the 2026-09-11 incident - `POST /api/v1/workflows` with none
> of these credentials created, and all **31 credential-bearing nodes** silently
> bound to whatever existing credential of the matching type n8n found, every
> ledger node onto `Supabase DoviLoop (pgvector)`, **the product database** -
> happened *because the credentials did not exist yet*, and that creating them
> first with exact names would fix it. **Also false, measured the same day.**
>
> Four workflows were posted, each naming a different credential, and every one
> came back bound to the same wrong credential:
>
> ```
> asked for  dsd-supabase-service-role                   -> Supabase DoviLoop (pgvector)
> asked for  Supabase account                            -> Supabase DoviLoop (pgvector)
> asked for  Campaign Ledger (Supabase, campaign schema) -> Supabase DoviLoop (pgvector)
> asked for  TOTAL GARBAGE THAT CANNOT EXIST             -> Supabase DoviLoop (pgvector)
> ```
>
> The first two **exist on the instance**. The name is not consulted at all. So
> creating the credentials first changes nothing about an API import, and the
> incident would have happened either way.
>
> **What the API does honour is `id`:**
>
> ```
> sent {id: 9siuWUnT9BvuJFK6, name: "deliberately the wrong name"}
> got  {id: 9siuWUnT9BvuJFK6, name: "dsd-supabase-service-role"}
> ```
>
> It resolves the id and **rewrites the name to match**. That also gives a free
> existence check: send a sentinel name with an id, and if the name comes back
> unchanged the id does not exist. A garbage id behaves identically to one that
> is merely wrong, which is how `i3saeYflwqETYMaV` - a *project* id pasted from
> `/projects/<id>/credentials` - was caught before it reached an import.
>
> **So the procedure is:**
>
> 1. Create the credentials in the UI, named as below. The names are for humans
>    and for a UI import; the API will not read them.
> 2. Collect each credential's **id** from its URL: `.../credentials/<id>`.
> 3. Inject `{id, name}` into every `credentials` block at import time. Ids are
>    instance-specific and are deliberately NOT committed to this repo.
> 4. **Verify by reading every node back** and diffing both the id and the name
>    against the committed export. Not by glancing at the canvas.
>
> A UI import (Workflows -> Import from File) does resolve by name, which is why
> the names still matter. The API does not.

> ### Imported 2026-09-11
>
> WF-C1 (`iaNNhNu7OA4aHCKv`) and WF-C2 (`kOby8XpvzVW5HOGG`), both inactive,
> 8 of 8 credential-bearing nodes verified bound by id. Instance went 125 -> 127
> with the active count unchanged at 21.
>
> **WF-C6 was deliberately held back.** Its `YouTube: video statistics` and
> `Meta: post insights` nodes have no credential yet and **no `onError`**, so
> they would either hard-fail or bind to a stranger's token. The no-stats branch
> that `README.md` promises is real but is keyed on *whether there is published
> content*, not on whether credentials exist - so C6 is harmless today and a
> landmine the first time a reel publishes. Import it once credentials 4 and 5
> exist.

`tools/validate.mjs` asserts, on every run, that no file contains anything but
`{ name }` under a `credentials` key, and separately scans every string in every
file for JWTs, Stripe keys, Meta tokens, Google API keys and private key blocks.

---

## Summary

| # | Name in n8n | n8n credential type | Used by | Needed before |
|---|---|---|---|---|
| 1 | `Campaign Ledger (Supabase, campaign schema)` | Supabase API | C1, C3, C4, C5, C6 | anything at all |
| 2 | `DoviLoop campaign SMTP` | SMTP | C1, C2, C3, C4, C5, C6 | anything at all |
| 3 | `Buffer API token` | Header Auth | C3 | first reel publish |
| 4 | `Meta Graph API page token` | Header Auth | C3, C4, C6 | IG/FB publish, comment DMs, stats |
| 5 | `YouTube Data API (campaign)` | YouTube OAuth2 API | C3, C6 | YouTube Shorts publish and stats |
| 6 | `LinkedIn (campaign posting)` | LinkedIn OAuth2 API | C3 | LinkedIn publish on the direct path |
| 7 | `Stripe secret key (campaign)` | Header Auth | C5 | first pilot reaching day 14 |
| 8 | `Campaign approval webhook token` | Header Auth | C3 | **activating C3 at all** |

### 8. `Campaign approval webhook token` - Header Auth

Added 2026-09-10 as the minimum half of decision **P-4**. It guards
`campaign/content-approve`, the POST that makes a reel publishable - the gate
this repo's own README calls the one that matters most, because it is what
publishes in public. Until now it had no authentication, and this repository is
the campaign's public face: it prints the n8n hostname and every webhook path,
so the gate rested on the path being hard to guess. It was not.

**Create it as:** Header Auth, name `Campaign approval webhook token`, header
name `X-Campaign-Approve`, value a long random string you generate. Nothing
needs to know the value except you and n8n.

**Then approve a reel with:**

```
curl -X POST https://<your-n8n>/webhook/campaign/content-approve \
  -H 'X-Campaign-Approve: <the value>' \
  -H 'Content-Type: application/json' \
  -d '{"natural_key":"...","approved_by":"dovy"}'
```

**Why the other approval webhook does NOT get one.**
`campaign/meta-dm-approve` is a link clicked from an email, so it cannot carry a
header - a token in the URL is the only shape that works there. It already had
one, but the token was `base64url(rateKey|comment_id|Date.now())`, which is an
encoding rather than a secret: both ids are public on the comment that triggers
the workflow, and it runs seconds after the comment is posted. Anyone who
commented could derive their own approval link. That token is now 64 hex
characters of `crypto.randomUUID()`, and nothing is recoverable from it because
the draft is parked against it in workflow static data. No credential needed.

`campaign/qualifier` also stays open, deliberately: the public landing page
posts to it from a browser, where a secret would not be secret. It needs its
`allowedOrigins` narrowed from `*` to the real site origin instead - still open,
because the campaign site has no deployed domain yet.

Only 1 and 2 are needed to activate C1, C2 and C6. Everything else can wait
until the account it belongs to exists.

---

## 1. `Campaign Ledger (Supabase, campaign schema)`

**Type:** Supabase API (n8n's built-in `supabaseApi`).

Chosen over a plain header credential for one specific reason: Supabase's
gateway wants **both** an `apikey` header and an `Authorization: Bearer` header,
and n8n's Header Auth credential can only inject one header. The Supabase
credential injects both, so the HTTP nodes stay simple and no key is ever typed
into a node parameter.

- **Host / URL:** `https://yheilbuunzdugfnermfb.supabase.co`, the CAMPAIGN
  ledger project. **Confirmed by Dovy on 2026-09-06.** The same URL is
  pre-filled as `ledger_url` in every Config node, and `sql/004_consent.sql`
  targets this project's `campaign` schema.
- **Service Role Secret:** Project Settings → API → `service_role` key.

### Two hard warnings

1. **It must NOT be the product project `kngcxwcybozgqgnoweyt`.** That is the
   Frankfurt product database and every spec in this campaign forbids touching
   it. The only Supabase credential that exists in the build container points at
   it, which is why nothing here was ever tested against a real database.
   Every ledger-touching workflow runs a `Guard: ledger target` node that
   throws if the configured URL contains that ref, mirroring the same refusal
   Batch B built into `campaign_db.py`. Do not remove those nodes.
2. **PostgREST must be told about the schema.** The ledger lives in schema
   `campaign`, not `public`. In the Supabase dashboard go to
   **Settings → API → Exposed schemas** and add `campaign`. Without it every
   request returns `PGRST106 schema must be one of the following`. The HTTP
   nodes already send `Accept-Profile: campaign` and `Content-Profile: campaign`,
   which is the other half of the same requirement.

The service role bypasses RLS by design. Batch B's `002_rls.sql` turns RLS on
with **zero** policies, so `anon` and `authenticated` get nothing and only this
credential can read the table. Treat it as a production secret.

## 2. `DoviLoop campaign SMTP`

**Type:** SMTP. Used by thirteen Send nodes across all six workflows.

**Settled 2026-09-11. The credential exists and its test is green.**

- **Host / Port / SSL:** `smtp.gmail.com`, port **465**, **SSL on**, and an
  **App Password** (Google rejects the account password on SMTP outright).
  `doviloop.dev` is Google Workspace - `MX 1 smtp.google.com`,
  `v=spf1 include:_spf.google.com`, checked in DNS rather than assumed.
- **User:** `dovyvini@doviloop.dev`.

If the test ever reads **"Connection closed"**, that is transport, not
credentials - n8n never got far enough to try the password. Check SSL/TLS is
on (465 needs TLS from the first byte), then try port 587 with SSL/TLS off,
which is STARTTLS. If neither connects the host is blocking outbound SMTP.
A wrong password says "Invalid login" instead.

Two things worth doing before activation:

- **Do not use an Instantly sending domain for this.** Those domains are being
  warmed for cold outreach from around 22 Sept. Mixing transactional campaign
  mail into a warming domain is a good way to lose both.
- **`from_email` is not a free choice - it must equal the SMTP user.** Every
  workflow now sends from `dovyvini@doviloop.dev`, built from one `SENDER_EMAIL`
  constant in `tools/build_workflows.py`. Google Workspace rewrites or rejects
  a From that is neither the authenticated mailbox nor one of its verified
  "Send mail as" aliases, so an unverified address does not fail loudly - the
  mail goes out wearing a different name than the one in the export.

  This collapsed a distinction the build used to make: C2's nurture notes came
  from `dovy@doviloop.dev` because a human wrote them, everything else from
  `campaign-bot@doviloop.dev`. Neither was verified on this mailbox, so both
  were fiction. C2 keeps the intent through `reply_to`, which the sending
  account does not constrain. To restore the split, verify those two addresses
  under **Gmail → Settings → Accounts → Send mail as** and set them back in the
  builder.

## 3. `Buffer API token`

**Type:** Header Auth. Used by one node, `WF-C3 / Buffer: createPost`.

- **Name:** `Authorization`
- **Value:** `Bearer <your Buffer access token>`

From `publish.buffer.com` → Settings → Apps and Extras → Developers, or an
existing access token. **Buffer's API is not on every plan.** If yours does not
expose it, do not fight it: set `publisher: 'direct'` in WF-C3's Config node and
the direct path takes over with no other change. That is what the fallback is for.

You also need the four Buffer channel ids in WF-C3's Config
(`buffer_channels.instagram`, `.facebook`, `.youtube_shorts`, `.linkedin`).
They are in the URL when you open a channel in Buffer.

## 4. `Meta Graph API page token`

**Type:** Header Auth. Used by five nodes across WF-C3, WF-C4 and WF-C6.

- **Name:** `Authorization`
- **Value:** `Bearer <page access token>`

From Meta Business Suite → Business Settings → Users → System Users → Generate
token, against the Page and the connected Instagram account. Get a **long-lived**
token; the default expires in about an hour and every one of these nodes will
start failing quietly on the same day.

Permissions this campaign actually uses:

| Permission | What breaks without it |
|---|---|
| `pages_manage_posts` | WF-C3 cannot post the FB page video |
| `instagram_content_publish` | WF-C3 cannot publish the IG reel |
| `pages_read_engagement`, `read_insights` | WF-C6 gets no content stats |
| `pages_messaging`, `instagram_manage_messages` | WF-C4 cannot send the private reply |
| `pages_manage_metadata` | the comments webhook cannot be subscribed |

Also fill `ig_user_id` and `fb_page_id` in the Config nodes of WF-C3, WF-C4 and
WF-C6. The IG one is the **Instagram Business Account ID**, not the @handle and
not the numeric profile id.

## 5. `YouTube Data API (campaign)`

**Type:** YouTube OAuth2 API.

Google Cloud Console → new project → enable **YouTube Data API v3** → OAuth
consent screen → Credentials → OAuth client ID (Web application). Paste n8n's
OAuth redirect URL into the authorised redirect URIs, then click Connect in n8n
and sign in as the channel owner.

Worth knowing before you rely on it: an unverified Google Cloud project uploads
videos as **private** and cannot make them public. If the Shorts come out
private, that is the cause, and the fix is verifying the project, not the
workflow.

## 6. `LinkedIn (campaign posting)`

**Type:** LinkedIn OAuth2 API. Used by one node on WF-C3's direct path only.
The Buffer path does not need it.

LinkedIn Developer portal → create an app tied to the DoviLoop page → request
**Share on LinkedIn** (`w_member_social`), or **Community Management API** if
you want to post as the company page rather than as yourself. Approval is not
instant.

**Read the LinkedIn limitation in `README.md` before relying on this.** n8n's
LinkedIn node has no native video post, and LinkedIn is the ONLY channel Danish
and Lithuanian reels go to. This is logged as F-11 in `BLOCKED.md`.

## 7. `Stripe secret key (campaign)`

**Type:** Header Auth. Used by two nodes in WF-C5.

- **Name:** `Authorization`
- **Value:** `Bearer sk_live_...` (use `sk_test_...` until you have watched a
  full run)

Stripe dashboard → Developers → API keys.

**Use a restricted key.** WF-C5 needs exactly two permissions and nothing else:

| Resource | Access | Why |
|---|---|---|
| Checkout Sessions | **write** | to create the payment link |
| Events | **read** | to re-fetch and verify the webhook event |

Everything else can be `none`. A restricted key with those two permissions
cannot refund, cannot charge a saved card, and cannot read your customer list,
which turns "this workflow must never charge anyone" from a promise in a comment
into something the key itself enforces.

You also need two Price ids in WF-C5's Config: `price_seat_monthly` (89 USD per
seat, recurring monthly) and `price_setup_once` (500 USD, one-off).

### Note on the Stripe webhook signing secret

There isn't one, deliberately. Stripe's usual advice is to verify the
`stripe-signature` header with the endpoint's signing secret, which would mean
putting a secret into an exported workflow. WF-C5 does the other accepted thing:
it takes **only the event id** out of the incoming body, throws the rest away,
and re-fetches that event from Stripe over the authenticated API. A forged post
either names an id that does not exist or names a real one whose real contents
are then used. Nothing an attacker writes reaches the ledger, and there is no
signing secret to leak.

When you add the endpoint in Stripe (Developers → Webhooks → the
`campaign/stripe` production URL), subscribe it to
`checkout.session.completed` and `invoice.paid`. Copy the signing secret
somewhere safe if you like, but this workflow does not want it.

---

## What is NOT here, and why

- **No Instantly credential.** Batch C owns Instantly and it is not wired into
  any n8n workflow. Nothing in this repo can put a Danish address into a cold
  email sequence, which is the way it should stay.
- **No Higgsfield or HyperFrames credential.** Batch D renders locally.
- **No PostHog credential.** Batch A's page talks to PostHog from the browser.
- **No product database credential.** By design, and enforced by a guard node.
