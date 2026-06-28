# Backend Deployment

Local run:

```powershell
.\.venv\Scripts\python -m uvicorn backend.app.api:app --reload --port 8001
```

Local env file:

```text
DATABASE_URL=sqlite:///./data/jobs.sqlite3
API_ENV=local
CORS_ORIGINS=http://localhost:3000,https://gis-job-portal.vercel.app
```

`DATABASE_URL` defaults to local SQLite. Use hosted Postgres only with a hosted backend and durable database.

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8001/health
```

When the backend is hosted later, set Vercel frontend env:

```text
NEXT_PUBLIC_API_MODE=api
NEXT_PUBLIC_API_BASE_URL=https://your-hosted-backend.example.com
```

Privacy warning: do not deploy private resume/transcript PDFs, extracted documents, `.env` files, or generated application packets. Keep `private/` and `generated/application_packets/` local unless a reviewed storage plan exists.
