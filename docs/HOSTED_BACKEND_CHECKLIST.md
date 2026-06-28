# Hosted Backend Checklist

1. Choose a backend host: Render, Railway, or Fly.io.
2. Create a hosted Postgres database: Neon, Supabase, Railway Postgres, or Render Postgres.
3. Set backend environment variables on the backend host:

```text
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:PORT/DB
API_ENV=production
CORS_ORIGINS=https://gis-job-portal.vercel.app
USAJOBS_USER_AGENT=your_email@example.com
USAJOBS_AUTHORIZATION_KEY=your_host_secret
```

4. Deploy the FastAPI backend.
5. Check:

```text
GET /health
GET /deployment/status
```

6. Export local seed data if needed:

```powershell
python scripts\export_sqlite_to_json.py
```

7. Import seed data into the hosted backend/database only after reviewing the JSON.
8. Set Vercel frontend variables:

```text
NEXT_PUBLIC_API_MODE=api
NEXT_PUBLIC_API_BASE_URL=<hosted backend URL>
```

9. Redeploy Vercel.
10. Confirm the dashboard badge says `Live API` and real jobs load.

Do not upload private resume/transcript files, generated packets, `.env` files, or local SQLite database files.
