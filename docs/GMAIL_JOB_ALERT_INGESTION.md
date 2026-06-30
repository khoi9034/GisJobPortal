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
GMAIL_ALERT_QUERY=(from:linkedin.com OR from:indeed.com) newer_than:14d
```

`runtime/secrets/` is ignored by Git and is the only place OAuth token files should live.

## Current MVP Status

The parser and pasted-email fallback are implemented now. Live Gmail API fetching is guarded and exits cleanly until OAuth is configured.

Test the parser without OAuth:

```powershell
python scripts\ingest_gmail_job_alerts.py --source-hint linkedin --text-file path\to\alert.txt
```

Or use Settings/Profile -> Job Alert Ingestion and paste a full alert email.
