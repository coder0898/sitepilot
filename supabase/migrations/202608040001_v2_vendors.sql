-- Phase 2 U1: V2 vendor/capability tables (R1).
--
-- These tables are the target of a one-time, validated import from the
-- legacy `vendors` / `vendor_contacts` tables (see
-- backend/app/services/vendor_import.py, VendorImportService). They are
-- NOT live-synced with the legacy schema - legacy remains the system of
-- record for its own schema, and new project/task work reads only these
-- siteops_v2 tables going forward.
--
-- Modeling notes:
--  * `vendors.legacy_vendor_id` is a nullable, unique back-reference to the
--    legacy `vendors.id` a row was imported from. Unique (not just
--    indexed) so the import can be safely re-run: it is looked up first,
--    and a legacy vendor already present here is skipped rather than
--    re-inserted, making the import idempotent. Nullable because a future
--    unit may create V2 vendor rows directly (no legacy origin) - this
--    table is not scoped to import-only writes forever, only this one-time
--    import is.
--  * The legacy `vendors.category` free-text field is normalized here into
--    `capability_categories` (lookup) + `vendor_capabilities` (join), so a
--    vendor's capability set is a proper many-to-many relationship going
--    forward instead of a single free-text column.
--  * `vendors.parent_vendor_id` mirrors the legacy self-referential
--    parent/sub-vendor relationship (`Vendor.parent_vendor_id`), which is
--    the sole authoritative source the import uses for that relationship.
--    The legacy `contractor_relationships` table is a separate legacy
--    representation that is explicitly NOT migrated into this schema - see
--    VendorImportService for how a disagreement between the two is
--    surfaced (flagged for manual review, never auto-resolved).
--  * `migration_pending` is deliberately not a valid `engagement_type`
--    value here: vendors in that legacy state are excluded from import
--    entirely until resolved in the legacy module, so no V2 row for them
--    should ever exist with that state.
--  * Only one primary contact per vendor is allowed. Enforced here with a
--    partial unique index on `vendor_contacts(vendor_id) where is_primary`
--    as a DB-level backstop, matching this codebase's existing
--    double-enforcement convention (see e.g. TaskDelayEvent's check
--    constraint) - VendorImportService also rejects this case in Python
--    before ever attempting the write.

create table if not exists siteops_v2.vendors (
  id uuid primary key default gen_random_uuid(),
  legacy_vendor_id uuid unique,
  name text not null,
  contact_person text not null,
  phone text not null,
  whatsapp text,
  email text,
  address text,
  gst_number text,
  notes text,
  status text not null default 'active',
  engagement_type text not null default 'main' check (engagement_type in ('main', 'sub_vendor')),
  parent_vendor_id uuid references siteops_v2.vendors(id) on delete restrict,
  created_by uuid references users(id) on delete restrict,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint ck_v2_vendors_sub_vendor_parent check (engagement_type != 'sub_vendor' or parent_vendor_id is not null),
  constraint ck_v2_vendors_main_without_parent check (engagement_type != 'main' or parent_vendor_id is null)
);
create index if not exists ix_v2_vendors_parent on siteops_v2.vendors(parent_vendor_id);
create index if not exists ix_v2_vendors_status on siteops_v2.vendors(status);
revoke all on table siteops_v2.vendors from anon, authenticated;

create table if not exists siteops_v2.capability_categories (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  created_at timestamptz not null default now()
);
revoke all on table siteops_v2.capability_categories from anon, authenticated;

create table if not exists siteops_v2.vendor_capabilities (
  id uuid primary key default gen_random_uuid(),
  vendor_id uuid not null references siteops_v2.vendors(id) on delete cascade,
  category_id uuid not null references siteops_v2.capability_categories(id) on delete restrict,
  created_at timestamptz not null default now(),
  constraint uq_v2_vendor_capabilities_vendor_category unique (vendor_id, category_id)
);
create index if not exists ix_v2_vendor_capabilities_vendor on siteops_v2.vendor_capabilities(vendor_id);
create index if not exists ix_v2_vendor_capabilities_category on siteops_v2.vendor_capabilities(category_id);
revoke all on table siteops_v2.vendor_capabilities from anon, authenticated;

create table if not exists siteops_v2.vendor_contacts (
  id uuid primary key default gen_random_uuid(),
  vendor_id uuid not null references siteops_v2.vendors(id) on delete cascade,
  name text not null,
  designation text,
  phone text not null,
  whatsapp text,
  is_primary boolean not null default false,
  created_at timestamptz not null default now()
);
create index if not exists ix_v2_vendor_contacts_vendor on siteops_v2.vendor_contacts(vendor_id);
create unique index if not exists uq_v2_vendor_contacts_vendor_primary on siteops_v2.vendor_contacts(vendor_id) where is_primary;
revoke all on table siteops_v2.vendor_contacts from anon, authenticated;
