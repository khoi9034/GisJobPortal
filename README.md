# GIS Apply Copilot / GisJobPortal

Human-reviewed GIS job application intelligence dashboard for Khoi Nguyen. It finds or imports GIS/planning/geospatial roles, scores them against the local profile, drafts application materials, and tracks application status.

It does not auto-submit applications, log into job boards, scrape LinkedIn/Indeed/Workday, send emails, or claim skills not present in `config/profile.yaml`.

## Stack

- Frontend: Next.js + TypeScript
- Backend: FastAPI + Python
- Database: SQLite
- Config: YAML/JSON

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
cd frontend
npm install
```

## Run Backend

```powershell
.\.venv\Scripts\python -m uvicorn backend.app.api:app --reload --port 8000
```

API docs: `http://localhost:8000/docs`

## Run Frontend

```powershell
cd frontend
npm run dev
```

Dashboard: `http://localhost:3000`

## Refresh Jobs

```powershell
.\.venv\Scripts\python scripts\refresh_jobs.py
```

The MVP loads enabled sources from `config/sources.yaml`. The default enabled source is `data/sample_jobs.json`, so the dashboard works before real collectors are connected.

## Add Job Sources

Edit `config/sources.yaml` or use `POST /sources`.

Supported source types:

- `api`
- `rss`
- `greenhouse`
- `lever`
- `static_url`
- `manual`

Disabled static sources are kept as review targets only. The app intentionally avoids LinkedIn/Indeed scraping and portal automation.

## Tests

```powershell
.\.venv\Scripts\python -m unittest discover -s tests
cd frontend
npm run typecheck
npm run build
```

## Git Push

```powershell
git add .
git commit -m "Build GIS job application copilot MVP"
git push origin main
```

Vercel deployment comes later after authentication/access is provided.
