# Hosted Backend Checklist

1. Choose a backend host: Render, Railway, or Fly.io.
2. Create a hosted Postgres database: Neon, Supabase, Railway Postgres, or Render Postgres.
3. Deploy from the repo root, not `backend/`.

Build command:

```text
pip install -r requirements.txt
```

Start command:

```text
python -m uvicorn backend.app.api:app --host 0.0.0.0 --port $PORT
```

The repo also includes a `Procfile` with the same web start command for hosts that read it.

4. Set backend environment variables on the backend host:

```text
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:PORT/DB
API_ENV=production
CORS_ORIGINS=https://gis-job-portal.vercel.app
USAJOBS_USER_AGENT=<local_secret_email_or_user_agent>
USAJOBS_AUTHORIZATION_KEY=<secret_key_from_usajobs>
```

5. Deploy the FastAPI backend.
6. Check:

```text
GET /health
GET /deployment/status
```

7. Run the hosted smoke check:

```powershell
python scripts\check_hosted_backend.py --url <hosted backend URL>
```

Do not point Vercel to the hosted backend until the smoke check reports:

```text
api env: production
database type: postgres
real job count: greater than 0
real sources enabled: greater than 0
production ready: yes
```

If it reports `database type: sqlite`, that backend is only a smoke deployment and should not be used for live production data.

## Using the Render API helper

From the repo root:

```powershell
cd C:\Dev\GisJobPortal
.\scripts\connect_render_backend.ps1
```

The script asks for the Render API key locally with `Read-Host -AsSecureString`. It does not save the key, write it to an env file, or commit it. It checks the Render service, reports whether required env vars are present, checks hosted backend readiness, and optionally triggers a deploy only if you type `y`.

If env vars are missing, add them in the Render dashboard.

8. Export local seed data if needed:

```powershell
python scripts\export_sqlite_to_json.py
```

9. Import seed data into the hosted backend/database only after reviewing the JSON:

```powershell
python scripts\import_json_to_db.py --file runtime\exports\db_seed_YYYYMMDD.json
```

10. Set Vercel frontend variables:

```text
NEXT_PUBLIC_API_MODE=api
NEXT_PUBLIC_API_BASE_URL=<hosted backend URL>
```

11. Redeploy Vercel.
12. Confirm the dashboard badge says `Live API` and real jobs load.

Do not upload private resume/transcript files, generated packets, `.env` files, or local SQLite database files.
