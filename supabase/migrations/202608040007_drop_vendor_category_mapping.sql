-- Removes the standalone "Vendor Category Mapping" page's tables. That
-- page manually linked a template task category (e.g. "Ceiling") to a
-- vendor category one at a time via TaskVendorCategoryMapping - superseded
-- by communication.py's get_hub() auto-seeding a matching VendorCategory
-- for every distinct ExecutionTemplateTask.category directly, with the
-- existing Communication Hub category picker/manager as the manual path.
-- Both tables are unused (task_vendor_category_mappings had zero rows
-- mapped at removal time) - dropped outright rather than left dormant.

drop table if exists task_vendor_category_mapping_audit;
drop table if exists task_vendor_category_mappings;
