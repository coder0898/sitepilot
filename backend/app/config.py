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
    # Real Meta WhatsApp Cloud API credentials (see
    # backend/app/services/whatsapp_provider.py). Sourced from
    # environment/`.env` only, mirroring `supabase_secret_key`'s pattern -
    # never hardcoded. Empty by default: with no token/phone-number-id
    # configured, `MetaCloudApiAdapter.send` fails fast with
    # failure_code='not_configured' rather than attempting a doomed call.
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_api_version: str = "v21.0"
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
    # Evidence retention sweep (app.services.evidence_retention): deletes
    # evidence bytes N months after a project's actual completion
    # (V2Project.completed_at), so multi-project evidence storage does not
    # grow forever. Enabled by default for the same reason as
    # outbox_dispatch_enabled above - a policy nobody runs is not a policy.
    # The switch exists for an operator who needs to pause deletion without
    # redeploying (e.g. while validating the sweep against real data).
    evidence_retention_enabled: bool = True
    evidence_retention_months: int = 6
    # Once a day: this is housekeeping against a 6-month window, not a
    # time-sensitive path - polling more often than daily costs a query for
    # no one who could ever perceive the difference.
    evidence_retention_interval_seconds: float = 86400.0
    # Plan Phase 6 (second half): the merged daily task-prompt + task-side
    # escalation sweep (`daily_task_prompts_scheduler.py`). Enabled by
    # default for the same reason as the two schedulers above - a prompt
    # cadence nobody runs is not a cadence. The switch exists for an
    # operator who needs to pause it without redeploying.
    daily_task_prompts_enabled: bool = True
    # Hourly: frequent enough to catch a "morning of start" or "midday"
    # window without needing precise wall-clock scheduling. Per-calendar-day
    # idempotency (see `DailyTaskPromptsService`) makes ticking more often
    # than once a day harmless - it just means a task's prompt fires closer
    # to whichever hour it first becomes eligible.
    daily_task_prompts_interval_seconds: float = 3600.0
    # Plan Phase 6 (second half): the gate due-date reminder + approval-side
    # escalation sweep (`gate_reminder_scheduler.py`). Same enabled-by-
    # default rationale as above.
    gate_reminder_enabled: bool = True
    gate_reminder_interval_seconds: float = 3600.0
    # Plan Phase 8: the automated weekly report-summary pass
    # (`weekly_summary_scheduler.py`). Same enabled-by-default rationale as
    # the schedulers above.
    weekly_summary_enabled: bool = True
    # Hourly, same as `daily_task_prompts_interval_seconds`/
    # `gate_reminder_interval_seconds`: the real cadence gate is the 7-day
    # check inside the pass itself (against the latest weekly
    # `ReportSnapshot.period_start`), not this tick interval - a frequent
    # tick with an internal idempotency/cadence check doing the real
    # gating is the pattern every scheduler in this codebase already uses.
    weekly_summary_interval_seconds: float = 3600.0
    bootstrap_super_admin_email: str = ""
    bootstrap_super_admin_password: str = ""
    migration_temp_password: str = ""
    frontend_url: str = "http://localhost:3000"


settings = Settings()
