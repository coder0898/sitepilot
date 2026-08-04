from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://siteops:siteops_password@localhost:5435/siteops"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    upload_dir: str = "uploads/task-proofs"
    # U3: evidence bytes for task_progress_updates/task_evidence live in a
    # SEPARATE directory, never passed to StaticFiles in main.py (unlike
    # `upload_dir` above, which backs the public `/uploads` mount). This
    # directory must never be mounted publicly - evidence is only reachable
    # via the authenticated GET .../evidence/{file_id} download route.
    evidence_upload_dir: str = "evidence_storage"
    supabase_url: str = ""
    supabase_publishable_key: str = ""
    supabase_secret_key: str = ""
    # Phase 2 U6: HMAC secret used to verify `X-Hub-Signature-256` on
    # inbound WhatsApp webhook deliveries (see
    # backend/app/routes/whatsapp_webhook_v2.py). Sourced from
    # environment/`.env` only, mirroring `supabase_secret_key`'s pattern -
    # never hardcoded. Empty by default: with no configured secret, no
    # valid signature can ever be computed, so the route safely rejects
    # every inbound request until an operator configures this.
    whatsapp_webhook_secret: str = ""
    bootstrap_super_admin_email: str = ""
    bootstrap_super_admin_password: str = ""
    migration_temp_password: str = ""
    frontend_url: str = "http://localhost:3000"


settings = Settings()
