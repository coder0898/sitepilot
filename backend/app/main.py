from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import SessionLocal
from app.routes import access_requests, auth, communication, dashboard, execution_v2, permissions, projects_v2, templates_v2, users, vendors, dependencies_v2, vendor_category_mapping_v2
from app.seed import ensure_seed_data


def create_app() -> FastAPI:
    app = FastAPI(title="SiteOps API")

    cors_origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

    app.include_router(dashboard.router)
    app.include_router(auth.router)
    app.include_router(access_requests.router)
    app.include_router(users.router)
    app.include_router(vendors.router)
    app.include_router(vendor_category_mapping_v2.router)
    app.include_router(communication.router)
    app.include_router(permissions.router)
    app.include_router(execution_v2.router)
    app.include_router(projects_v2.router)
    app.include_router(dependencies_v2.router)
    app.include_router(templates_v2.router)

    @app.on_event("startup")
    def startup() -> None:
        # Local-only convenience seeding (dev super admin + sample execution
        # template). Never runs in staging/production - those environments
        # get their Super Admin via the explicit, opt-in
        # `python -m app.scripts.bootstrap_super_admin` script instead
        # (see Phase 3 of the staging deployment prep).
        if settings.environment == "local":
            with SessionLocal() as db:
                ensure_seed_data(db)

    return app


app = create_app()
