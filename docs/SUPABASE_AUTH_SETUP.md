# Supabase Auth and PostgreSQL setup

SiteOps uses different Supabase topologies by environment.

| Environment | Supabase Auth and PostgreSQL |
|---|---|
| Local development | Official Supabase CLI stack running in Docker |
| Internal testing/staging | Dedicated hosted Supabase project |
| Production | Separate hosted Supabase project |

The React application uses Supabase only for authentication and sessions. FastAPI remains the business API and authorization boundary.

## Local development

Requirements:

- Docker Desktop running
- Node.js 20 or newer
- PowerShell
- The project dependencies installed with `npm install`

Start everything from the repository root:

```powershell
npm run local:start
```

This command:

1. Starts the official local Supabase PostgreSQL, Auth, API gateway and email-capture services.
2. Reads the locally generated publishable and secret keys.
3. Writes them to the Git-ignored root `.env` file.
4. Points FastAPI at local Supabase PostgreSQL.
5. Builds the frontend with the browser-safe local Supabase URL and publishable key.
6. Runs the legacy Alembic schema through revision `0019_supabase_auth`.
7. Creates or links the local Super Admin.

Local endpoints:

- Portal: `http://localhost:3000`
- FastAPI: `http://localhost:8000`
- Supabase API/Auth: `http://127.0.0.1:54321`
- Supabase PostgreSQL: `127.0.0.1:54322`
- Local Auth email inbox: `http://127.0.0.1:54324`

Default local login:

- Email: `superadmin@siteops.local`
- Password: `LocalSiteOps!2026`

These are local development credentials only. Change the bootstrap values in the root `.env` before running `npm run local:start` if different local credentials are required.

Check health without displaying API keys:

```powershell
npm run local:status
```

Stop SiteOps and its local Supabase stack without deleting the database:

```powershell
npm run local:stop
```

Do not run `supabase stop --no-backup` or delete Docker volumes unless a destructive local reset is intended.

Password recovery messages are captured locally at `http://127.0.0.1:54324`; no real email is sent.

## Internal testing and production

Staging and production do not use the local Docker keys. Each environment requires its own hosted Supabase project and protected environment variables:

```env
DATABASE_URL=
SUPABASE_PUBLIC_URL=
SUPABASE_BACKEND_URL=
SUPABASE_PUBLISHABLE_KEY=
SUPABASE_SECRET_KEY=
BOOTSTRAP_SUPER_ADMIN_EMAIL=
BOOTSTRAP_SUPER_ADMIN_PASSWORD=
VITE_API_BASE=
```

For a hosted project, `SUPABASE_PUBLIC_URL` and `SUPABASE_BACKEND_URL` normally contain the same HTTPS project URL. The secret key and database credentials must remain backend-only.

Configure the hosted Auth redirect allowlist for the exact staging or production recovery URL. Configure a production SMTP provider before relying on password-recovery email.

## Existing legacy users

Only when migrating accounts that predate Supabase Auth:

1. Set `MIGRATION_TEMP_PASSWORD` in the target environment.
2. Start the backend.
3. Run:

```powershell
docker compose exec backend python -m app.scripts.link_supabase_users
```

4. Remove `MIGRATION_TEMP_PASSWORD`.
5. Send password-recovery emails so users select their own passwords.

Never commit `.env`, database passwords, secret keys or access tokens.