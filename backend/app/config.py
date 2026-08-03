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
    bootstrap_super_admin_email: str = ""
    bootstrap_super_admin_password: str = ""
    migration_temp_password: str = ""
    frontend_url: str = "http://localhost:3000"


settings = Settings()
