from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import SessionLocal
from app.routes import access_requests, admin_visibility_v2, auth, broadcasts, communication, dashboard, execution_tasks_v2, permissions, project_dashboard_v2, project_read_models_v2, project_vendors_v2, projects_v2, reports_v2, templates_v2, users, vendors, dependencies_v2, whatsapp_webhook_v2
from app.seed import ensure_seed_data
from app.services.evidence_retention_scheduler import start_retention_scheduler, stop_retention_scheduler
from app.services.outbox_scheduler import start_dispatcher, stop_dispatcher


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
    app.include_router(broadcasts.router)

    @app.on_event("startup")
    def startup() -> None:
        with SessionLocal() as db:
            ensure_seed_data(db)

    # U3 (R18): start the outbox dispatcher. Separate from the seed hook
    # above because it must be async - `asyncio.create_task` needs a running
    # event loop - and because the two have nothing to do with each other.
    @app.on_event("startup")
    async def start_outbox_dispatcher() -> None:
        start_dispatcher(app)

    @app.on_event("shutdown")
    async def stop_outbox_dispatcher() -> None:
        await stop_dispatcher(app)

    # Same rationale as the outbox dispatcher above: async startup task,
    # started/stopped alongside it but independent of it.
    @app.on_event("startup")
    async def start_evidence_retention_scheduler() -> None:
        start_retention_scheduler(app)

    @app.on_event("shutdown")
    async def stop_evidence_retention_scheduler() -> None:
        await stop_retention_scheduler(app)

    return app


app = create_app()
