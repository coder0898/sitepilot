# Wrokved SiteOps

Framework
- Frontend: React.js + Tailwind CSS
- Backend: Python FastAPI
- Database: PostgreSQL/Supabase
- Migrations: Alembic(depreciated)
- Runtime: Docker Compose Command

## Local run

Prerequisite: Docker Desktop running. `npx supabase` is pulled automatically, no separate install needed.

```bash
npm run local:start
```

This runs `tools/start-local.ps1`, which does everything needed from a clean checkout:

1. Starts the local Supabase stack (Postgres, Auth) via the Supabase CLI.
2. Bootstraps the backend schema with `alembic upgrade head`.
3. Applies the newer domain schema in `supabase/migrations/*.sql`.
4. Generates a git-ignored `.env` with local Supabase credentials and a bootstrap Super Admin login.
5. Builds and starts the `docker compose` stack (backend + frontend) against that database.

Open:

- Frontend: http://localhost:3000
- Backend health: http://localhost:8000/api/health

Default local login (written to `.env` on first run, unless already set there):

- Email: `superadmin@siteops.local`
- Password: `LocalSiteOps!2026`

Other scripts:

- `npm run local:status` - check the stack is up and healthy.
- `npm run local:stop` - stop the stack.

`docker compose up -d --build` on its own only rebuilds/restarts the `backend`/`frontend` containers - it does **not** start Supabase or run any migrations, and fails without the `.env` that `npm run local:start` produces. Use it only to restart the app containers after `npm run local:start` has already set things up once.

## Services

- `backend`: FastAPI on host port 8000, connects to the local Supabase Postgres over `host.docker.internal`
- `frontend`: React static app on host port 3000
- Postgres/Auth are provided by the local Supabase CLI stack, not by a container in this `docker-compose.yml`

## Notes

- For a fully clean database, run `npm run local:stop` then `npm run local:start` again (the script re-bootstraps Supabase and both migration sets from scratch).
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
