from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import SessionLocal
from app.routes import auth, dashboard, projects, tasks, users, vendors
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

    app.include_router(dashboard.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(vendors.router)
    app.include_router(projects.router)
    app.include_router(tasks.router)

    @app.on_event("startup")
    def startup() -> None:
        with SessionLocal() as db:
            ensure_seed_data(db)

    return app


app = create_app()
