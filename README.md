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

## Vercel Frontend Deployment

Deploy only the Next.js frontend for now. In Vercel, set the project Root Directory to `frontend`.

Safe frontend environment variables:

```text
NEXT_PUBLIC_APP_NAME=GIS Apply Copilot
NEXT_PUBLIC_API_MODE=demo
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

Use `NEXT_PUBLIC_API_MODE=demo` until a hosted backend with durable storage is ready. The FastAPI + SQLite backend is local-only for now because Vercel serverless storage is not persistent.

Do not commit `.env`, `.vercel/`, tokens, private documents, resume/transcript PDFs, extracted document text, or generated application packets.

From `frontend/`, deployment commands use `VERCEL_TOKEN` from the local environment:

```powershell
vercel link --yes --project "prj_7rRCF8pTAJBrxMQZtsjBgvNYiKGI"
vercel pull --yes --environment=production
vercel build --prod
vercel deploy --prebuilt --prod
```

## Refresh Jobs

```powershell
.\.venv\Scripts\python scripts\refresh_jobs.py
```

The MVP loads enabled sources from `config/sources.yaml`. The default enabled source is `data/sample_jobs.json`, so the dashboard works before real collectors are connected.

The refresh command reports sources checked, disabled sources skipped, jobs collected, new jobs inserted, duplicates updated, jobs marked missing/closed, fresh/stale counts, closing-soon counts, match bands, and per-source errors without stopping the full refresh.

Duplicate jobs are not reinserted. Refresh updates `last_seen_at`, source close/update dates, freshness fields, and scoring while preserving user status such as saved or applied.

Freshness defaults live in `config/application_rules.yaml`:

```yaml
freshness:
  max_default_age_days: 30
  hide_after_days: 45
  fresh_days: 14
  closing_soon_days: 7
  unknown_date_allowed: true
```

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

### USAJobs

USAJobs is the first real API collector. It is disabled by default because USAJobs requires an API key and the email/user-agent used for that key.

Add local-only credentials to `backend/.env`:

```text
USAJOBS_USER_AGENT=your_email@example.com
USAJOBS_API_KEY=replace_with_your_local_secret
```

Then set `enabled: true` for `USAJobs API` in `config/sources.yaml` and run the refresh command. `default_date_posted_days: 30` keeps USAJobs queries recent by default; lower it to 7 or 14 for stricter freshness. Do not commit `backend/.env` or the API key.

Sources can declare freshness coverage with:

```yaml
posted_date_supported: true
close_date_supported: true
updated_date_supported: false
first_seen_only: false
```

### Manual Sources

Manual career-page sources are for human review and copy/paste intake only. To add one safely, add a disabled `manual` source with the career page URL and notes. Do not automate LinkedIn, Indeed, Workday, login-gated portals, or application submission.

## Private Documents

Put your resume PDF in `private/resume/`, then run:

```powershell
Invoke-RestMethod -Method Post http://localhost:8000/documents/resume/extract
```

This creates `private/resume/resume_extracted.md` for local review and manual editing.

Put your transcript PDF in `private/transcript/` only when needed, then run:

```powershell
Invoke-RestMethod -Method Post http://localhost:8000/documents/transcript/extract
```

This creates `private/transcript/transcript_summary.md`. The transcript summary is used only for internships, government/entry-level roles asking for transcript/coursework/GPA/degree proof, or jobs where academic GIS coursework is useful.

`private/`, `*.pdf`, `*.docx`, and `generated/application_packets/` are ignored by Git except placeholder files. Do not commit private documents. Generated application packets stay local. Review all materials before submitting applications.

## Using Pony Alpha / OpenRouter

The backend can use Pony Alpha through OpenRouter for application packet writing. The frontend never receives the OpenRouter key.

Create `backend/.env` locally:

```text
AI_PROVIDER=openrouter
AI_MODEL=openrouter/pony-alpha
OPENROUTER_API_KEY=replace_with_your_local_secret
DATABASE_URL=sqlite:///./gis_apply.db
API_ENV=local
CORS_ORIGINS=http://localhost:3000,https://gis-job-portal.vercel.app
```

Do not commit `backend/.env`. If `OPENROUTER_API_KEY` is missing or still a placeholder, the backend uses the template fallback generator.

Check mode:

```powershell
Invoke-RestMethod http://localhost:8000/ai/status
```

Only sanitized profile/config text, sanitized resume summary text, job details, scoring, missing skills, and the portfolio link are sent to the AI provider. Raw PDFs, transcripts, `.env` files, private folder paths, tokens, and generated packet history are not sent.

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
