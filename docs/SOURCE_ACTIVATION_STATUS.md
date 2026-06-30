# Source Activation Status

Generated: 2026-06-28T00:49:54.649520+00:00

| Organization | Source type | Status | Career URL | Date support | Validation result | Next action |
|---|---|---|---|---|---|---|
| USAJobs | api | active | https://data.usajobs.gov/api/search | Posted date and close date supported | ok | Run validate_target_sources.py, then refresh. |
| Cabarrus County | unknown | needs manual review | https://www.cabarruscounty.us/Government/Departments/Human-Resources/Careers | First-seen only unless endpoint exposes dates | disabled | Confirm public ATS or keep manual. |
| City of Concord | manual/public career page | needs manual review | https://concordnc.gov/Departments/Human-Resources/Careers | First-seen only unless endpoint exposes dates | disabled | Confirm public ATS or keep manual. |
| City of Charlotte | unknown | needs manual review | https://www.charlottenc.gov/Services/Jobs | First-seen only unless endpoint exposes dates | disabled | Confirm public ATS or keep manual. |
| Mecklenburg County | unknown | needs manual review | https://www.mecknc.gov/CountyManagersOffice/BOCC/Pages/Careers.aspx | First-seen only unless endpoint exposes dates | disabled | Confirm public ATS or keep manual. |
| Wake County | unknown | needs manual review | https://www.wake.gov/departments-government/human-resources/jobs-wake-county | First-seen only unless endpoint exposes dates | disabled | Confirm public ATS or keep manual. |
| NCDOT | unsupported/login portal | unsupported | https://www.ncdot.gov/about-us/our-people/careers/Pages/default.aspx | First-seen only unless endpoint exposes dates | disabled | Manual browser review only. |
| NC Department of Commerce | unknown | needs manual review | https://www.commerce.nc.gov/about-us/careers | First-seen only unless endpoint exposes dates | disabled | Confirm public ATS or keep manual. |
| Esri | manual/public career page | needs manual review | https://www.esri.com/en-us/about/careers/job-search | First-seen only unless endpoint exposes dates | disabled | Confirm public ATS or keep manual. |
| Kimley-Horn | unsupported/login portal | unsupported | https://www.kimley-horn.com/careers/ | First-seen only unless endpoint exposes dates | disabled | Manual browser review only. |
| WSP | unknown | needs manual review | https://www.wsp.com/en-us/careers | First-seen only unless endpoint exposes dates | disabled | Confirm public ATS or keep manual. |
| AECOM | manual/public career page | needs manual review | https://aecom.jobs/ | First-seen only unless endpoint exposes dates | disabled | Confirm public ATS or keep manual. |
| HDR | unsupported/login portal | unsupported | https://www.hdrinc.com/careers | First-seen only unless endpoint exposes dates | disabled | Manual browser review only. |
| Dewberry | unsupported/login portal | unsupported | https://www.dewberry.com/careers | First-seen only unless endpoint exposes dates | disabled | Manual browser review only. |
| Timmons Group | manual/public career page | needs manual review | https://www.timmons.com/careers/ | First-seen only unless endpoint exposes dates | disabled | Confirm public ATS or keep manual. |
| WithersRavenel | unsupported/login portal | unsupported | https://withersravenel.com/careers/ | First-seen only unless endpoint exposes dates | disabled | Manual browser review only. |
| Stewart | manual/public career page | needs manual review | https://www.stewartinc.com/careers/ | First-seen only unless endpoint exposes dates | disabled | Confirm public ATS or keep manual. |
| McAdams | manual/public career page | needs manual review | https://mcadamsco.com/careers/ | First-seen only unless endpoint exposes dates | disabled | Confirm public ATS or keep manual. |
| Freese and Nichols | unsupported/login portal | unsupported | https://www.freese.com/careers/ | First-seen only unless endpoint exposes dates | disabled | Manual browser review only. |
| SAM Companies | unsupported/login portal | unsupported | https://www.sam.biz/careers/ | First-seen only unless endpoint exposes dates | disabled | Manual browser review only. |
| Woolpert | greenhouse | active | https://woolpert.com/careers/ | First-seen only unless endpoint exposes dates | ok | Run validate_target_sources.py, then refresh. |
| NV5 Geospatial | unsupported/login portal | unsupported | https://www.nv5.com/careers/ | First-seen only unless endpoint exposes dates | disabled | Manual browser review only. |
| Michael Baker International | unsupported/login portal | unsupported | https://mbakerintl.com/careers/ | First-seen only unless endpoint exposes dates | disabled | Manual browser review only. |

## Broad API Coverage Pack

| Provider | Coverage tier | Credential status | Enabled | Expected coverage | Risk / terms notes | Next action |
|---|---|---|---|---|---|---|
| Adzuna | broad_api | needs local `ADZUNA_APP_ID` + `ADZUNA_APP_KEY` | false | Broad US GIS/planning/search API results | Use API terms only; do not scrape underlying boards | Add keys locally, validate, then enable if quality is acceptable |
| JSearch / RapidAPI | broad_api | needs local `RAPIDAPI_KEY` | false | Broad aggregated jobs with publisher attribution | Use RapidAPI/JSearch terms; preserve publisher attribution | Add key locally, validate, then enable if quality is acceptable |
| SerpApi Google Jobs | broad_api | needs local `SERPAPI_KEY` | false | Google Jobs API results through SerpApi | Use SerpApi API only; do not scrape Google or job boards | Add key locally, validate, then enable if quality is acceptable |
| Remotive | broad_api | no key required | false | Remote GIS/data jobs, likely lower volume | Public API only; remote roles may be noisy | Enable only if remote coverage is useful |

## Public ATS Placeholders

| ATS | Status | Date support | Next action |
|---|---|---|---|
| Ashby | needs manual review | first-seen only until confirmed | Add company-specific source only after verifying public endpoint |
| SmartRecruiters | needs manual review | first-seen only until confirmed | Add company-specific source only after verifying public endpoint |
| Workable | needs manual review | first-seen only until confirmed | Add company-specific source only after verifying public endpoint |
| GovernmentJobs / NeoGov | manual review | first-seen only unless official feed/API is confirmed | Do not scrape; use manual review or official API/feed only |

## Unsupported / Manual Only

LinkedIn, Indeed, Workday, iCIMS, Taleo, Oracle Cloud, and login-required portals are marked unsupported for automation. Open them manually if useful; do not scrape, log in, or auto-apply through the portal.
