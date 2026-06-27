# Daily Automation Setup

The local backend can refresh sources once per day, update SQLite, and write a Markdown digest for the Daily Review queue.

## Install The Scheduled Task

From the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_daily_refresh_task.ps1
```

This creates a Windows scheduled task named `GIS Job Portal Daily Refresh` that runs daily at 8:00 AM.

## Run Once Manually

```powershell
python scripts\run_daily_refresh_once.py
```

This validates sources, refreshes jobs, verifies a report was written, and prints the report path plus summary counts.

## Remove The Scheduled Task

```powershell
powershell -ExecutionPolicy Bypass -File scripts\remove_daily_refresh_task.ps1
```

## Local Files

- Reports: `runtime/reports/daily_review_YYYY-MM-DD.md`
- Logs: `runtime/logs/daily_refresh.log`

`runtime/` is ignored by Git. Do not commit logs, reports, credentials, databases, private documents, or generated packets.

## Morning Review

1. Open the local backend and frontend.
2. Go to Daily Review.
3. Read Latest Daily Digest.
4. Review Fresh High Match and Closing Soon first.
5. Mark jobs Interested, Maybe, or Not Interested.
6. Generate packets only for jobs worth applying to.
7. Submit manually outside the app.
8. Mark Applied and follow up later.

The automation never auto-applies, never sends email, and never generates packets without your action.
