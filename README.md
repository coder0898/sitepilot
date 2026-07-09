# SiteOps MVP

Converted from Next.js server actions to:

- Frontend: React + Vite + Tailwind CSS
- Backend: Python FastAPI
- Database: PostgreSQL
- Migrations: Alembic
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
- The React app auto-detects the current browser hostname and calls backend on the same hostname, port `8000`.
