# Backend Deployment

Local run:

```powershell
.\.venv\Scripts\python -m uvicorn backend.app.api:app --reload --port 8001
```

Local env file:

```text
DATABASE_URL=sqlite:///./gis_apply.db
API_ENV=local
CORS_ORIGINS=http://localhost:3000,https://gis-job-portal.vercel.app
```

`DATABASE_URL` currently supports local SQLite URLs. Add a Postgres driver and migration path only when a hosted Postgres database exists.

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8001/health
```

When the backend is hosted later, set Vercel frontend env:

```text
NEXT_PUBLIC_API_MODE=local
NEXT_PUBLIC_API_BASE_URL=https://your-hosted-backend.example.com
```

Privacy warning: do not deploy private resume/transcript PDFs, extracted documents, `.env` files, or generated application packets. Keep `private/` and `generated/application_packets/` local unless a reviewed storage plan exists.
