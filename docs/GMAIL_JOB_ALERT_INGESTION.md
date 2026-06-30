# Gmail Job Alert Ingestion

LinkedIn and Indeed coverage comes from email alerts, not scraping.

## Workflow

1. Create LinkedIn and Indeed job alerts manually on their websites.
2. Let those alerts arrive in Gmail.
3. Authorize the portal to read matching Gmail messages only.
4. The parser extracts obvious title, company, location, and job URLs from alert emails.
5. Jobs are deduplicated, scored, and added to Daily Review / Apply Today.
6. You still review every job and apply manually outside the portal.

## What This Does Not Do

- No LinkedIn scraping.
- No Indeed scraping.
- No browser bots, headless browsers, extensions, or click automation.
- No LinkedIn/Indeed login automation.
- No auto-apply.
- No automatic email sending.

## Local Configuration

Add placeholder values locally in `backend/.env`; never commit them:

```text
GMAIL_INGESTION_ENABLED=false
GMAIL_CLIENT_ID=replace_with_local_secret_only
GMAIL_CLIENT_SECRET=replace_with_local_secret_only
GMAIL_TOKEN_PATH=runtime/secrets/gmail_token.local.json
GMAIL_ALERT_QUERY=(from:linkedin.com OR from:indeed.com OR subject:("job alert")) newer_than:14d
```

`runtime/secrets/` is ignored by Git and is the only place OAuth token files should live.

## Setup Steps

A. Create LinkedIn job alerts manually once.

B. Create Indeed job alerts manually once.

C. In Google Cloud, create OAuth credentials for a desktop app or local/web client that allows:

```text
http://127.0.0.1:8765/
```

D. Run local setup:

```powershell
.\scripts\setup_gmail_local_env.ps1
python scripts\setup_gmail_oauth.py
.\scripts\sync_gmail_to_render.ps1
```

E. Run hosted refresh:

```powershell
python scripts\admin_refresh_hosted.py --url https://gisjobportal.onrender.com
```

F. Open Vercel and confirm LinkedIn/Indeed alert jobs appear in Daily Review / Apply Today.

## Current MVP Status

Live Gmail fetching is implemented through the Gmail REST API with read-only scope. It runs only when `GMAIL_INGESTION_ENABLED=true` and credentials plus token are configured.

For Render, `sync_gmail_to_render.ps1` stores the local token JSON as `GMAIL_TOKEN_JSON_BASE64` in Render env vars. It does not print the token.

Test the parser without OAuth:

```powershell
python scripts\ingest_gmail_job_alerts.py --source-hint linkedin --text-file path\to\alert.txt
```

Or use Settings/Profile -> Job Alert Ingestion and paste a full alert email.

## Safety

- Gmail API scope: `https://www.googleapis.com/auth/gmail.readonly`
- Local tokens stay in ignored `runtime/secrets/`.
- Hosted tokens are stored only in Render env vars.
- The portal fetches Gmail alert emails only.
- The portal never fetches LinkedIn/Indeed job pages.
- The portal never applies or sends messages.
