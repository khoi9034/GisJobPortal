# International Job Coverage

This project supports Southeast Asia and remote APAC coverage through safe sources only:

- broad job APIs such as JSearch, SerpApi, Adzuna where supported, and Remotive
- public ATS feeds when a public endpoint is verified
- Gmail job-alert emails from boards the user configured manually
- manual-review source records for boards that should not be automated

Target regions:

- Vietnam
- Singapore
- Malaysia
- Thailand
- Indonesia
- Philippines
- remote APAC / Southeast Asia roles

Target roles include GIS Analyst, Geospatial Analyst, Spatial Data Analyst, Urban Planning Analyst, Transportation Planning Analyst, Location Intelligence Analyst, Remote Sensing Analyst, Smart Cities Analyst, Climate Resilience Analyst, Land Use Analyst, ArcGIS Analyst, and QGIS Analyst.

The portal does not scrape LinkedIn, Indeed, JobStreet, JobsDB, Glints, VietnamWorks, TopCV, Workday, iCIMS, Taleo, Oracle Cloud, or login-required portals. It never auto-applies and never sends emails automatically.

## Source Strategy

Broad APIs are disabled by default because they need API keys and can return noisy results. Enable them one at a time after validating the source and checking match quality.

SEA email-alert sources are also disabled by default. Create the alerts manually on the job board, authorize Gmail ingestion locally/hosted, then let the portal parse alert emails. This avoids direct scraping while still expanding coverage.

Remotive APAC Remote is the first no-key test source. It uses the public Remotive API with conservative GIS/spatial title/content filters and a score floor. If `scripts/analyze_source_quality.py` shows low-fit noise, disable it again in `config/sources.yaml`.

Recommended alerts to create manually:

- LinkedIn: GIS Analyst Vietnam, Geospatial Analyst Singapore, Urban Planning Analyst Southeast Asia, Remote Sensing Analyst APAC
- Indeed: GIS Analyst Singapore, GIS Analyst Malaysia, GIS Analyst Thailand, GIS Analyst Philippines
- JobStreet/JobsDB: GIS, geospatial, urban planning, transport planning
- Glints: GIS, data analyst, urban planning, location intelligence
- VietnamWorks/TopCV: GIS, QGIS, ArcGIS, urban planning, data analyst

Setup:

```powershell
.\scripts\setup_gmail_local_env.ps1
python scripts\setup_gmail_oauth.py
.\scripts\sync_gmail_to_render.ps1
python scripts\admin_refresh_hosted.py --url https://gisjobportal.onrender.com
```

Then open Daily Review and Apply Today. Alert jobs should show their email-alert source and still require manual review before applying.

## Quality Controls

International broad API sources use:

- `max_jobs_per_source_per_refresh`
- `min_score_by_source`
- GIS/planning title keywords
- seniority and unrelated-title exclusions
- source attribution fields
- duplicate matching by canonical URL and normalized company/title/location

Apply Today keeps low-fit broad API jobs out of the priority queue so weaker international matches do not bury stronger local or public-ATS roles.
