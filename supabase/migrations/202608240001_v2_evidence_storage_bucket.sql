-- Private bucket for task/gate/vendor-activity evidence bytes (see
-- backend/app/services/evidence_storage.py). Never public: evidence is
-- only reachable through the backend's authenticated download routes,
-- which fetch bytes server-side with the service-role key.
insert into storage.buckets (id, name, public)
values ('evidence', 'evidence', false)
on conflict (id) do nothing;
