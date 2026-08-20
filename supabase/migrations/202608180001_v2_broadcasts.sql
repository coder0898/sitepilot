-- Communication module: admin project-wide meeting announcements/broadcasts.
--
-- `broadcast_recipients` is a snapshot taken at create time (see
-- app/services/broadcast_service.py), not a live join - who a past
-- broadcast was sent to must not silently change if the project's team or
-- vendor mappings change afterwards. `broadcast_templates` intentionally
-- stores only reusable message content (no recipients), since a template is
-- meant to be reused across different projects with different teams.

create table if not exists siteops_v2.broadcasts (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references siteops_v2.projects(id) on delete cascade,
  title text not null,
  meeting_date date,
  meeting_time text,
  location_or_link text,
  agenda text,
  message_body text not null,
  recipient_groups jsonb not null default '[]'::jsonb,
  send_mode text not null,
  scheduled_at timestamptz,
  status text not null,
  created_by uuid not null references users(id) on delete restrict,
  created_at timestamptz not null default now(),
  sent_at timestamptz,
  constraint ck_v2_broadcasts_send_mode check (send_mode in ('now', 'scheduled')),
  constraint ck_v2_broadcasts_status check (status in ('scheduled', 'sent', 'partially_failed', 'failed')),
  constraint ck_v2_broadcasts_scheduled_at_pair check (
    (send_mode = 'scheduled' and scheduled_at is not null) or (send_mode = 'now' and scheduled_at is null)
  )
);
create index if not exists ix_v2_broadcasts_project on siteops_v2.broadcasts(project_id);
create index if not exists ix_v2_broadcasts_status on siteops_v2.broadcasts(status);
create index if not exists ix_v2_broadcasts_created_at on siteops_v2.broadcasts(created_at desc);
revoke all on table siteops_v2.broadcasts from anon, authenticated;

create table if not exists siteops_v2.broadcast_recipients (
  id uuid primary key default gen_random_uuid(),
  broadcast_id uuid not null references siteops_v2.broadcasts(id) on delete cascade,
  recipient_type text not null,
  user_id uuid references users(id) on delete set null,
  vendor_id uuid references siteops_v2.vendors(id) on delete set null,
  vendor_contact_id uuid references siteops_v2.vendor_contacts(id) on delete set null,
  name text not null,
  role_label text not null,
  company_name text,
  phone text,
  email text,
  channels jsonb not null default '[]'::jsonb,
  delivery_status text not null default 'pending',
  delivered_at timestamptz,
  constraint ck_v2_broadcast_recipients_type check (
    recipient_type in ('project_manager', 'site_supervisor', 'internal_employee', 'vendor', 'vendor_contact')
  ),
  constraint ck_v2_broadcast_recipients_delivery_status check (delivery_status in ('pending', 'sent', 'skipped_no_contact'))
);
create index if not exists ix_v2_broadcast_recipients_broadcast on siteops_v2.broadcast_recipients(broadcast_id);
revoke all on table siteops_v2.broadcast_recipients from anon, authenticated;

create table if not exists siteops_v2.broadcast_templates (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  title text not null,
  agenda text,
  message_body text not null,
  created_by uuid not null references users(id) on delete restrict,
  created_at timestamptz not null default now()
);
create index if not exists ix_v2_broadcast_templates_created_at on siteops_v2.broadcast_templates(created_at desc);
revoke all on table siteops_v2.broadcast_templates from anon, authenticated;
