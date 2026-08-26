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
- Task/gate/vendor-activity evidence is stored in the local Supabase Storage `evidence` bucket (started as part of `npx supabase start`), not on local disk - see `backend/app/services/evidence_storage.py`.
- The React app auto-detects the current browser hostname and calls backend on the same hostname, port `8000` for backend.

## Deploy

Live environment:

- Frontend: https://sitepilot-psi.vercel.app/
- Backend: https://sitepilot-backend-f1q4.onrender.com (health check: `/api/health`)
- Database/Auth/Storage: Supabase (hosted)

### 1. Supabase

1. Create a project at supabase.com.
2. Bootstrap the baseline schema from `backend/`: `DATABASE_URL=<hosted connection string> alembic upgrade head`.
3. Apply the domain schema: `npx supabase link --project-ref <ref>` then `npx supabase db push` (applies `supabase/migrations/*.sql`, including the private `evidence` Storage bucket).
4. Import the authoritative 45-day template from `backend/`: `DATABASE_URL=<hosted connection string> python -m app.scripts.import_v2_template import --created-by-email <existing active Super Admin email>`. Verify with the same command's `verify` subcommand.

`DATABASE_URL` for all of the above must use the **Session pooler** connection string (not Direct connection or Transaction pooler) with a `postgresql+psycopg://` scheme, e.g.:

```
postgresql+psycopg://postgres.<project-ref>:<url-encoded-password>@aws-0-<region>.pooler.supabase.com:5432/postgres
```

### 2. Render (backend)

Create a plain **Web Service** (not a Blueprint - Blueprint deploys can prompt for payment/billing details that a Web Service does not):

- Runtime: Docker, Root Directory: `backend`, Branch: `master`
- Region: match Supabase's project region for low latency (this project: Singapore, matching Supabase's `ap-south-1`)
- Instance Type: Free
- Health Check Path: `/api/health`
- No persistent disk needed - evidence/uploads never touch local disk

`render.yaml` documents the full set of environment variables this service expects (`DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY`, `CORS_ORIGINS`, `FRONTEND_URL`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_API_VERSION`, `WHATSAPP_WEBHOOK_SECRET`, `BOOTSTRAP_SUPER_ADMIN_EMAIL`, `BOOTSTRAP_SUPER_ADMIN_PASSWORD`) - set the real values by hand in Render's dashboard; none of them belong in source control.

Render's free plan spins the service down after ~15 minutes of no inbound traffic. That pauses the in-process schedulers in `backend/app/main.py` (daily task prompts, gate/meeting reminders, weekly summaries, evidence retention, outbox dispatch) and slows the WhatsApp inbound webhook's first response after a sleep. Point a free external keep-alive (e.g. cron-job.org, every ~10 minutes) at `/api/health` to keep it always warm.

### 3. Vercel (frontend)

- Import the repo, set **Root Directory** to `frontend` (monorepo - this can only be set in Vercel's project settings, not a config file).
- Build environment variables: `VITE_API_BASE` (the Render URL above), `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`, `VITE_FRONTEND_URL` (this Vercel domain - pins where password-reset emails redirect, so triggering a reset from a local dev session never sends the link to `localhost` instead). Never put `SUPABASE_SECRET_KEY` here - a frontend build ships to every visitor's browser.

### 4. Close the loop

- Set `FRONTEND_URL` on Render to the real Vercel domain. It is not cosmetic - `app/routes/access_requests.py` uses it to build the links inside access-verification and password-reset emails, so leaving it as `http://localhost:3000` breaks those emails for real users.
- `CORS_ORIGINS` is currently unused: `backend/app/main.py` hardcodes `allow_origins=["*"]` regardless of this setting.
- Once `WHATSAPP_ACCESS_TOKEN`/`WHATSAPP_PHONE_NUMBER_ID`/`WHATSAPP_WEBHOOK_SECRET` are set, register `<render-url>/api/v2/whatsapp/inbound` as the webhook URL in Meta's WhatsApp Cloud API app settings.

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
