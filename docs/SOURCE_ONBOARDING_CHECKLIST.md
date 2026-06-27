# Source Onboarding Checklist

- Find the employer career page.
- Identify the ATS type: USAJobs, Greenhouse, Lever, manual/public page, or unsupported/login portal.
- Add the source to `config/sources.yaml`.
- Keep the source disabled first.
- Run `python scripts/validate_sources.py`.
- Confirm posted, updated, close, and first-seen date behavior is mapped honestly.
- Enable the source only after validation looks clean.
- Run `python scripts/refresh_jobs.py`.
- Check the dashboard for bad, stale, or irrelevant jobs.
- Generate an application packet only after reviewing the job.

Unsupported/login portals stay manual. Do not automate LinkedIn, Indeed, Workday, logins, or applications.
