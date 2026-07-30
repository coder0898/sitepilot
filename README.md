# Wrokved SiteOps

Framework
- Frontend: React.js + Tailwind CSS
- Backend: Python FastAPI
- Database: PostgreSQL/Supabase
- Migrations: Alembic(depreciated)
- Runtime: Docker Compose

## Local run

```bash
docker compose up -d --build
```

Open:

- Frontend: http://localhost:3000
- Backend health: http://localhost:8000/api/health

Default local login:

- Email: superadmin@siteops.local
- Password: admin123

## Services

- `db`: PostgreSQL 16 on host port 5435
- `backend`: FastAPI on host port 8000, runs `alembic upgrade head` on start
- `frontend`: React static app on host port 3000

## Notes

- Existing old MVP database volumes are tolerated by the first Alembic migration.
- For a fully clean test database, run `docker compose down -v` before `docker compose up -d --build`.
- Proof uploads are stored in Docker volume `siteops_uploads` and served from `/uploads` on the backend.
- The React app auto-detects the current browser hostname and calls backend on the same hostname, port `8000` for backend.

## Phase 2 release gate

Before starting Phase 3, run the complete local gate from the repository root:

```bash
python tools/phase2-release-check.py
```

To include the destructive staging lifecycle verification:

```bash
export PHASE2_API_BASE=http://localhost:8000
export PHASE2_SUPER_ADMIN_TOKEN='<staging access token>'
export PHASE2_SOURCE_VERSION_ID='<published version uuid>'
export DATABASE_URL='<staging PostgreSQL SQLAlchemy URL>'
python tools/phase2-release-check.py --skip-install --live
```

The live verifier clones and publishes a new version. Run it only against a controlled staging environment.

Create shareable source archives only with:

```bash
python tools/package-sanitized.py --output SiteOps_Sanitized_Source.zip
```

This command refuses to package prohibited `.env` files or obvious populated secrets.
