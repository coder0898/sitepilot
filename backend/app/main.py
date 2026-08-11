from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import SessionLocal
from app.routes import access_requests, admin_visibility_v2, auth, communication, dashboard, execution_tasks_v2, permissions, project_dashboard_v2, project_read_models_v2, project_vendors_v2, projects_v2, reports_v2, templates_v2, users, vendors, dependencies_v2, whatsapp_webhook_v2
from app.seed import ensure_seed_data


def create_app() -> FastAPI:
    app = FastAPI(title="SiteOps API")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

    # U3: evidence bytes are created on disk by TaskProgressService, but
    # this directory is deliberately never mounted via StaticFiles - it
    # must only ever be reachable through the authenticated download route.
    Path(settings.evidence_upload_dir).mkdir(parents=True, exist_ok=True)

    app.include_router(dashboard.router)
    app.include_router(auth.router)
    app.include_router(access_requests.router)
    app.include_router(users.router)
    app.include_router(vendors.router)
    app.include_router(communication.router)
    app.include_router(permissions.router)
    # Must precede projects_v2: both are mounted at /api/v2/projects, and
    # projects_v2's GET /{project_id} would otherwise match /summaries and
    # /attention first and reject them as invalid UUIDs.
    app.include_router(project_read_models_v2.router)
    app.include_router(projects_v2.router)
    app.include_router(execution_tasks_v2.router)
    app.include_router(project_dashboard_v2.router)
    app.include_router(reports_v2.router)
    app.include_router(admin_visibility_v2.router)
    app.include_router(project_vendors_v2.router)
    app.include_router(project_vendors_v2.vendors_router)
    app.include_router(whatsapp_webhook_v2.router)
    app.include_router(dependencies_v2.router)
    app.include_router(templates_v2.router)

    @app.on_event("startup")
    def startup() -> None:
        with SessionLocal() as db:
            ensure_seed_data(db)

    return app


app = create_app()
