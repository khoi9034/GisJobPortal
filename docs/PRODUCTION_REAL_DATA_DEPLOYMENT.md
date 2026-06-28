# Production Real Data Deployment

## Why Vercel Shows Demo Jobs

The Vercel frontend runs in the cloud. It cannot reach `http://127.0.0.1:8001` on your laptop, and it cannot read the local SQLite file at `data/jobs.sqlite3`.

Right now:

- Local frontend + local FastAPI can show real USAJobs/Woolpert data.
- Vercel frontend uses demo mode until a hosted backend URL exists.

## Why Not SQLite In Production

SQLite is fine for the local MVP. It should not be the durable production database for a hosted backend because app containers can restart, move hosts, or lose local disk state.

## Recommended Architecture

Use:

- Vercel frontend
- Hosted FastAPI backend
- Hosted Postgres database

Good backend hosts: Render, Railway, or Fly.io.

Good Postgres hosts: Neon, Supabase, Railway Postgres, or Render Postgres.

## Environment Shape

Local:

```text
DATABASE_URL=sqlite:///./data/jobs.sqlite3
API_ENV=local
CORS_ORIGINS=http://localhost:3000,https://gis-job-portal.vercel.app
```

Production:

```text
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:PORT/DB
API_ENV=production
CORS_ORIGINS=https://gis-job-portal.vercel.app
```

The current app recognizes Postgres URLs for deployment status and planning, while the runtime remains SQLite-first until the hosted Postgres adapter is cut over. Treat `database type: sqlite` in `/deployment/status` as not production-ready for live Vercel data.

## Seeding Production Later

Export local seed data:

```powershell
python scripts\export_sqlite_to_json.py
```

Import into the configured backend database:

```powershell
python scripts\import_json_to_db.py --file runtime\exports\db_seed_YYYYMMDD.json
```

`runtime/exports/` is ignored by Git. Review seed files before moving them to any hosted environment.
