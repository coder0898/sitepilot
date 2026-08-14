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
    # U3 (R18): the outbox dispatcher. `OutboxService.emit` has been writing
    # pending events since Phase 2 and nothing has ever drained them, so
    # every notification the system decided to send is still sitting in the
    # table. These two settings are sourced from environment/`.env` like
    # every other setting here.
    #
    # Enabled by default because a queue nobody drains is the bug this unit
    # exists to fix; the switch is for an operator who needs to stop delivery
    # without redeploying, and for any process that must not dispatch (a
    # migration run, a second replica, a test harness).
    #
    # The wired adapter is still the sandbox one per KTD7 - this unit changes
    # only whether anything drains the outbox, never what is emitted or where
    # it goes. Turning on a REAL provider is a separate, deliberate decision.
    outbox_dispatch_enabled: bool = True
    # 30s: this is a notification queue, not a transaction path. Polling
    # faster costs a query per interval for no benefit anyone can perceive.
    outbox_dispatch_interval_seconds: float = 30.0
    bootstrap_super_admin_email: str = ""
    bootstrap_super_admin_password: str = ""
    migration_temp_password: str = ""
    frontend_url: str = "http://localhost:3000"


settings = Settings()
