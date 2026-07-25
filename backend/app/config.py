from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://siteops:siteops_password@localhost:5435/siteops"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    upload_dir: str = "uploads/task-proofs"
    supabase_url: str = ""
    supabase_publishable_key: str = ""
    supabase_secret_key: str = ""
    bootstrap_super_admin_email: str = ""
    bootstrap_super_admin_password: str = ""
    migration_temp_password: str = ""
    frontend_url: str = "http://localhost:3000"


settings = Settings()
