# Daily Refresh Plan

Local MVP:

- Use Windows Task Scheduler to run `python scripts\refresh_jobs.py`.
- Run it from the repo root.
- Keep review manual: no auto-apply, no job-board login automation, no prohibited scraping.

Hosted later:

- Add a scheduler only after the backend is hosted.
- Use the host scheduler, cron, or a small worker process.
- Store jobs in hosted Postgres, not SQLite.

Application packets:

- Generate packets only after user review.
- Keep generated packets local for now.
- Copy/paste materials manually into application portals.

