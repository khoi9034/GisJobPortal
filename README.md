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

## Daily Review Workflow

1. Run `python scripts/refresh_jobs.py`.
2. Open the dashboard.
3. Go to Daily Review.
4. Review Fresh High Match and Closing Soon first.
5. Mark jobs Interested, Maybe, or Not Interested.
6. Generate a packet only for jobs worth applying to.
7. Mark Ready to Apply.
8. Submit manually outside the app.
9. Mark Applied and schedule follow-up.

For daily local automation, see `docs/DAILY_AUTOMATION_SETUP.md`.

## Testing a Real Application Packet

```powershell
python scripts\refresh_jobs.py
python scripts\qa_application_packet.py
```

Open Daily Review, pick a high-match job, generate the packet, and review every file before applying manually outside the app. The QA command uses the best current active USAJobs job, checks the generated packet for obvious safety/quality issues, and keeps generated packet files local.

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

`config/search_profiles.yaml` stores GIS/planning search profiles such as `gis_analyst_nc`, `planning_gis_nc`, `consulting_gis`, and `federal_gis`. These are simple keyword/location profiles for source tuning; scoring still decides which collected jobs rise to the top.

## Activating Real Job Sources

Keep new real sources disabled until validation passes.

```powershell
.\.venv\Scripts\python scripts\setup_usajobs.py
.\.venv\Scripts\python scripts\validate_sources.py
.\.venv\Scripts\python scripts\refresh_jobs.py
```

- USAJobs requires local-only `USAJOBS_USER_AGENT` and `USAJOBS_AUTHORIZATION_KEY` in `backend/.env`.
- Greenhouse requires a public `board_token`.
- Lever requires a public `site` slug.
- Manual sources are tracked but not scraped unless a safe collector exists.
- Greenhouse `updated_at` is stored as `source_updated_at`, not a posted date.
- Some sources use `first_seen_at` because the public endpoint does not expose a reliable posted date.
- Do not commit credentials, `.env`, private documents, or generated packets.

See `docs/SOURCE_ONBOARDING_CHECKLIST.md` before enabling a new source.
See `docs/LIVE_SOURCE_TARGETS.md` for the current target list.

### Activate USAJobs

USAJobs is the first real API collector. It is disabled by default because USAJobs requires a USAJobs Developer API key and the email/user-agent used for that key.

Add local-only credentials to `backend/.env`:

```text
USAJOBS_USER_AGENT=your_email@example.com
USAJOBS_AUTHORIZATION_KEY=replace_with_your_local_secret
```

Then enable the source and validate it before refreshing:

```powershell
.\.venv\Scripts\python scripts\source_toggle.py enable "USAJobs API"
.\.venv\Scripts\python scripts\setup_usajobs.py
.\.venv\Scripts\python scripts\validate_sources.py
.\.venv\Scripts\python scripts\refresh_jobs.py
```

Use `scripts\source_toggle.py list` to check enabled/disabled status. Do not commit `backend/.env` or the API key.

USAJobs supports `source_posted_at` from `PublicationStartDate` and `source_closes_at` from `ApplicationCloseDate`. Keep `default_date_posted_days: 30` or lower in `config/sources.yaml` so refreshes stay recent; lower it to 7 or 14 for stricter freshness.

Sources can declare freshness coverage with:

```yaml
posted_date_supported: true
close_date_supported: true
updated_date_supported: false
first_seen_only: false
```

### Greenhouse

Use public Greenhouse Job Board API sources only:

```yaml
- name: Example Greenhouse
  type: greenhouse
  url: https://boards.greenhouse.io/example
  board_token: example
  company: Example Company
  enabled: false
  updated_date_supported: true
  first_seen_only: true
```

Greenhouse exposes `updated_at`; the app stores it as `source_updated_at`. It is not treated as `source_posted_at`, so freshness uses `first_seen_at` unless a true posted date is available.

### Lever

Use public Lever Postings API sources only:

```yaml
- name: Example Lever
  type: lever
  url: https://jobs.lever.co/example
  site: example
  company: Example Company
  enabled: false
  first_seen_only: true
```

Lever postings are normalized from the public JSON endpoint. If no reliable posted date is present, freshness uses `first_seen_at`.

### Manual Sources

Manual career-page sources are for human review and copy/paste intake only. To add one safely, add a disabled `manual` source with the career page URL and notes. Do not automate LinkedIn, Indeed, Workday, login-gated portals, or application submission; those sources do not provide a safe public ATS endpoint for this MVP.

## Expanding Job Sources

USAJobs is live locally. Before enabling another real source, run:

```powershell
python scripts\discover_sources.py
python scripts\validate_target_sources.py
```

Greenhouse and Lever sources are company-specific; only add a `board_token` or `site` slug after the public board URL is confirmed. Local government pages should stay disabled/manual first unless a safe public endpoint is confirmed. Unsupported or login-based portals such as LinkedIn, Indeed, Workday, and similar systems are intentionally not automated.

Discovery writes `docs/SOURCE_DISCOVERY_REPORT.md` and `docs/SOURCE_ACTIVATION_STATUS.md`.

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
