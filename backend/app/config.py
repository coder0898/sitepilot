from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ENVIRONMENT gates any local-only convenience behaviour (auto-seeding,
    # dev-only scripts). Must be explicitly set to "local" to enable those
    # paths; anything else (staging/production/unset in a deployed context)
    # keeps them off. Defaults to "local" so existing local dev workflows
    # keep working without extra configuration.
    environment: str = "local"

    database_url: str = "postgresql+psycopg://siteops:siteops_password@localhost:5435/siteops"

    # CORS_ORIGINS is the documented name. FRONTEND_URL is also accepted as a
    # single-origin fallback so a minimal staging config (only FRONTEND_URL
    # set) still produces a working CORS allow-list.
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    upload_dir: str = "uploads/task-proofs"

    # Supabase server-side config. SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY
    # are accepted as aliases of the existing SUPABASE_BACKEND_URL-derived
    # SUPABASE_URL / SUPABASE_SECRET_KEY names so both naming conventions
    # work without renaming the working docker-compose plumbing.
    supabase_url: str = Field(default="", validation_alias=AliasChoices("SUPABASE_URL", "supabase_url"))
    supabase_publishable_key: str = ""
    supabase_secret_key: str = Field(
        default="", validation_alias=AliasChoices("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY", "supabase_secret_key")
    )

    # Legacy dev bootstrap (used by seed.py's ensure_seed_data path, local only).
    bootstrap_super_admin_email: str = Field(
        default="", validation_alias=AliasChoices("BOOTSTRAP_SUPER_ADMIN_EMAIL", "SUPER_ADMIN_EMAIL", "bootstrap_super_admin_email")
    )
    bootstrap_super_admin_password: str = Field(
        default="", validation_alias=AliasChoices("BOOTSTRAP_SUPER_ADMIN_PASSWORD", "SUPER_ADMIN_PASSWORD", "bootstrap_super_admin_password")
    )

    # Standalone bootstrap_super_admin.py script config (Phase 3). Opt-in via
    # BOOTSTRAP_SUPER_ADMIN=true; SUPER_ADMIN_* reuse the aliases above.
    bootstrap_super_admin_enabled: bool = Field(default=False, validation_alias=AliasChoices("BOOTSTRAP_SUPER_ADMIN", "bootstrap_super_admin_enabled"))
    super_admin_name: str = "Super Admin"

    migration_temp_password: str = ""
    frontend_url: str = "http://localhost:3000"


settings = Settings()
