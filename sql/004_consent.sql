-- =====================================================================
-- PROPOSED migration 004 — consent, content approval, social touches
--
-- STATUS: NOT RUN. NOT APPLIED. This file lives in campaign-n8n, not in
-- campaign-ledger, on purpose:
--
--   * the global rules say Batch B writes SQL files and Dovy runs them, and
--     that no batch applies a migration;
--   * Batch F may not write to a sibling repo at all.
--
-- So this is a proposal with the reasoning attached, for Dovy to read, decide
-- on, and (if he agrees) move into campaign-ledger/migrations/ as 004 before
-- running it there with 001 to 003.
--
-- TARGET PROJECT: the campaign ledger project oqpeebtwtikdzorgouxd, schema
-- `campaign`. Confirmed by Dovy on 2026-09-06. NEVER the product project
-- (kngcxwcybozgqgnoweyt).
--
-- Every statement is guarded so the file is re-runnable.
--
-- WHY THIS EXISTS
-- ---------------
-- Three of Batch F's six workflows had to route around a column that does not
-- exist. Each workaround works, and each one keeps state in n8n that ought to
-- be in the ledger where the Friday brief can see it. n8n workflow static data
-- does not survive an instance rebuild, and it is invisible to every other
-- batch. These four changes move that state where it belongs.
-- =====================================================================


-- ---------------------------------------------------------------------
-- 1. CONSENT on campaign.leads.        Blocks: WF-C2. Priority: HIGH.
--
-- The shared qualifier contract has eleven fields and no consent field, yet the
-- routing table enrols a `too_small` lead into a three-email nurture. Batch A
-- refused to auto-enrol and made the 1-9 screen an explicit opt-in. Batch B
-- flagged the same gap ("no consent/capture-context field on a schema holding
-- EU personal data"). Batch F refuses to send without proof of opt-in.
--
-- Right now that proof is passed into WF-C2 by hand and the opt-out list lives
-- in n8n static data plus a JSONL file. Neither is durable and neither is
-- visible to the ledger. These columns fix that.
--
-- Denmark is the reason this is HIGH and not MEDIUM: Danish marketing law is
-- the stated cause of the campaign-wide ban on Danish cold email, and a
-- consent record you cannot produce on request is the same as no consent.
-- ---------------------------------------------------------------------

alter table campaign.leads
  add column if not exists consent_granted_at timestamptz,
  add column if not exists consent_source     text,
  add column if not exists consent_evidence   text,
  add column if not exists opt_out_at         timestamptz,
  add column if not exists capture_context    text;

-- A consent record with no source and no evidence is not a consent record.
do $$ begin
  alter table campaign.leads add constraint leads_consent_is_evidenced check (
    consent_granted_at is null
    or (coalesce(consent_source, '') <> '' and coalesce(consent_evidence, '') <> '')
  );
exception when duplicate_object then null; end $$;

create index if not exists leads_opt_out_at_idx on campaign.leads (opt_out_at);

comment on column campaign.leads.consent_granted_at is
  'When this person actively asked to be emailed. NULL means no marketing email may be sent to them, whatever stage they are at.';
comment on column campaign.leads.consent_source is
  'HOW they opted in, in words. e.g. "pressed Send me the three emails on teams.doviloop.dev, then replied to the mailto".';
comment on column campaign.leads.consent_evidence is
  'WHERE the proof is, so a human can find it again. A message id, a thread link, a screenshot path.';
comment on column campaign.leads.opt_out_at is
  'Set by WF-C2s unsubscribe webhook. Checked before EVERY send, not just the first.';
comment on column campaign.leads.capture_context is
  'What the page said above the button they pressed. The thing you would have to produce if a regulator asked what they agreed to.';


-- ---------------------------------------------------------------------
-- 2. APPROVAL on campaign.content.     Blocks: WF-C3. Priority: HIGH.
--
-- The spec for WF-C3 says: read campaign.content "where published_at is null
-- AND an approval flag is set". There is no approval flag. campaign.content is
-- exactly id, kind, lane, language, hook, script_path, asset_path, platforms,
-- published_at, buffer_id, natural_key, created_at. Batch D asserts the same
-- list in its own tests.
--
-- The alternative reading, "published_at is null and asset_path is set", would
-- publish every rendered reel automatically, and this is the one workflow in
-- the campaign that posts in public. So WF-C3 keeps its own approval list in
-- n8n static data and fails closed without it.
--
-- That works, but the approval decision is invisible to the ledger and dies
-- with the n8n instance. One column fixes it.
-- ---------------------------------------------------------------------

alter table campaign.content
  add column if not exists approved_at timestamptz,
  add column if not exists approved_by text;

do $$ begin
  alter table campaign.content add constraint content_publish_needs_approval check (
    published_at is null or approved_at is not null
  );
exception when duplicate_object then null; end $$;

create index if not exists content_approved_at_idx on campaign.content (approved_at);

comment on column campaign.content.approved_at is
  'Set by a human. WF-C3 publishes nothing without it. The CHECK makes it impossible to record a publish that was never approved.';

-- After running this, WF-C3 can drop its static-data list and change
-- "Ledger: read unpublished content" to:
--   /rest/v1/content?published_at=is.null&approved_at=not.is.null&select=*


-- ---------------------------------------------------------------------
-- 3. SOCIAL TOUCHES.                   Blocks: WF-C4. Priority: MEDIUM.
--
-- WF-C4 sends a DM to somebody who commented a keyword, and the spec says "log
-- a touch". It cannot go in campaign.touches, for two independent reasons:
--
--   a. touches.contact_id is NOT NULL -> contacts.company_id is NOT NULL ->
--      companies.domain is NOT NULL with a CHECK on its shape. An Instagram
--      commenter is an anonymous handle. Logging one touch would mean inventing
--      a company and a contact for a person whose firm, name and email are all
--      unknown, into the same tables the ICP finder and the Friday brief count.
--
--   b. touch_channel is ('linkedin_connect','linkedin_dm','email','phone').
--      There is no instagram_dm and no facebook_dm, and Batch B's comment on
--      the type says the taxonomy is shared with the outreach engine and must
--      not be extended without checking that repo's classifier first.
--
-- Two ways out. This file proposes the SECOND, and leaves the first commented.
--
-- Option A, rejected: add the two values to campaign.touch_channel. One line,
-- but it changes an enum the outreach engine reads, and (a) is unsolved anyway,
-- so a social DM still has no contact row to hang off.
--
--   alter type campaign.touch_channel add value if not exists 'instagram_dm';
--   alter type campaign.touch_channel add value if not exists 'facebook_dm';
--
-- Option B, proposed: a separate table for anonymous platform touches, which
-- has no contact requirement because there is genuinely no contact.
-- ---------------------------------------------------------------------

do $$ begin
  create type campaign.social_channel as enum ('instagram_dm', 'facebook_dm');
exception when duplicate_object then null; end $$;

create table if not exists campaign.social_touches (
  id                 uuid primary key default gen_random_uuid(),
  channel            campaign.social_channel not null,
  platform_user_id   text not null,
  platform_user_name text,
  comment_id         text,
  content_id         uuid references campaign.content (id) on delete set null,
  landing_url        text,
  utm_source         text,
  utm_medium         text,
  utm_campaign       text,
  utm_content        text,
  approved_by        text not null,
  sent_at            timestamptz not null default now(),
  message_id         text,
  -- One DM per person per channel, ever. The rate limit WF-C4 keeps in n8n
  -- static data, made durable and made a database fact.
  constraint social_touches_one_per_person unique (channel, platform_user_id)
);

create index if not exists social_touches_content_id_idx on campaign.social_touches (content_id);
create index if not exists social_touches_sent_at_idx    on campaign.social_touches (sent_at);

comment on table campaign.social_touches is
  'DMs sent in reply to a public comment. Separate from campaign.touches because the recipient is an anonymous platform handle with no contact or company row, and inventing one would corrupt the ICP counts.';
comment on column campaign.social_touches.approved_by is
  'NOT NULL on purpose. No row can exist for a DM nobody approved.';

alter table campaign.social_touches enable row level security;
revoke all on campaign.social_touches from anon, authenticated;
grant select, insert, update on campaign.social_touches to service_role;


-- ---------------------------------------------------------------------
-- 4. CURRENCY on campaign.pilots.      Blocks: WF-C5. Priority: LOW.
--
-- Batch B raised this and did not resolve it: the offer is priced in USD (89
-- a seat, 500 setup) and the column is mrr_eur, in euros. B's own comment says
-- "whoever writes it must convert". WF-C5 is the whoever, and it refuses to
-- guess: with no rate configured it writes converted = true and leaves mrr_eur
-- NULL, because a null is a known gap and a guess is a wrong number in the one
-- table the Friday brief adds up.
--
-- The honest fix is to record what Stripe actually settled, not a mid-market
-- rate picked on the day.
-- ---------------------------------------------------------------------

alter table campaign.pilots
  add column if not exists mrr_usd      numeric(10,2),
  add column if not exists fx_rate_used numeric(12,6),
  add column if not exists fx_rate_at   timestamptz;

do $$ begin
  alter table campaign.pilots add constraint pilots_fx_is_explained check (
    mrr_eur is null or mrr_usd is null or fx_rate_used is not null
  );
exception when duplicate_object then null; end $$;

comment on column campaign.pilots.mrr_usd is
  'What was actually billed. The offer is priced in USD; mrr_eur is a conversion of this.';
comment on column campaign.pilots.fx_rate_used is
  'The rate used to fill mrr_eur, so the euro figure can be recomputed or audited later. Prefer the rate Stripe settled at over a mid-market rate.';


-- ---------------------------------------------------------------------
-- 5. RLS catch-all, borrowed from 002_rls.sql
--
-- 002 has a loop that switches RLS on for every table in the schema. Repeat it
-- here so a table added by this file cannot be the hole in the fence, whichever
-- order these end up being run in.
-- ---------------------------------------------------------------------

do $$
declare t record;
begin
  for t in select tablename from pg_tables where schemaname = 'campaign'
  loop
    execute format('alter table campaign.%I enable row level security', t.tablename);
  end loop;
end $$;
