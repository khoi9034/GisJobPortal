# Production Backend Plan

Current state:

- Frontend is deployed on Vercel at `https://gis-job-portal.vercel.app`.
- Backend is local FastAPI + SQLite.
- Demo fallback keeps the Vercel frontend usable without a hosted backend.
- Private resume/transcript files and generated application packets stay local.

Recommended next backend:

- Host FastAPI on Render, Railway, or Fly.io.
- Use managed Postgres, such as Neon, Supabase, Railway Postgres, or Render Postgres.
- Set `DATABASE_URL` in the host environment.
- Point `NEXT_PUBLIC_API_BASE_URL` in Vercel to the hosted API URL.

Do not use SQLite as durable production storage. SQLite is fine for local MVP work, but serverless/local files are not reliable production persistence.

Alternative later: convert selected API endpoints to Next.js route handlers and use hosted Postgres. Do that only if it actually reduces moving parts.

Do not upload private resume PDFs, transcript PDFs, extracted private documents, or generated packets to cloud storage yet.

