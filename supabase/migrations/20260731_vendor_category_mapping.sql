
create table if not exists task_vendor_category_mappings (
 id uuid primary key default gen_random_uuid(),
 task_category text not null unique,
 vendor_category_id uuid references vendor_categories(id) on delete set null,
 created_by uuid references users(id),
 created_at timestamptz default now()
);

create table if not exists task_vendor_category_mapping_audit (
 id uuid primary key default gen_random_uuid(),
 task_category text not null,
 action text not null,
 old_vendor_category_id uuid,
 new_vendor_category_id uuid,
 changed_by uuid references users(id),
 created_at timestamptz default now()
);
