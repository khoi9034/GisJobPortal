import tempfile
import unittest
import base64
import io
import os
import json
from pathlib import Path
from datetime import date, timedelta
from contextlib import redirect_stdout
from unittest.mock import patch
from fastapi import HTTPException

from scripts import admin_refresh_hosted, analyze_job_matches, analyze_source_quality, check_frontend_data_mode, check_hosted_backend, check_live_frontend_data, check_ports, check_vercel_frontend_fetch, discover_sources, export_application_packet, export_sqlite_to_json, import_json_to_db, ingest_gmail_job_alerts, qa_application_packet, setup_gmail_oauth, setup_usajobs, source_toggle, test_scheduled_refresh_payload, validate_target_sources
from backend.app import collectors, db, reports
from backend.app.ai.base import MissingAPIKeyError
from backend.app.ai.openrouter_client import OpenRouterClient
from backend.app.ai.prompts import materials_user_prompt, safe_generation_context
from backend.app.ai.service import ai_status
from backend.app.api import AlertEmailImport, admin_refresh_jobs, ai_status_endpoint, application_board as application_board_endpoint, apply_today as apply_today_endpoint, deployment_status, health, import_job_alert_email_text, jobs as jobs_endpoint, latest_report as latest_report_endpoint, overview as overview_endpoint, refresh as refresh_endpoint, review_queue as review_queue_endpoint, sources as sources_endpoint, validate_source_config
from backend.app.documents import (
    build_packet_files,
    detect_document_checklist,
    extract_resume,
    extract_transcript,
    should_use_transcript,
)
from backend.app.email_alerts import create_job_from_alert, dedupe_alert_jobs, gmail_alert_query_profiles, ingest_gmail_alerts, load_gmail_token, parse_alert_jobs, parse_indeed_alert_text, parse_linkedin_alert_text
from backend.app.freshness import apply_freshness
from backend.app.materials import format_material_context, generate_materials
from backend.app.paths import admin_refresh_token, api_env, cors_origins, database_path, database_runtime_type, database_type, database_url, database_url_scheme
from backend.app.profile import load_profile
from backend.app.scoring import score_band, score_job
from backend.app.sources import load_search_profiles, load_sources
from backend.app.source_validation import validate_source


class MvpTests(unittest.TestCase):
    def setUp(self):
        self.profile = load_profile()
        self.job = {
            "title": "GIS Analyst",
            "company": "City of Concord",
            "location": "Concord, NC",
            "remote_status": "onsite",
            "source": "test",
            "source_url": "https://example.com/job",
            "apply_url": "https://example.com/job/apply",
            "description": "ArcGIS Enterprise, parcels, zoning, planning, web map, public works, and Python automation.",
            "requirements": "GIS, ArcGIS Pro, SQL, land use, county data, and public sector communication.",
        }

    def test_scoring_engine_scores_good_gis_fit_high(self):
        scored = score_job(self.job, self.profile)
        self.assertGreaterEqual(scored["match_score"], 75)
        self.assertIn("arcgis_relevance", scored["scoring_breakdown"])
        self.assertIn("ArcGIS", scored["keyword_matches"])
        for field in ["positive_matches", "penalty_matches", "score_reason", "score_band", "recommended_resume_angle"]:
            self.assertIn(field, scored)

    def test_gis_analyst_title_scores_strong_when_description_matches(self):
        scored = score_job({**self.job, "title": "GIS Analyst", "description": "ArcGIS Enterprise, geospatial data, spatial analysis, Python automation, SQL, web GIS, parcels, zoning, and planning."}, self.profile)
        self.assertGreaterEqual(scored["match_score"], 70)
        self.assertIn(scored["score_band"], {"strong fit", "excellent fit"})
        self.assertIn("gis analyst", scored["positive_matches"])

    def test_senior_or_principal_jobs_are_penalized(self):
        junior = score_job({**self.job, "title": "GIS Analyst"}, self.profile)
        senior = score_job({**self.job, "title": "Senior GIS Manager", "requirements": self.job["requirements"] + " 10+ years required."}, self.profile)
        self.assertLess(senior["match_score"], junior["match_score"])
        self.assertIn("manager", senior["penalty_matches"])
        self.assertIn("7+ years", senior["penalty_matches"])

    def test_score_band_labels(self):
        self.assertEqual(score_band(90), "excellent fit")
        self.assertEqual(score_band(70), "strong fit")
        self.assertEqual(score_band(55), "possible fit")
        self.assertEqual(score_band(40), "weak/maybe")
        self.assertEqual(score_band(39), "low fit")

    def test_duplicate_detection_uses_company_title_location_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            first = apply_freshness(self.job, checked_at="2026-06-01")
            second = apply_freshness(self.job, checked_at="2026-06-15")
            first_id, first_duplicate = db.insert_job(first, path)
            second_id, second_duplicate = db.insert_job(second, path)
            self.assertIsNotNone(first_id)
            self.assertFalse(first_duplicate)
            self.assertEqual(second_id, first_id)
            self.assertTrue(second_duplicate)
            updated = db.get_job(first_id, path)
            self.assertEqual(updated["first_seen_at"], "2026-06-01")
            self.assertEqual(updated["last_seen_at"], "2026-06-15")

    def test_profile_loading(self):
        self.assertEqual(self.profile["name"], "Khoi Nguyen")
        self.assertNotIn("phone", self.profile)
        self.assertIn("ArcGIS Pro", self.profile["skills"])

    def test_material_generation_prompt_formatting(self):
        scored_job = {**self.job, **score_job(self.job, self.profile)}
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}, clear=False), patch("backend.app.ai.service.load_backend_env"):
            materials = generate_materials(scored_job, self.profile)
            context = format_material_context(scored_job, self.profile)
        combined = "\n".join([context, materials["cover_letter"], materials["followup_email"]])
        self.assertIn(self.profile["portfolio"], combined)
        self.assertIn("Application Follow-Up", materials["followup_email"])
        self.assertNotIn("expert", combined.lower())
        self.assertNotIn("github", materials["cover_letter"].lower())

    def test_status_updates_validate_allowed_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            job_id, _ = db.insert_job(self.job, path)
            updated = db.update_job_fields(job_id, {"status": "saved"}, path)
            self.assertEqual(updated["status"], "saved")
            with self.assertRaises(ValueError):
                db.update_job_fields(job_id, {"status": "auto_applied"}, path)

    def test_application_status_flow(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            job_id, _ = db.insert_job(self.job, path)
            for status in ["materials_generated", "ready_to_apply", "applied"]:
                updated = db.update_job_fields(job_id, {"status": status}, path)
                self.assertEqual(updated["status"], status)

    def test_mark_started_sets_application_started_at(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            job_id, _ = db.insert_job(self.job, path)
            updated = db.mark_application_started(job_id, path)
        self.assertEqual(updated["application_started_at"], db.now_iso())
        self.assertEqual(updated["application_url_opened_at"], db.now_iso())
        self.assertEqual(updated["outcome_status"], "ready_to_apply")

    def test_mark_applied_sets_applied_at_and_outcome_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            job_id, _ = db.insert_job(self.job, path)
            updated = db.mark_applied(job_id, path)
        self.assertEqual(updated["status"], "applied")
        self.assertEqual(updated["outcome_status"], "applied")
        self.assertEqual(updated["applied_at"], db.now_iso())

    def test_follow_up_due_default_logic(self):
        today = date.fromisoformat(db.now_iso())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            private_id, _ = db.insert_job({**self.job, "company": "Woolpert", "source": "Woolpert Careers", "source_url": "https://example.com/private"}, path)
            gov_id, _ = db.insert_job({**self.job, "source": "USAJobs API", "source_url": "https://example.com/gov"}, path)
            closed_id, _ = db.insert_job({**self.job, "source_url": "https://example.com/closed-follow", "source_closes_at": db.now_iso()}, path)
            private_job = db.mark_applied(private_id, path)
            gov_job = db.mark_applied(gov_id, path)
            closed_job = db.mark_applied(closed_id, path)
        self.assertEqual(private_job["follow_up_due_at"], (today + timedelta(days=7)).isoformat())
        self.assertEqual(gov_job["follow_up_due_at"], (today + timedelta(days=10)).isoformat())
        self.assertEqual(closed_job["follow_up_due_at"], "")

    def test_follow_up_sent_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            job_id, _ = db.insert_job(self.job, path)
            db.mark_applied(job_id, path)
            updated = db.mark_follow_up_sent(job_id, path)
        self.assertEqual(updated["follow_up_sent_at"], db.now_iso())
        self.assertEqual(updated["status"], "applied")

    def test_application_updates_do_not_erase_review_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            job_id, _ = db.insert_job(self.job, path)
            db.update_job_review(job_id, {"review_status": "interested"}, path)
            updated = db.mark_applied(job_id, path)
        self.assertEqual(updated["review_status"], "interested")

    def test_application_board_endpoint_shape(self):
        with patch("backend.app.api.ensure_seeded"), patch("backend.app.api.db.application_board", return_value={"ready_to_apply": [], "started": [], "applied": [], "follow_up_due": [], "interview": [], "rejected_closed": []}):
            row = application_board_endpoint()
        self.assertIn("ready_to_apply", row)
        self.assertIn("follow_up_due", row)

    def test_source_loading(self):
        sources = load_sources()
        self.assertTrue(any(source["type"] == "manual" and source["enabled"] for source in sources))
        self.assertTrue(all(source["type"] in {"api", "jsearch", "rss", "greenhouse", "lever", "static_url", "manual", "linkedin_email_alert", "indeed_email_alert", "job_alert_email", "gmail_job_alerts"} for source in sources))
        broad = [source for source in sources if source.get("coverage_tier") == "broad_api"]
        self.assertGreaterEqual(len(broad), 4)
        self.assertTrue(all(not source.get("enabled") or source["type"] == "jsearch" or source["name"] == "Remotive APAC Remote" for source in broad))
        self.assertTrue(any(source.get("requires_api_key") for source in broad))
        self.assertTrue(any(source["name"] == "LinkedIn Job Alerts Email" and not source["enabled"] for source in sources))
        self.assertTrue(any(source["name"] == "Indeed Job Alerts Email" and not source["enabled"] for source in sources))

    def test_southeast_asia_sources_are_disabled_safely(self):
        sources = load_sources()
        names = {source["name"]: source for source in sources}
        for name in ["JSearch Southeast Asia GIS", "SerpApi Google Jobs SEA", "Adzuna International", "Remotive APAC Remote"]:
            self.assertEqual(names[name]["coverage_tier"], "broad_api")
            self.assertIn(names[name]["region_scope"], {"southeast_asia", "international", "apac"})
        self.assertTrue(names["Remotive APAC Remote"]["enabled"])
        self.assertEqual(names["Remotive APAC Remote"]["min_score_by_source"], 55)
        self.assertEqual(names["Remotive APAC Remote"]["max_jobs_per_source_per_refresh"], 25)
        self.assertFalse(names["JSearch Southeast Asia GIS"]["enabled"])
        for name in ["SerpApi Google Jobs SEA", "Adzuna International"]:
            self.assertFalse(names[name]["enabled"])
        for name in ["JobStreet JobsDB Job Alerts Email", "Glints Job Alerts Email", "VietnamWorks Job Alerts Email", "TopCV Job Alerts Email"]:
            self.assertFalse(names[name]["enabled"])
            self.assertFalse(names[name]["scraping_supported"])
            self.assertEqual(names[name]["coverage_tier"], "big_board_email_alert")
        for name in ["LinkedIn SEA Scraping", "Indeed SEA Scraping", "JobStreet Scraping", "Glints Scraping", "VietnamWorks Scraping", "TopCV Scraping"]:
            self.assertFalse(names[name]["enabled"])
            self.assertEqual(names[name]["coverage_tier"], "unsupported")

    def test_jsearch_source_profiles_are_tuned_and_keyed(self):
        names = {source["name"]: source for source in load_sources()}
        useful = ["JSearch GIS US", "JSearch Remote GIS", "JSearch Singapore GIS"]
        tuned_off = [
            "JSearch Planning US",
            "JSearch Southeast Asia GIS",
            "JSearch Vietnam GIS",
            "JSearch APAC Remote Sensing",
            "JSearch Location Intelligence",
        ]
        for name in [*useful, *tuned_off]:
            self.assertEqual(names[name]["type"], "jsearch")
            self.assertTrue(names[name]["requires_api_key"])
            self.assertEqual(names[name]["env_key"], "RAPIDAPI_KEY")
            self.assertLessEqual(names[name]["max_api_requests_per_refresh"], 1)
            self.assertLessEqual(names[name]["request_timeout_seconds"], 12)
        for name in useful:
            self.assertTrue(names[name]["enabled"])
            self.assertGreaterEqual(names[name]["min_score_by_source"], 55)
            self.assertLessEqual(names[name]["max_jobs_per_source_per_refresh"], 10)
        for name in tuned_off:
            self.assertFalse(names[name]["enabled"])
            self.assertLessEqual(names[name]["max_jobs_per_source_per_refresh"], 5)

    def test_jsearch_useful_profiles_stay_enabled(self):
        names = {source["name"]: source for source in load_sources()}
        self.assertEqual(
            {name for name, source in names.items() if source.get("type") == "jsearch" and source.get("enabled")},
            {"JSearch GIS US", "JSearch Remote GIS", "JSearch Singapore GIS"},
        )

    def test_noisy_jsearch_profiles_are_capped_or_disabled(self):
        names = {source["name"]: source for source in load_sources()}
        for name in [
            "JSearch GIS US",
            "JSearch Planning US",
            "JSearch Remote GIS",
            "JSearch Southeast Asia GIS",
            "JSearch Vietnam GIS",
            "JSearch Singapore GIS",
            "JSearch APAC Remote Sensing",
            "JSearch Location Intelligence",
        ]:
            self.assertLessEqual(names[name]["max_jobs_per_source_per_refresh"], 10)
            self.assertLessEqual(names[name]["max_api_requests_per_refresh"], 1)

    def test_enabled_sea_broad_api_missing_keys_does_not_break_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            source = {"name": "JSearch Southeast Asia GIS", "type": "jsearch", "url": "https://jsearch.p.rapidapi.com/search", "enabled": True}
            with patch.dict(os.environ, {"RAPIDAPI_KEY": ""}, clear=False), patch("backend.app.collectors.load_backend_env"):
                result = collectors.refresh_jobs(path, sources_override=[source])
        self.assertEqual(result["sources_checked"], 1)
        self.assertIn("JSearch Southeast Asia GIS", result["errors"])

    def test_jsearch_timeout_does_not_fail_whole_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            sources = [
                {"name": "JSearch Timeout", "type": "jsearch", "url": "https://jsearch.p.rapidapi.com/search-v2", "enabled": True},
                {"name": "Temp Manual Jobs", "type": "manual", "url": str(Path(tmp) / "missing.json"), "enabled": True},
            ]
            with patch("backend.app.collectors.collect_jsearch", side_effect=TimeoutError("timed out")):
                result = collectors.refresh_jobs(path, sources_override=sources)
        self.assertIn("JSearch Timeout", result["errors"])
        self.assertGreaterEqual(result["jobs_collected"], 1)

    def test_enabled_broad_api_missing_keys_does_not_break_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            source = {"name": "Adzuna Jobs API", "type": "api", "provider": "adzuna", "url": "https://api.adzuna.com/v1/api/jobs/us/search/1", "enabled": True}
            with patch.dict(os.environ, {"ADZUNA_APP_ID": "", "ADZUNA_APP_KEY": ""}, clear=False), patch("backend.app.collectors.load_backend_env"):
                result = collectors.refresh_jobs(path, sources_override=[source])
        self.assertEqual(result["sources_checked"], 1)
        self.assertIn("Adzuna Jobs API", result["errors"])

    def test_adzuna_collector_normalizes_mock_response(self):
        source = {"name": "Adzuna Jobs API", "type": "api", "provider": "adzuna", "url": "https://api.adzuna.com/v1/api/jobs/us/search/1", "enabled": True, "search_terms": ["GIS Analyst"], "locations": ["North Carolina"]}
        data = {"results": [{"id": "adz-1", "title": "GIS Analyst", "company": {"display_name": "Example County"}, "location": {"display_name": "Charlotte, NC"}, "redirect_url": "https://jobs.example.com/apply?id=1", "description": "<p>ArcGIS parcels zoning</p>", "created": "2026-06-01T00:00:00Z"}]}
        with patch.dict(os.environ, {"ADZUNA_APP_ID": "id", "ADZUNA_APP_KEY": "key"}, clear=False), patch("backend.app.collectors.load_backend_env"), patch("backend.app.collectors.fetch_json", return_value=data):
            jobs = collectors.collect_adzuna(source)
        self.assertEqual(jobs[0]["title"], "GIS Analyst")
        self.assertEqual(jobs[0]["source_posted_at"], "2026-06-01T00:00:00Z")
        self.assertEqual(jobs[0]["original_source"], "")
        self.assertIn("Adzuna", jobs[0]["attribution_note"])

    def test_jsearch_collector_normalizes_links_and_metadata(self):
        source = {"name": "JSearch GIS US", "type": "jsearch", "url": "https://jsearch.p.rapidapi.com/search", "enabled": True, "search_terms": ["GIS Analyst"], "locations": ["North Carolina"]}
        data = {
            "data": {"jobs": [{
                "job_id": "js-1",
                "job_title": "GIS Analyst",
                "employer_name": "Example County",
                "employer_logo": "https://logo.example.com/logo.png",
                "employer_website": "https://examplecounty.gov",
                "job_publisher": "Google Jobs",
                "job_employment_type": "FULLTIME",
                "job_apply_link": "https://jobs.example.com/apply/1",
                "job_apply_is_direct": True,
                "apply_options": [{"publisher": "County Careers", "apply_link": "https://jobs.example.com/apply/1"}],
                "job_description": "<p>ArcGIS parcels zoning</p>",
                "job_is_remote": False,
                "job_posted_at_datetime_utc": "2026-06-01T00:00:00Z",
                "job_city": "Charlotte",
                "job_state": "NC",
                "job_country": "US",
                "job_google_link": "https://www.google.com/search?q=job",
                "job_min_salary": 50000,
                "job_max_salary": 70000,
                "required_technologies": ["ArcGIS", "Python"],
            }]}
        }
        with patch.dict(os.environ, {"RAPIDAPI_KEY": "new-rotated-key"}, clear=False), patch("backend.app.collectors.load_backend_env"), patch("backend.app.collectors.fetch_json_request", return_value=data):
            jobs = collectors.collect_jsearch(source)
        job = jobs[0]
        self.assertEqual(job["title"], "GIS Analyst")
        self.assertEqual(job["company"], "Example County")
        self.assertEqual(job["location"], "Charlotte, NC, US")
        self.assertEqual(job["external_job_id"], "js-1")
        self.assertEqual(job["apply_url"], "https://jobs.example.com/apply/1")
        self.assertEqual(job["source_url"], "https://www.google.com/search?q=job")
        self.assertEqual(job["link_status"], "available")
        self.assertTrue(job["apply_is_direct"])
        self.assertEqual(job["apply_options_json"][0]["publisher"], "County Careers")
        self.assertIn("ArcGIS", job["requirements"])

    def test_jsearch_apply_option_and_missing_link_fallbacks(self):
        source = {"name": "JSearch GIS US", "type": "jsearch", "url": "https://jsearch.p.rapidapi.com/search", "enabled": True, "search_terms": ["GIS Analyst"], "locations": [""]}
        data = {
            "data": [
                {"job_id": "js-2", "job_title": "GIS Analyst", "employer_name": "County", "job_location": "NC", "apply_options": [{"apply_link": "https://example.com/apply"}]},
                {"job_id": "js-3", "job_title": "GIS Technician", "employer_name": "City", "job_location": "NC", "job_google_link": "https://google.example/job"},
                {"job_id": "js-4", "job_title": "Spatial Analyst", "employer_name": "Planner", "job_location": "NC"},
            ]
        }
        with patch.dict(os.environ, {"RAPIDAPI_KEY": "new-rotated-key"}, clear=False), patch("backend.app.collectors.load_backend_env"), patch("backend.app.collectors.fetch_json_request", return_value=data):
            jobs = collectors.collect_jsearch(source)
        self.assertEqual(jobs[0]["apply_url"], "https://example.com/apply")
        self.assertEqual(jobs[0]["link_status"], "available")
        self.assertEqual(jobs[1]["source_url"], "https://google.example/job")
        self.assertEqual(jobs[1]["apply_url"], "")
        self.assertEqual(jobs[1]["link_status"], "source_only")
        self.assertEqual(jobs[2]["link_status"], "missing")

    def test_jsearch_respects_source_refresh_cap_before_more_api_calls(self):
        source = {
            "name": "JSearch GIS US",
            "type": "jsearch",
            "url": "https://jsearch.p.rapidapi.com/search",
            "enabled": True,
            "search_terms": ["GIS Analyst", "Geospatial Analyst"],
            "locations": ["North Carolina", "Remote"],
            "max_jobs_per_source_per_refresh": 2,
        }
        data = {"data": [
            {"job_id": "js-a", "job_title": "GIS Analyst", "employer_name": "County", "job_location": "NC"},
            {"job_id": "js-b", "job_title": "GIS Technician", "employer_name": "City", "job_location": "NC"},
            {"job_id": "js-c", "job_title": "Spatial Analyst", "employer_name": "Firm", "job_location": "NC"},
        ]}
        with patch.dict(os.environ, {"RAPIDAPI_KEY": "new-rotated-key"}, clear=False), patch("backend.app.collectors.load_backend_env"), patch("backend.app.collectors.fetch_json_request", return_value=data) as fetch:
            jobs = collectors.collect_jsearch(source)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(fetch.call_count, 1)

    def test_remotive_collector_normalizes_mock_response(self):
        source = {"name": "Remotive Remote Jobs", "type": "api", "provider": "remotive", "url": "https://remotive.com/api/remote-jobs", "enabled": True, "search_terms": ["GIS"]}
        data = {"jobs": [{"id": 7, "title": "Remote GIS Analyst", "company_name": "Remote Co", "candidate_required_location": "USA", "url": "https://remote.example.com/gis", "description": "ArcGIS and Python", "publication_date": "2026-06-02T00:00:00"}]}
        with patch("backend.app.collectors.fetch_json", return_value=data):
            jobs = collectors.collect_remotive(source)
        self.assertEqual(jobs[0]["remote_status"], "remote")
        self.assertEqual(jobs[0]["original_source"], "Remotive")
        self.assertEqual(jobs[0]["source_posted_at"], "2026-06-02T00:00:00")

    def test_fetch_json_sends_public_user_agent(self):
        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self, *_args): return None
            def read(self): return b'{"ok": true}'
        captured = {}
        def fake_urlopen(req, timeout=0):
            captured["headers"] = dict(req.header_items())
            return FakeResponse()
        with patch("backend.app.collectors.request.urlopen", side_effect=fake_urlopen):
            self.assertEqual(collectors.fetch_json("https://remotive.com/api/remote-jobs")["ok"], True)
        self.assertIn("User-Agent", {key.title(): value for key, value in captured["headers"].items()})

    def test_canonical_duplicate_detection_merges_api_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            first = {**self.job, "source": "Adzuna Jobs API", "source_url": "https://www.example.com/jobs/123?utm_source=adzuna", "apply_url": "https://www.example.com/jobs/123?utm_source=adzuna"}
            second = {**self.job, "source": "JSearch RapidAPI", "source_url": "https://example.com/jobs/123?ref=jsearch", "apply_url": "https://example.com/jobs/123?ref=jsearch"}
            first_id, first_duplicate = db.insert_job(first, path)
            second_id, second_duplicate = db.insert_job(second, path)
        self.assertFalse(first_duplicate)
        self.assertEqual(first_id, second_id)
        self.assertTrue(second_duplicate)

    def test_source_attribution_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            job_id, _ = db.insert_job({**self.job, "source": "JSearch RapidAPI", "original_source": "County Careers", "attribution_note": "Collected through JSearch/RapidAPI broad jobs API."}, path)
            job = db.get_job(job_id, path)
        self.assertEqual(job["source"], "JSearch RapidAPI")
        self.assertEqual(job["original_source"], "County Careers")
        self.assertIn("JSearch", job["attribution_note"])

    def test_unsupported_sources_are_not_called(self):
        source = {"name": "LinkedIn Manual Only", "type": "manual", "url": "https://www.linkedin.com/jobs/", "enabled": True, "coverage_tier": "unsupported"}
        with patch("builtins.open") as mocked_open:
            jobs = collectors.collect_from_source(source)
        self.assertEqual(jobs, [])
        mocked_open.assert_not_called()

    def test_setup_job_api_keys_script_is_secret_safe(self):
        text = Path("scripts/setup_job_api_keys.ps1").read_text(encoding="utf-8")
        self.assertIn("Read-Host", text)
        self.assertIn("backend\\.env", text)
        self.assertNotRegex(text, r"(ADZUNA_APP_KEY|RAPIDAPI_KEY|SERPAPI_KEY)=['\"][A-Za-z0-9_-]{12,}")

    def test_sync_job_api_keys_to_render_script_is_secret_safe(self):
        text = Path("scripts/sync_job_api_keys_to_render.ps1").read_text(encoding="utf-8")
        self.assertIn("srv-d90stu3sq97s739mpta0", text)
        self.assertIn("Read-Host", text)
        self.assertIn("RAPIDAPI_KEY", text)
        self.assertNotRegex(text, r"RAPIDAPI_KEY\s*=\s*['\"][A-Za-z0-9_-]{12,}")
        self.assertNotIn("Set-Content", text)

    def test_parse_linkedin_alert_text_with_multiple_jobs(self):
        text = """
        GIS Analyst at City of Charlotte, Charlotte, NC
        https://www.linkedin.com/jobs/view/123456
        Geospatial Analyst at Woolpert, Remote
        https://www.linkedin.com/jobs/view/789012
        """
        jobs = parse_linkedin_alert_text(text)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0]["title"], "GIS Analyst")
        self.assertEqual(jobs[0]["company"], "City of Charlotte")
        self.assertIn("linkedin", jobs[0]["attribution_note"].lower())

    def test_parse_indeed_alert_text_with_multiple_jobs(self):
        text = """
        Planning Technician - Cabarrus County - Concord, NC
        https://www.indeed.com/viewjob?jk=abc123
        GIS Technician | City of Concord | Concord, NC
        https://www.indeed.com/viewjob?jk=def456
        """
        jobs = parse_indeed_alert_text(text)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[1]["company"], "City of Concord")
        self.assertIn("indeed", jobs[1]["attribution_note"].lower())

    def test_parse_sea_board_alert_text_with_multiple_jobs(self):
        samples = {
            "jobstreet": "GIS Analyst at Urban Data Lab, Singapore\nhttps://www.jobstreet.com/job/123\nQGIS Analyst - Planning Co - Kuala Lumpur\nhttps://www.jobsdb.com/job/456",
            "glints": "Location Intelligence Analyst at Map Studio, Jakarta\nhttps://glints.com/opportunities/jobs/abc",
            "vietnamworks": "ArcGIS Analyst at Planning Vietnam, Ho Chi Minh City\nhttps://www.vietnamworks.com/job/789",
            "topcv": "QGIS Analyst at Spatial VN, Hanoi\nhttps://www.topcv.vn/viec-lam/101",
        }
        for hint, text in samples.items():
            jobs = parse_alert_jobs(hint, text)
            self.assertTrue(jobs, hint)
            self.assertIn("job alert email", jobs[0]["attribution_note"].lower())
            self.assertTrue(jobs[0]["apply_url"].startswith("https://"))

    def test_create_job_shell_from_alert_email(self):
        job = create_job_from_alert(
            {"title": "GIS Analyst", "company": "Example County", "location": "NC", "apply_url": "https://www.linkedin.com/jobs/view/1", "description": "ArcGIS"},
            "linkedin",
        )
        self.assertEqual(job["source"], "LinkedIn Job Alerts Email")
        self.assertIn("Description", job["description"] + "Description")

    def test_dedupe_repeated_alert_jobs(self):
        rows = [
            {"title": "GIS Analyst", "company": "County", "location": "NC", "apply_url": "https://www.linkedin.com/jobs/view/1"},
            {"title": "GIS Analyst", "company": "County", "location": "NC", "apply_url": "https://www.linkedin.com/jobs/view/1"},
        ]
        self.assertEqual(len(dedupe_alert_jobs(rows)), 1)

    def test_gmail_missing_credentials_skip_cleanly(self):
        output = io.StringIO()
        with patch.dict(os.environ, {"GMAIL_INGESTION_ENABLED": "false"}, clear=True), patch("backend.app.email_alerts.load_backend_env"), redirect_stdout(output):
            self.assertEqual(ingest_gmail_job_alerts.main([]), 0)
        self.assertIn("not configured", output.getvalue())
        self.assertNotIn("client_secret_value", output.getvalue())

    def test_gmail_token_path_is_ignored_runtime_secret(self):
        self.assertIn("runtime/secrets/", Path(".gitignore").read_text(encoding="utf-8"))
        with patch.dict(os.environ, {}, clear=True), patch("backend.app.email_alerts.load_backend_env"):
            self.assertEqual(ingest_gmail_job_alerts.gmail_config()["token_path"], "runtime/secrets/gmail_token.local.json")

    def test_setup_gmail_oauth_uses_readonly_scope(self):
        text = Path("scripts/setup_gmail_oauth.py").read_text(encoding="utf-8")
        self.assertIn("gmail.readonly", text)
        self.assertIn("getpass", text)
        self.assertIn("runtime", str(setup_gmail_oauth.TOKEN_PATH))
        self.assertNotRegex(text, r"refresh_token['\"]?:\\s*['\"][A-Za-z0-9._-]{20,}")

    def test_gmail_setup_helpers_do_not_hardcode_secrets(self):
        combined = Path("scripts/setup_gmail_local_env.ps1").read_text(encoding="utf-8") + Path("scripts/sync_gmail_to_render.ps1").read_text(encoding="utf-8")
        self.assertIn("Read-Host", combined)
        self.assertIn("GMAIL_TOKEN_JSON_BASE64", combined)
        self.assertIn("subject:(geospatial)", combined)
        self.assertNotRegex(combined, r"ya29\\.|1//[A-Za-z0-9_-]{20,}|GMAIL_CLIENT_SECRET\\s*=\\s*['\"][A-Za-z0-9_-]{20,}")

    def test_gmail_alert_query_profiles_exist_for_sea_boards(self):
        profiles = gmail_alert_query_profiles()
        for name in ["linkedin_indeed_us", "linkedin_indeed_sea", "jobstreet_jobsdb", "glints", "vietnamworks_topcv"]:
            self.assertIn(name, profiles)
            self.assertIn("newer_than:14d", profiles[name])

    def test_hosted_gmail_token_base64_decodes_without_printing_secret(self):
        token = {"refresh_token": "refresh-token-secret", "access_token": "access-token-secret"}
        encoded = base64.b64encode(json.dumps(token).encode("utf-8")).decode("ascii")
        with patch.dict(os.environ, {"GMAIL_TOKEN_JSON_BASE64": encoded}, clear=True), patch("backend.app.email_alerts.load_backend_env"):
            loaded = load_gmail_token()
        self.assertEqual(loaded["refresh_token"], "refresh-token-secret")

    def test_mocked_gmail_ingestion_creates_alert_jobs(self):
        emails = [{"id": "m1", "source_hint": "linkedin", "text": "GIS Analyst at Example County, Concord, NC\nhttps://www.linkedin.com/jobs/view/123456"}]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            with patch("backend.app.email_alerts.gmail_config", return_value={"enabled": "true", "client_id": "id", "client_secret": "secret", "token_path": "runtime/secrets/gmail_token.local.json", "token_json_base64": "x", "query": "q"}), patch("backend.app.email_alerts.gmail_configured", return_value=True), patch("backend.app.email_alerts.gmail_fetch_alert_texts", return_value=emails):
                result = ingest_gmail_alerts(path)
                rows = db.list_jobs(path=path)
        self.assertEqual(result["alert_emails_checked"], 1)
        self.assertEqual(result["alert_jobs_inserted"], 1)
        self.assertEqual(rows[0]["source"], "LinkedIn Job Alerts Email")

    def test_alert_import_endpoint_scores_and_adds_daily_review_job(self):
        text = "GIS Analyst at Example County, Concord, NC\nhttps://www.linkedin.com/jobs/view/123456"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            original_insert_job = db.insert_job
            original_get_job = db.get_job

            def insert_job(job):
                return original_insert_job(job, path)

            def get_job(job_id):
                return original_get_job(job_id, path)

            with patch("backend.app.api.db.insert_job", side_effect=insert_job), patch("backend.app.api.db.get_job", side_effect=get_job):
                row = import_job_alert_email_text(AlertEmailImport(source_hint="linkedin", raw_email_text=text))
                queue = db.review_queue(path)
        self.assertEqual(row["inserted"], 1)
        self.assertEqual(queue["needs_review"][0]["source"], "LinkedIn Job Alerts Email")

    def test_email_alert_refresh_skip_does_not_fail_when_gmail_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            source = {"name": "LinkedIn Job Alerts Email", "type": "linkedin_email_alert", "url": "gmail://job-alerts/linkedin", "enabled": True, "notes": ""}
            result = collectors.refresh_jobs(path, sources_override=[source])
        self.assertEqual(result["sources_checked"], 1)
        self.assertEqual(result["email_alert_sources_checked"], 1)
        self.assertFalse(result["gmail_configured"])
        self.assertEqual(result["errors"], {})
        for field in ["alert_emails_checked", "alert_jobs_inserted", "alert_duplicates_updated", "alert_parse_errors", "gmail_errors"]:
            self.assertIn(field, result)

    def test_hosted_refresh_summary_includes_gmail_fields(self):
        result = {
            "sources_checked": 1,
            "jobs_collected": 1,
            "new_jobs_inserted": 1,
            "new_jobs_found": 1,
            "duplicates_skipped": 0,
            "duplicates_updated": 0,
            "stale_jobs": 0,
            "high_matches": 1,
            "errors": {},
            "daily_report_path": "x",
            "email_alert_sources_checked": 2,
            "alert_emails_checked": 3,
            "alert_emails_parsed": 2,
            "alert_jobs_inserted": 2,
            "alert_duplicates_updated": 1,
            "alert_parse_errors": 0,
            "gmail_errors": [],
            "gmail_configured": True,
        }
        with patch("backend.app.api.api_env", return_value="production"), patch("backend.app.api.admin_refresh_token", return_value="secret"), patch("backend.app.api.refresh_jobs", return_value=result):
            row = admin_refresh_jobs("secret")
        self.assertTrue(row["gmail_configured"])
        self.assertEqual(row["alert_emails_checked"], 3)

    def test_no_linkedin_or_indeed_fetching_in_alert_parser(self):
        with patch("urllib.request.urlopen") as opener:
            parse_alert_jobs("indeed", "GIS Analyst at County, NC\nhttps://www.indeed.com/viewjob?jk=abc123")
        opener.assert_not_called()

    def test_search_profile_loading(self):
        profiles = load_search_profiles()
        self.assertIn("gis_analyst_nc", profiles)
        self.assertIn("GIS Analyst", profiles["gis_analyst_nc"]["keywords"])
        self.assertTrue(profiles["planning_gis_nc"]["include_remote"])

    def test_international_search_profiles_load(self):
        profiles = load_search_profiles()
        for name in ["international_gis", "southeast_asia_gis", "vietnam_gis", "singapore_gis", "malaysia_gis", "thailand_gis", "indonesia_gis", "philippines_gis", "remote_apac_gis"]:
            self.assertIn(name, profiles)
            self.assertFalse(profiles[name]["enabled"])
            self.assertEqual(profiles[name]["preferred_language"], "English")
            self.assertIn("GIS Analyst", profiles[name]["role_keywords"])

    def test_country_region_fields_serialize(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            job_id, _ = db.insert_job({
                **self.job,
                "source_url": "https://example.com/sea-serialize",
                "country": "Vietnam",
                "region": "southeast_asia",
                "international_region": "Southeast Asia",
                "language_requirement": "English",
                "timezone_note": "ICT / APAC overlap",
            }, path)
            row = db.get_job(job_id, path)
        self.assertEqual(row["country"], "Vietnam")
        self.assertEqual(row["international_region"], "Southeast Asia")
        self.assertEqual(row["language_requirement"], "English")

    def test_international_scoring_boosts_sea_gis_role(self):
        scored = score_job({
            **self.job,
            "title": "Geospatial Analyst",
            "location": "Singapore",
            "country": "Singapore",
            "international_region": "Southeast Asia",
            "language_requirement": "English",
            "description": "GIS, QGIS, ArcGIS, geospatial dashboards, spatial analysis, Python, SQL, and smart city planning.",
            "requirements": "English professional communication and urban planning data analysis.",
        }, self.profile)
        self.assertGreaterEqual(scored["match_score"], 70)
        self.assertGreater(scored["scoring_breakdown"]["international_region_fit"], 0)
        self.assertIn("Singapore", scored["positive_matches"])

    def test_visa_citizenship_language_constraints_lower_international_score(self):
        base = {
            **self.job,
            "title": "GIS Analyst",
            "location": "Bangkok, Thailand",
            "country": "Thailand",
            "international_region": "Southeast Asia",
            "description": "GIS, ArcGIS, QGIS, spatial analysis, transportation planning, Python, SQL, and dashboards.",
        }
        open_role = score_job({**base, "requirements": "English professional communication."}, self.profile)
        constrained = score_job({**base, "requirements": "Thai citizenship required. Native Thai required. Relocation required."}, self.profile)
        self.assertLess(constrained["match_score"], open_role["match_score"])
        self.assertIn("local citizenship required", constrained["penalty_matches"])
        self.assertIn("native language only", constrained["penalty_matches"])

    def test_sea_email_alert_sources_do_not_scrape_remote_pages(self):
        source = {"name": "JobStreet JobsDB Job Alerts Email", "type": "gmail_job_alerts", "url": "gmail://job-alerts/jobstreet-jobsdb", "enabled": True, "coverage_tier": "big_board_email_alert"}
        with patch("urllib.request.urlopen") as opener:
            jobs = collectors.collect_from_source(source)
        self.assertEqual(jobs, [])
        opener.assert_not_called()

    def test_source_quality_report_runs_without_secrets(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"FAKE_SECRET_KEY": "do-not-print-me"}, clear=False):
            path = Path(tmp) / "jobs.sqlite3"
            db.insert_job({**self.job, "source": "Remotive APAC Remote", "source_url": "https://example.com/remotive-quality", "match_score": 60}, path)
            original_list_jobs = db.list_jobs
            with patch("scripts.analyze_source_quality.db.list_jobs", side_effect=lambda include_sample=False: original_list_jobs(path=path, include_sample=include_sample)), patch("scripts.analyze_source_quality.db.list_sources", return_value=[{"name": "Remotive APAC Remote", "last_status": "ok: 0 new, 1 duplicates", "errors_last_run": ""}]):
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(analyze_source_quality.main(), 0)
        text = output.getvalue()
        self.assertIn("Remotive APAC Remote", text)
        self.assertNotIn("do-not-print-me", text)

    def test_source_quality_counts_missing_jsearch_links(self):
        jobs = [
            {**self.job, "source": "JSearch GIS US", "attribution_note": "Collected through JSearch/RapidAPI broad jobs API.", "apply_url": "", "source_url": "", "match_score": 72},
            {**self.job, "source": "JSearch GIS US", "attribution_note": "Collected through JSearch/RapidAPI broad jobs API.", "apply_url": "https://example.com/apply", "source_url": "", "match_score": 60},
        ]
        sources = [{"name": "JSearch GIS US", "enabled": True, "last_status": "ok: 1 new, 1 duplicates", "jobs_found_last_run": 2, "errors_last_run": ""}]
        with patch("scripts.analyze_source_quality.db.list_jobs", return_value=jobs), patch("scripts.analyze_source_quality.db.list_sources", return_value=sources):
            row = next(item for item in analyze_source_quality.rows() if item["source"] == "JSearch GIS US")
        self.assertEqual(row["missing_links"], 1)
        self.assertEqual(row["collected_last_run"], 2)
        self.assertEqual(row["inserted_last_run"], 1)
        self.assertEqual(row["duplicates_last_run"], 1)

    def test_greenhouse_collector_normalizes_mock_response(self):
        source = {
            "name": "Example Greenhouse",
            "type": "greenhouse",
            "url": "https://boards.greenhouse.io/example",
            "board_token": "example",
            "company": "Example Co",
            "enabled": True,
        }
        data = {"jobs": [{"title": "GIS Analyst", "updated_at": "2026-06-20T12:00:00Z", "location": {"name": "Charlotte, NC"}, "absolute_url": "https://boards.greenhouse.io/example/jobs/1", "content": "<p>ArcGIS and parcels</p>"}]}
        with patch("backend.app.collectors.fetch_json", return_value=data):
            jobs = collectors.collect_greenhouse(source)
        self.assertEqual(jobs[0]["title"], "GIS Analyst")
        self.assertEqual(jobs[0]["company"], "Example Co")
        self.assertEqual(jobs[0]["source_updated_at"], "2026-06-20T12:00:00Z")
        self.assertEqual(jobs[0]["source_posted_at"], "")
        self.assertEqual(jobs[0]["freshness_confidence"], "first_seen_only")

    def test_source_include_keywords_filter_prevents_generic_jobs(self):
        jobs = [
            {"title": "Accounts Payable", "description": "Invoices", "requirements": ""},
            {"title": "GIS Analyst", "description": "ArcGIS mapping", "requirements": ""},
        ]
        filtered = collectors.filter_by_source_keywords(jobs, {"include_keywords": ["GIS", "mapping"]})
        self.assertEqual([job["title"] for job in filtered], ["GIS Analyst"])

    def test_lever_collector_normalizes_mock_response(self):
        source = {"name": "Example Lever", "type": "lever", "url": "https://jobs.lever.co/example", "site": "example", "company": "Example Co", "enabled": True}
        data = [{"text": "Spatial Analyst", "hostedUrl": "https://jobs.lever.co/example/abc", "applyUrl": "https://jobs.lever.co/example/abc/apply", "categories": {"location": "Remote", "team": "GIS"}, "descriptionPlain": "Python GIS and ArcGIS", "lists": [{"content": "Planning and parcels"}]}]
        with patch("backend.app.collectors.fetch_json", return_value=data):
            jobs = collectors.collect_lever(source)
        fresh = apply_freshness(jobs[0], checked_at="2026-06-20")
        self.assertEqual(fresh["title"], "Spatial Analyst")
        self.assertEqual(fresh["apply_url"], "https://jobs.lever.co/example/abc/apply")
        self.assertEqual(fresh["source_posted_at"], "")
        self.assertEqual(fresh["freshness_confidence"], "first_seen_only")
        self.assertEqual(fresh["first_seen_at"], "2026-06-20")

    def test_source_status_endpoint_includes_freshness_support_fields(self):
        rows = sources_endpoint()
        self.assertTrue(rows)
        for field in ["supports_posted_date", "supports_updated_date", "supports_close_date", "freshness_confidence_default", "last_checked_at", "last_error", "strong_matches_by_region"]:
            self.assertIn(field, rows[0])

    def test_sources_endpoint_returns_config_when_db_status_unavailable(self):
        with patch("backend.app.api.db.list_sources", side_effect=RuntimeError("db unavailable")):
            rows = sources_endpoint()
        self.assertTrue(rows)
        self.assertIn("name", rows[0])
        self.assertIn("supports_posted_date", rows[0])

    def test_validate_disabled_source_does_not_call_network(self):
        source = {"name": "Disabled Greenhouse", "type": "greenhouse", "url": "https://boards.greenhouse.io/example", "enabled": False}
        with patch("backend.app.source_validation.collect_from_source") as collector:
            row = validate_source(source)
        collector.assert_not_called()
        self.assertEqual(row["validation_status"], "disabled")

    def test_validation_redacts_secret_values(self):
        source = {"name": "Bad Lever", "type": "lever", "url": "https://jobs.lever.co/example", "site": "example", "enabled": True}
        with patch.dict(os.environ, {"USAJOBS_AUTHORIZATION_KEY": "super-secret-token"}, clear=False):
            with patch("backend.app.source_validation.collect_from_source", side_effect=RuntimeError("failed super-secret-token")):
                row = validate_source(source)
        self.assertEqual(row["validation_status"], "error")
        self.assertNotIn("super-secret-token", json.dumps(row))

    def test_invalid_greenhouse_token_returns_error_not_crash(self):
        source = {"name": "Bad Greenhouse", "type": "greenhouse", "url": "https://boards.greenhouse.io/bad", "board_token": "bad", "enabled": True}
        with patch("backend.app.source_validation.collect_from_source", side_effect=RuntimeError("404 not found")):
            row = validate_source(source)
        self.assertEqual(row["validation_status"], "error")
        self.assertIn("404", row["last_error"])

    def test_invalid_lever_site_returns_error_not_crash(self):
        source = {"name": "Bad Lever", "type": "lever", "url": "https://jobs.lever.co/bad", "site": "bad", "enabled": True}
        with patch("backend.app.source_validation.collect_from_source", side_effect=RuntimeError("404 not found")):
            row = validate_source(source)
        self.assertEqual(row["validation_status"], "error")
        self.assertIn("404", row["last_error"])

    def test_enabled_safe_greenhouse_and_lever_validate_with_mocked_collectors(self):
        greenhouse = {"name": "Good Greenhouse", "type": "greenhouse", "url": "https://boards.greenhouse.io/example", "board_token": "example", "enabled": True}
        lever = {"name": "Good Lever", "type": "lever", "url": "https://jobs.lever.co/example", "site": "example", "enabled": True}
        with patch("backend.app.source_validation.collect_from_source", return_value=[self.job]):
            self.assertEqual(validate_source(greenhouse)["validation_status"], "ok")
            self.assertEqual(validate_source(lever)["validation_status"], "ok")

    def test_usajobs_missing_credentials_returns_warning(self):
        source = {"name": "USAJobs API", "type": "api", "url": "https://data.usajobs.gov/api/search", "enabled": True}
        with patch.dict(os.environ, {"USAJOBS_USER_AGENT": "", "USAJOBS_AUTHORIZATION_KEY": "", "USAJOBS_API_KEY": ""}, clear=False):
            with patch("backend.app.collectors.load_backend_env"):
                row = validate_source(source)
        self.assertEqual(row["validation_status"], "warning")
        self.assertIn("credentials missing", row["last_error"].lower())

    def test_setup_usajobs_reports_missing_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_path = root / ".env"
            sources_path = root / "sources.yaml"
            sources_path.write_text("sources:\n- name: USAJobs API\n  type: api\n  url: https://data.usajobs.gov/api/search\n  enabled: false\n", encoding="utf-8")
            output = io.StringIO()
            with patch.dict(os.environ, {"USAJOBS_USER_AGENT": "", "USAJOBS_AUTHORIZATION_KEY": "", "USAJOBS_API_KEY": ""}, clear=False), redirect_stdout(output):
                code = setup_usajobs.main(env_path, sources_path)
        text = output.getvalue()
        self.assertEqual(code, 1)
        self.assertIn("Missing USAJobs credentials", text)
        self.assertIn("Do not commit backend/.env", text)

    def test_setup_usajobs_does_not_print_key(self):
        secret = "never-print-me"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_path = root / ".env"
            sources_path = root / "sources.yaml"
            env_path.write_text(f"USAJOBS_USER_AGENT=test@example.com\nUSAJOBS_AUTHORIZATION_KEY={secret}\n", encoding="utf-8")
            sources_path.write_text("sources:\n- name: USAJobs API\n  type: api\n  url: https://data.usajobs.gov/api/search\n  enabled: true\n", encoding="utf-8")
            output = io.StringIO()
            with patch("scripts.setup_usajobs.validate_source", return_value={"validation_status": "ok", "reachable_endpoint": True, "jobs_sampled": 2, "last_error": ""}):
                with redirect_stdout(output):
                    code = setup_usajobs.main(env_path, sources_path)
        text = output.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("Validation status: ok", text)
        self.assertNotIn(secret, text)

    def test_source_toggle_enables_and_disables_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sources.yaml"
            path.write_text("sources:\n- name: USAJobs API\n  type: api\n  enabled: false\n", encoding="utf-8")
            enabled = source_toggle.set_enabled("USAJobs API", True, path)
            disabled = source_toggle.set_enabled("USAJobs API", False, path)
        self.assertTrue(enabled["enabled"])
        self.assertFalse(disabled["enabled"])

    def test_source_toggle_fails_when_source_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sources.yaml"
            path.write_text("sources:\n- name: Sample GIS Jobs\n  type: manual\n  enabled: true\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                source_toggle.set_enabled("USAJobs API", True, path)

    def test_source_validation_endpoint_includes_freshness_support_fields(self):
        with patch("backend.app.api.validate_sources", return_value=[{"supports_posted_date": True, "supports_updated_date": False, "supports_close_date": True, "freshness_confidence_default": "source_posted_date", "jobs_sampled": 1}]):
            rows = validate_source_config()
        self.assertTrue(rows)
        for field in ["supports_posted_date", "supports_updated_date", "supports_close_date", "freshness_confidence_default", "jobs_sampled"]:
            self.assertIn(field, rows[0])

    def test_discover_sources_creates_reports_without_secrets(self):
        targets = [{"organization": "Example", "expected_type": "unknown", "status": "manual", "url": "https://example.com/careers", "notes": "", "priority": "High", "date_support": "First-seen only"}]
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"FAKE_SECRET_KEY": "do-not-print-me"}, clear=False):
            discovery_path = Path(tmp) / "SOURCE_DISCOVERY_REPORT.md"
            activation_path = Path(tmp) / "SOURCE_ACTIVATION_STATUS.md"
            with patch("scripts.discover_sources.DISCOVERY_REPORT_PATH", discovery_path), patch("scripts.discover_sources.ACTIVATION_STATUS_PATH", activation_path), patch("scripts.discover_sources.fetch_url", return_value=("https://example.com/careers", "do-not-print-me boards.greenhouse.io/example", "")), patch("scripts.discover_sources.source_lookup", return_value={}):
                rows = discover_sources.discover(targets)
                discover_sources.write_reports(rows)
            self.assertTrue(discovery_path.exists())
            self.assertTrue(activation_path.exists())
            text = discovery_path.read_text(encoding="utf-8") + activation_path.read_text(encoding="utf-8")
        self.assertIn("Source Discovery Report", text)
        self.assertIn("Source Activation Status", text)
        self.assertNotIn("do-not-print-me", text)

    def test_source_classification_does_not_guess_unsupported_as_safe(self):
        row = discover_sources.classify_url("https://example.com", "<a href='https://company.wd1.myworkdayjobs.com/jobs'>Jobs</a>")
        self.assertEqual(row["status"], "unsupported")
        self.assertEqual(row["type"], "unsupported/login portal")

    def test_frontend_api_local_does_not_silently_fallback_to_demo(self):
        text = Path("frontend/lib/api.ts").read_text(encoding="utf-8")
        self.assertIn("if (API_MODE === \"demo\") return demoApi", text)
        self.assertIn("API mode is enabled but NEXT_PUBLIC_API_BASE_URL is missing.", text)
        self.assertNotIn("catch {\n    return demoApi", text)

    def test_frontend_data_mode_badge_text_logic_exists(self):
        api_text = Path("frontend/lib/api.ts").read_text(encoding="utf-8")
        dashboard_text = Path("frontend/components/DashboardPage.tsx").read_text(encoding="utf-8")
        for label in ["Demo Mode", "Local Backend", "Live API"]:
            self.assertIn(label, api_text)
        self.assertIn("dataModeLabel()", dashboard_text)
        self.assertIn("Promise.allSettled", dashboard_text)
        self.assertIn("Live API connected, but no jobs returned for this filter", dashboard_text)
        self.assertIn("Hosted refresh admin-only", dashboard_text)
        self.assertIn("International sources", dashboard_text)
        self.assertIn("Southeast Asia sources", dashboard_text)
        self.assertNotIn("ADMIN_REFRESH_TOKEN", dashboard_text)

    def test_check_frontend_data_mode_does_not_expose_secrets(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"FAKE_SECRET_KEY": "do-not-print-me"}, clear=False):
            env_path = Path(tmp) / ".env.local"
            env_path.write_text("NEXT_PUBLIC_API_MODE=demo\nNEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8001\n", encoding="utf-8")
            output = io.StringIO()
            with patch("scripts.check_frontend_data_mode.fetch_json", side_effect=[{"status": "ok", "database": "connected"}, [{"source": "USAJobs API"}, {"source": "Woolpert Careers"}]]), redirect_stdout(output):
                self.assertEqual(check_frontend_data_mode.main(env_path), 0)
        text = output.getvalue()
        self.assertIn("warning: frontend is in demo mode while the backend has real jobs.", text)
        self.assertNotIn("do-not-print-me", text)

    def test_admin_refresh_hosted_script_does_not_save_or_print_token(self):
        text = Path("scripts/admin_refresh_hosted.py").read_text(encoding="utf-8")
        self.assertIn("getpass.getpass", text)
        self.assertIn("X-Admin-Refresh-Token", text)
        self.assertNotRegex(text, r"print\(.*token|write_text|open\(.*token")
        with patch("scripts.admin_refresh_hosted.getpass.getpass", return_value="secret-token"), patch("scripts.admin_refresh_hosted.admin_refresh", return_value={"sources_checked": 1, "jobs_collected": 1, "inserted": 1, "duplicates_updated": 0, "stale_jobs": 0, "strong_excellent_matches": 1, "report_generated": True, "source_errors": {}}):
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(admin_refresh_hosted.main(["--url", "https://backend.example.com"]), 0)
        self.assertNotIn("secret-token", output.getvalue())

    def test_admin_refresh_hosted_reads_ignored_token_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "admin_refresh_token.local.txt"
            path.write_text("stored-token", encoding="utf-8")
            with patch("scripts.admin_refresh_hosted.admin_refresh", return_value={"sources_checked": 1, "jobs_collected": 1, "inserted": 0, "duplicates_updated": 1, "stale_jobs": 0, "strong_excellent_matches": 1, "report_generated": True, "source_errors": {}}):
                output = io.StringIO()
                with patch("scripts.admin_refresh_hosted.TOKEN_PATH", path), redirect_stdout(output):
                    self.assertEqual(admin_refresh_hosted.main(["--url", "https://backend.example.com"]), 0)
        self.assertNotIn("stored-token", output.getvalue())

    def test_admin_refresh_hosted_falls_back_to_getpass(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing-token.txt"
            with patch("scripts.admin_refresh_hosted.getpass.getpass", return_value="prompt-token"):
                self.assertEqual(admin_refresh_hosted.load_token(missing), "prompt-token")

    def test_setup_hosted_refresh_script_is_safe_static(self):
        text = Path("scripts/setup_hosted_refresh.ps1").read_text(encoding="utf-8")
        self.assertIn("srv-d90stu3sq97s739mpta0", text)
        self.assertIn("Paste Render API key, then press Enter:", text)
        self.assertIn("RENDER_API_KEY", text)
        self.assertIn("ADMIN_REFRESH_TOKEN", text)
        self.assertIn("runtime\\secrets\\admin_refresh_token.local.txt", text)
        self.assertIn("RandomNumberGenerator", text)
        self.assertNotRegex(text, r"rnd_[A-Za-z0-9]|Authorization = \"Bearer [^$]|ADMIN_REFRESH_TOKEN\\s*=\\s*['\"][A-Za-z0-9_-]{20,}")

    def test_hosted_refresh_workflow_is_scheduled_and_secret_safe(self):
        text = Path(".github/workflows/hosted-refresh.yml").read_text(encoding="utf-8")
        self.assertIn("cron: \"0 12 * * *\"", text)
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("secrets.ADMIN_REFRESH_TOKEN", text)
        self.assertIn("/admin/refresh-jobs", text)
        self.assertIn("X-Admin-Refresh-Token", text)
        self.assertNotRegex(text, r"rnd_[A-Za-z0-9]|vcp_[A-Za-z0-9]|ADMIN_REFRESH_TOKEN:\\s*[A-Za-z0-9_-]{20,}")

    def test_setup_github_refresh_secret_script_is_safe_static(self):
        text = Path("scripts/setup_github_refresh_secret.ps1").read_text(encoding="utf-8")
        self.assertIn("gh secret set", text)
        self.assertIn("--body-file -", text)
        self.assertIn("runtime\\secrets\\admin_refresh_token.local.txt", text)
        self.assertIn("Read-Host \"Paste GitHub token, then press Enter\" -AsSecureString", text)
        self.assertNotRegex(text, r"ghp_[A-Za-z0-9]|github_pat_[A-Za-z0-9_]|ADMIN_REFRESH_TOKEN\\s*=\\s*['\"][A-Za-z0-9_-]{20,}")
        self.assertNotRegex(text, r"(Set-Content|Out-File|Add-Content).*(AdminToken|GitHub token|ADMIN_REFRESH_TOKEN)")

    def test_runtime_secrets_remain_ignored(self):
        patterns = Path(".gitignore").read_text(encoding="utf-8")
        self.assertIn("runtime/secrets/", patterns)
        self.assertIn("runtime/secrets/**", patterns)

    def test_scheduled_refresh_payload_dry_run_prints_safe_summary(self):
        responses = {
            "/deployment/status": {"api_env": "production", "database_runtime_type": "postgres", "production_ready": True, "job_count": 62, "real_sources_enabled": 2},
            "/reports/latest": {"exists": True, "date": "2026-06-29"},
        }
        output = io.StringIO()
        with patch.dict(os.environ, {"FAKE_SECRET_KEY": "do-not-print-me"}, clear=False), patch("scripts.test_scheduled_refresh_payload.fetch_json", side_effect=lambda _base, path: responses[path]), redirect_stdout(output):
            self.assertEqual(test_scheduled_refresh_payload.main(["--url", "https://backend.example.com"]), 0)
        text = output.getvalue()
        self.assertIn("POST /admin/refresh-jobs", text)
        self.assertIn("secrets.ADMIN_REFRESH_TOKEN", text)
        self.assertIn("job_count: 62", text)
        self.assertNotIn("do-not-print-me", text)

    def test_check_hosted_backend_reports_readiness_without_secrets(self):
        responses = {
            "/health": {"status": "ok"},
            "/deployment/status": {"api_env": "production", "database_runtime_type": "postgres", "database_url_present": True, "database_url_scheme": "postgresql+psycopg", "configured_database_type": "postgres", "real_sources_enabled": 2, "production_blockers": []},
            "/jobs": [{"source": "USAJobs API"}, {"source": "Woolpert Careers"}],
            "/review/queue": {"fresh_high_match": [{"id": 1}], "needs_review": []},
            "/application/board": {"ready_to_apply": [], "applied": [{"id": 2}]},
        }
        output = io.StringIO()
        with patch.dict(os.environ, {"FAKE_SECRET_KEY": "do-not-print-me"}, clear=False), patch("scripts.check_hosted_backend.fetch_json", side_effect=lambda _base, path: responses[path]), redirect_stdout(output):
            self.assertEqual(check_hosted_backend.main(["--url", "https://backend.example.com"]), 0)
        text = output.getvalue()
        self.assertIn("database_runtime_type: postgres", text)
        self.assertIn("production blockers: none", text)
        self.assertIn("production ready: yes", text)
        self.assertNotIn("do-not-print-me", text)

    def test_live_frontend_data_diagnostic_runs_without_secrets(self):
        responses = {
            "/deployment/status": {"job_count": 2, "source_count": 2},
            "/jobs": [{"source": "USAJobs API"}, {"source": "Woolpert Careers"}],
            "/sources": [{"name": "USAJobs API"}, {"name": "Woolpert Careers"}],
            "/stats/overview": {"total": 2},
            "/review/queue": {"needs_review": [{"id": 1}], "fresh_high_match": [{"id": 2}]},
            "/application/board": {"ready_to_apply": [], "applied": []},
            "/reports/latest": {"exists": False, "summary": {}},
        }
        output = io.StringIO()
        with patch.dict(os.environ, {"FAKE_SECRET_KEY": "do-not-print-me"}, clear=False), patch("scripts.check_live_frontend_data.fetch_json", side_effect=lambda _base, path: responses[path]), redirect_stdout(output):
            self.assertEqual(check_live_frontend_data.main(["--url", "https://backend.example.com"]), 0)
        text = output.getvalue()
        self.assertIn("jobs: 2", text)
        self.assertIn("sources: 2", text)
        self.assertNotIn("do-not-print-me", text)

    def test_vercel_frontend_fetch_diagnostic_checks_browser_origin(self):
        api_url = "https://backend.example.com"
        rows = {
            "/health": {"status": "ok"},
            "/deployment/status": {"job_count": 2, "source_count": 1},
            "/jobs": [{"id": 1}, {"id": 2}],
            "/sources": [{"name": "USAJobs API"}],
            "/stats/overview": {"total": 2},
            "/review/queue": {"needs_review": [{"id": 1}], "fresh_high_match": []},
            "/reports/latest": {"exists": True, "summary": {"new_jobs_inserted": 1}},
        }

        def fake_text(url):
            if url.endswith(".js"):
                return api_url
            return '<html><script src="/_next/app.js"></script>No jobs in this view yet.</html>'

        def fake_json(url, origin):
            path = "/" + url.split("/", 3)[3]
            return rows[path], {"access-control-allow-origin": origin}, 200

        def fake_preflight(_url, origin):
            return {"access-control-allow-origin": origin}, 200

        output = io.StringIO()
        with patch.dict(os.environ, {"FAKE_SECRET_KEY": "do-not-print-me"}, clear=False), patch("scripts.check_vercel_frontend_fetch.fetch_text", side_effect=fake_text), patch("scripts.check_vercel_frontend_fetch.fetch_json", side_effect=fake_json), patch("scripts.check_vercel_frontend_fetch.preflight", side_effect=fake_preflight), redirect_stdout(output):
            self.assertEqual(check_vercel_frontend_fetch.main(["--site", "https://site.example.com", "--api", api_url]), 0)
        text = output.getvalue()
        self.assertIn("/jobs length: 2", text)
        self.assertIn("/sources length: 1", text)
        self.assertIn("bundle has api url: True", text)
        self.assertNotIn("do-not-print-me", text)

    def test_dashboard_live_api_initial_state_says_loading_not_zero(self):
        text = Path("frontend/components/DashboardPage.tsx").read_text(encoding="utf-8")
        self.assertIn("Loading live jobs...", text)
        self.assertIn("Loading sources", text)

    def test_connect_render_backend_script_is_safe_static(self):
        text = Path("scripts/connect_render_backend.ps1").read_text(encoding="utf-8")
        self.assertIn("srv-d90stu3sq97s739mpta0", text)
        self.assertIn("https://gisjobportal.onrender.com", text)
        self.assertNotIn("srv-d90slrjeo5us73caqu40", text)
        self.assertIn("Read-Host \"Paste Render API key, then press Enter:\" -AsSecureString", text)
        self.assertIn("Authorization = \"Bearer $ApiKey\"", text)
        self.assertNotRegex(text, r"rnd_[A-Za-z0-9]|Authorization = \"Bearer [^$]")
        self.assertNotRegex(text, r"(Set-Content|Out-File|Add-Content).*(ApiKey|SecureKey|Render API key)")

    def test_connect_vercel_live_api_script_is_safe_static(self):
        text = Path("scripts/connect_vercel_live_api.ps1").read_text(encoding="utf-8")
        self.assertIn("prj_7rRCF8pTAJBrxMQZtsjBgvNYiKGI", text)
        self.assertIn("team_NnrpDjazbXYZNE9Sqb9iTIKv", text)
        self.assertIn("https://gisjobportal.onrender.com", text)
        self.assertIn("https://api.vercel.com/v10/projects/$ProjectId/env?teamId=$TeamId", text)
        self.assertIn("upsert=true", text)
        self.assertIn("Read-Host \"Paste Vercel token, then press Enter\" -AsSecureString", text)
        self.assertIn("Authorization = \"Bearer $script:Token\"", text)
        self.assertNotIn("Invoke-VercelCli", text)
        self.assertNotIn('@("--team', text)
        self.assertNotIn('@("--scope', text)
        self.assertNotRegex(text, r"vcp_[A-Za-z0-9]|--token|Authorization = \"Bearer [^$]")
        self.assertNotRegex(text, r"(Set-Content|Out-File|Add-Content).*(Token|VERCEL_TOKEN|Vercel token)")

    def test_render_docs_do_not_contain_secret_values(self):
        combined = "\n".join(path.read_text(encoding="utf-8") for path in [Path("README.md"), *Path("docs").glob("*.md")])
        self.assertIn("connect_render_backend.ps1", combined)
        self.assertIn("connect_vercel_live_api.ps1", combined)
        self.assertIn("setup_hosted_refresh.ps1", combined)
        self.assertNotRegex(combined, r"rnd_[A-Za-z0-9]|vcp_|apiapi|sk-[A-Za-z0-9]")

    def test_check_ports_runs_without_secrets(self):
        output = io.StringIO()
        with patch.dict(os.environ, {"FAKE_SECRET_KEY": "do-not-print-me"}, clear=False), patch("scripts.check_ports.is_open", return_value=True), patch("scripts.check_ports.http_get", return_value=(True, "HTTP 200")), patch("scripts.check_ports.health", return_value=(False, "/health HTTP 404")), redirect_stdout(output):
            self.assertEqual(check_ports.main(), 0)
        text = output.getvalue()
        self.assertIn("preferred backend port: 8001", text)
        self.assertIn("warning: port 8000 is occupied", text)
        self.assertNotIn("do-not-print-me", text)

    def test_frontend_env_local_remains_ignored(self):
        patterns = Path(".gitignore").read_text(encoding="utf-8")
        self.assertIn("frontend/.env.local", patterns)

    def test_readme_documents_8001_local_backend_mode(self):
        text = Path("README.md").read_text(encoding="utf-8")
        self.assertIn("Local Real Data Mode", text)
        self.assertIn("NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8001", text)
        self.assertIn("NEXT_PUBLIC_API_MODE=api", text)

    def test_launcher_script_does_not_contain_secrets(self):
        text = Path("scripts/start_local_dev.ps1").read_text(encoding="utf-8")
        self.assertIn("NEXT_PUBLIC_API_MODE=api", text)
        self.assertNotRegex(text, r"vcp_|USAJOBS_AUTHORIZATION_KEY=|OPENROUTER_API_KEY=")

    def test_procfile_has_backend_start_command(self):
        text = Path("Procfile").read_text(encoding="utf-8")
        self.assertIn("uvicorn backend.app.api:app", text)
        self.assertIn("--host 0.0.0.0", text)
        self.assertIn("--port $PORT", text)

    def test_validate_target_sources_skips_disabled_sources(self):
        enabled = {"name": "Enabled Manual", "type": "manual", "url": "data/sample_jobs.json", "enabled": True}
        disabled = {"name": "Disabled Lever", "type": "lever", "url": "https://jobs.lever.co/example", "enabled": False}
        with patch("scripts.validate_target_sources.load_sources", return_value=[enabled, disabled]):
            self.assertEqual([source["name"] for source in validate_target_sources.target_sources()], ["Enabled Manual"])

    def test_usajobs_collector_normalizes_sample_response(self):
        source = {"name": "USAJobs API", "type": "api", "url": "https://data.usajobs.gov/api/search", "enabled": True}
        item = {
            "MatchedObjectDescriptor": {
                "PositionTitle": "Geospatial Analyst",
                "OrganizationName": "U.S. Geological Survey",
                "PositionLocationDisplay": "Raleigh, North Carolina",
                "PositionURI": "https://www.usajobs.gov/job/123",
                "ApplyURI": ["https://www.usajobs.gov/apply/123"],
                "QualificationSummary": "GIS, Python, and spatial analysis experience.",
                "PublicationStartDate": "2026-06-20",
                "ApplicationCloseDate": "2026-07-01",
                "PositionRemuneration": [{"MinimumRange": "62000", "MaximumRange": "82000"}],
                "UserArea": {
                    "Details": {
                        "JobSummary": "Support geospatial data workflows.",
                        "MajorDuties": "Maintain GIS layers and web maps.",
                        "Requirements": "Public trust background check.",
                    }
                },
            }
        }
        job = collectors.normalize_usajobs_item(item, source)
        self.assertEqual(job["title"], "Geospatial Analyst")
        self.assertEqual(job["company"], "U.S. Geological Survey")
        self.assertEqual(job["apply_url"], "https://www.usajobs.gov/apply/123")
        self.assertEqual(job["salary_min"], 62000)
        self.assertEqual(job["source_posted_at"], "2026-06-20")
        self.assertEqual(job["source_closes_at"], "2026-07-01")
        self.assertIn("spatial analysis", job["requirements"])

    def test_usajobs_collector_handles_list_text_fields(self):
        source = {"name": "USAJobs API", "type": "api", "url": "https://data.usajobs.gov/api/search", "enabled": True}
        item = {
            "MatchedObjectDescriptor": {
                "PositionTitle": "GIS Technician",
                "OrganizationName": "Federal Agency",
                "PositionLocationDisplay": "Charlotte, North Carolina",
                "PositionURI": "https://www.usajobs.gov/job/456",
                "ApplyURI": ["https://www.usajobs.gov/apply/456"],
                "QualificationSummary": "GIS data maintenance.",
                "UserArea": {"Details": {"MajorDuties": ["Maintain parcels.", "Publish web maps."], "Requirements": ["ArcGIS Pro"], "Education": ["GIS coursework"]}},
            }
        }
        job = collectors.normalize_usajobs_item(item, source)
        self.assertIn("Maintain parcels", job["description"])
        self.assertIn("ArcGIS Pro", job["requirements"])
        self.assertIn("GIS coursework", job["requirements"])

    def test_usajobs_query_defaults_to_recent_jobs(self):
        source = {"name": "USAJobs API", "type": "api", "url": "https://data.usajobs.gov/api/search", "enabled": True}
        with patch.dict(os.environ, {"USAJOBS_USER_AGENT": "test@example.com", "USAJOBS_API_KEY": "key"}, clear=False):
            with patch("backend.app.collectors.load_backend_env"), patch("urllib.request.urlopen") as opener:
                opener.return_value.__enter__.return_value.read.return_value = b'{"SearchResult":{"SearchResultItems":[]}}'
                collectors.fetch_usajobs("GIS Analyst", source)
        self.assertIn("DatePosted=30", opener.call_args.args[0].full_url)

    def test_disabled_sources_are_skipped_by_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            result = collectors.refresh_jobs(
                path,
                sources_override=[
                    {"name": "Disabled Manual", "type": "manual", "url": "data/sample_jobs.json", "enabled": False, "notes": ""}
                ],
            )
        self.assertEqual(result["sources_checked"], 0)
        self.assertEqual(result["sources_skipped"], 1)
        self.assertEqual(result["jobs_collected"], 0)

    def test_collector_errors_do_not_crash_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            source = {"name": "Broken API", "type": "api", "url": "https://example.com", "enabled": True, "notes": ""}
            with patch("backend.app.collectors.collect_from_source", side_effect=RuntimeError("boom")):
                result = collectors.refresh_jobs(path, sources_override=[source])
        self.assertEqual(result["sources_checked"], 1)
        self.assertEqual(result["jobs_collected"], 0)
        self.assertEqual(result["errors"], {"Broken API": "boom"})

    def test_first_seen_stale_closed_and_active_filters(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            stale_job = {**self.job, "source_url": "https://example.com/stale", "date_posted": "2000-01-01"}
            closed_job = {**self.job, "source_url": "https://example.com/closed", "source_closes_at": "2000-01-02"}
            stale_id, _ = db.insert_job(stale_job, path)
            closed_id, _ = db.insert_job(closed_job, path)
            stale = db.get_job(stale_id, path)
            active_ids = {job["id"] for job in db.list_jobs(path=path, active_only=True)}
        self.assertTrue(stale["first_seen_at"])
        self.assertTrue(stale["is_stale"])
        self.assertNotIn(closed_id, active_ids)

    def test_review_queue_groups_high_match_fresh_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            job_id, _ = db.insert_job({**self.job, "source_url": "https://example.com/review-high", "date_posted": db.now_iso(), "match_score": 82}, path)
            queue = db.review_queue(path)
        self.assertIn(job_id, {job["id"] for job in queue["fresh_high_match"]})

    def test_closing_soon_calculation_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            job_id, _ = db.insert_job({**self.job, "source_url": "https://example.com/closing-soon", "source_closes_at": db.now_iso()}, path)
            job = db.get_job(job_id, path)
            queue = db.review_queue(path)
        self.assertEqual(job["close_days_remaining"], 0)
        self.assertIn(job_id, {item["id"] for item in queue["closing_soon"]})

    def test_closed_jobs_do_not_appear_as_active_high_priority(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            job_id, _ = db.insert_job({**self.job, "source_url": "https://example.com/closed-high", "source_closes_at": "2000-01-01", "match_score": 95}, path)
            active_ids = {job["id"] for job in db.list_jobs(path=path, active_only=True)}
            queue_ids = {job["id"] for group in db.review_queue(path).values() for job in group}
        self.assertNotIn(job_id, active_ids)
        self.assertNotIn(job_id, queue_ids)

    def test_fresh_strong_jobs_rank_above_weak_closing_soon_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            strong_id, _ = db.insert_job({**self.job, "source_url": "https://example.com/strong-fresh", "date_posted": db.now_iso(), "match_score": 78}, path)
            weak_id, _ = db.insert_job({**self.job, "title": "Weak Closing Job", "source_url": "https://example.com/weak-closing", "source_closes_at": db.now_iso(), "match_score": 42}, path)
            ordered = [job["id"] for job in db.review_queue(path)["needs_review"]]
        self.assertLess(ordered.index(strong_id), ordered.index(weak_id))

    def test_review_queue_hides_stale_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            job_id, _ = db.insert_job({**self.job, "source_url": "https://example.com/stale-review", "date_posted": "2000-01-01", "match_score": 90}, path)
            hidden = db.review_queue(path)
            visible = db.review_queue(path, include_stale=True)
        self.assertNotIn(job_id, {job["id"] for job in hidden["needs_review"]})
        self.assertIn(job_id, {job["id"] for job in visible["needs_review"]})

    def test_production_live_views_exclude_sample_jobs_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            db.insert_job({**self.job, "source": "USAJobs API", "source_url": "https://example.com/real-live", "match_score": 60, "date_posted": db.now_iso()}, path)
            db.insert_job({**self.job, "source": db.SAMPLE_JOB_SOURCE, "source_url": "https://example.com/sample-live", "match_score": 95, "status": "ready_to_apply", "date_posted": db.now_iso()}, path)
            original_list_jobs = db.list_jobs

            def temp_list_jobs(status=None, path_arg=None, active_only=False, include_sample=True, **_kwargs):
                return original_list_jobs(status=status, path=path_arg or path, active_only=active_only, include_sample=include_sample)

            with patch("backend.app.api.ensure_seeded"), patch("backend.app.api.api_env", return_value="production"), patch("backend.app.api.db.list_jobs", side_effect=temp_list_jobs):
                rows = jobs_endpoint()
                rows_with_sample = jobs_endpoint(include_sample=True)
                stats = overview_endpoint()
                queue = review_queue_endpoint()
                board = application_board_endpoint()

        self.assertEqual([job["source"] for job in rows], ["USAJobs API"])
        self.assertEqual({job["source"] for job in rows_with_sample}, {"USAJobs API", db.SAMPLE_JOB_SOURCE})
        self.assertEqual(stats["total"], 1)
        self.assertEqual(stats["high_matches"], 0)
        self.assertNotIn(db.SAMPLE_JOB_SOURCE, {job["source"] for group in queue.values() for job in group})
        self.assertFalse(board["ready_to_apply"])

    def test_local_api_includes_sample_jobs_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            db.insert_job({**self.job, "source": "USAJobs API", "source_url": "https://example.com/local-real"}, path)
            db.insert_job({**self.job, "source": db.SAMPLE_JOB_SOURCE, "source_url": "https://example.com/local-sample"}, path)
            original_list_jobs = db.list_jobs

            def temp_list_jobs(status=None, path_arg=None, active_only=False, include_sample=True, **_kwargs):
                return original_list_jobs(status=status, path=path_arg or path, active_only=active_only, include_sample=include_sample)

            with patch("backend.app.api.ensure_seeded"), patch("backend.app.api.api_env", return_value="local"), patch("backend.app.api.db.list_jobs", side_effect=temp_list_jobs):
                rows = jobs_endpoint()

        self.assertEqual({job["source"] for job in rows}, {"USAJobs API", db.SAMPLE_JOB_SOURCE})

    def test_demo_mode_and_sample_badge_still_exist(self):
        api_text = Path("frontend/lib/api.ts").read_text(encoding="utf-8")
        dashboard_text = Path("frontend/components/DashboardPage.tsx").read_text(encoding="utf-8")
        detail_text = Path("frontend/components/JobDetail.tsx").read_text(encoding="utf-8")
        self.assertIn('if (API_MODE === "demo") return demoApi', api_text)
        self.assertIn("Demo sample job — not a live posting", dashboard_text)
        self.assertIn("Demo sample job — not a live posting", detail_text)

        for text in (dashboard_text, detail_text):
            self.assertIn("No apply link available from source.", text)
            self.assertIn("JSearch / Google Jobs result", text)
            self.assertIn("Original source:", text)
        self.assertIn("Apply link available", dashboard_text)
        self.assertIn("Source-only link", dashboard_text)

    def test_apply_today_defaults_to_five_and_excludes_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            for index in range(7):
                db.insert_job({**self.job, "title": f"GIS Analyst {index}", "source": "USAJobs API", "source_url": f"https://example.com/apply-today-{index}", "match_score": 80 - index, "date_posted": db.now_iso()}, path)
            db.insert_job({**self.job, "title": "Sample Top Job", "source": db.SAMPLE_JOB_SOURCE, "source_url": "https://example.com/apply-today-sample", "match_score": 99, "date_posted": db.now_iso()}, path)
            rows = db.apply_today(path=path, include_sample=False)
            rows_with_sample = db.apply_today(path=path, include_sample=True)

        self.assertEqual(len(rows), 5)
        self.assertNotIn(db.SAMPLE_JOB_SOURCE, {job["source"] for job in rows})
        self.assertIn(db.SAMPLE_JOB_SOURCE, {job["source"] for job in rows_with_sample})

    def test_apply_today_excludes_terminal_statuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            db.insert_job({**self.job, "title": "Keep Me", "source_url": "https://example.com/keep-apply", "match_score": 82, "date_posted": db.now_iso()}, path)
            for status in ["applied", "skipped", "rejected"]:
                db.insert_job({**self.job, "title": f"Drop {status}", "source_url": f"https://example.com/drop-{status}", "status": status, "match_score": 99, "date_posted": db.now_iso()}, path)
            db.insert_job({**self.job, "title": "Drop Closed", "source_url": "https://example.com/drop-closed", "outcome_status": "closed", "match_score": 99, "date_posted": db.now_iso()}, path)
            rows = db.apply_today(path=path)

        self.assertEqual([job["title"] for job in rows], ["Keep Me"])

    def test_apply_today_ranking_prefers_strong_fresh_over_weak_closing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            strong_id, _ = db.insert_job({**self.job, "title": "Strong Fresh", "source_url": "https://example.com/strong-fresh-apply", "match_score": 76, "score_band": "strong fit", "date_posted": db.now_iso()}, path)
            weak_id, _ = db.insert_job({**self.job, "title": "Weak Closing", "source_url": "https://example.com/weak-closing-apply", "match_score": 42, "score_band": "weak/maybe", "source_closes_at": db.now_iso(), "date_posted": db.now_iso()}, path)
            ordered = [job["id"] for job in db.apply_today(path=path)]

        self.assertIn(strong_id, ordered)
        self.assertNotIn(weak_id, ordered)

    def test_apply_today_excludes_weak_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            db.insert_job({**self.job, "title": "Possible Job", "source_url": "https://example.com/possible-apply", "match_score": 55, "date_posted": db.now_iso()}, path)
            db.insert_job({**self.job, "title": "Weak Job", "source_url": "https://example.com/weak-apply", "match_score": 54, "date_posted": db.now_iso()}, path)
            rows = db.apply_today(path=path)

        self.assertEqual([job["title"] for job in rows], ["Possible Job"])

    def test_apply_today_excludes_low_fit_broad_api_noise(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            db.insert_job({**self.job, "title": "Good Real Job", "source": "USAJobs API", "source_url": "https://example.com/good-real", "match_score": 72, "date_posted": db.now_iso()}, path)
            db.insert_job({**self.job, "title": "Broad Noise", "source": "Adzuna Jobs API", "source_url": "https://example.com/broad-noise", "match_score": 25, "date_posted": db.now_iso(), "attribution_note": "Collected through Adzuna broad jobs API."}, path)
            rows = db.apply_today(path=path)

        self.assertEqual([job["title"] for job in rows], ["Good Real Job"])

    def test_apply_today_includes_high_scoring_jsearch_with_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            db.insert_job({**self.job, "title": "JSearch Strong", "source": "JSearch GIS US", "apply_url": "https://example.com/jsearch-apply", "source_url": "https://example.com/jsearch-source", "match_score": 88, "date_posted": db.now_iso(), "attribution_note": "Collected through JSearch/RapidAPI broad jobs API."}, path)
            rows = db.apply_today(path=path)

        self.assertEqual([job["title"] for job in rows], ["JSearch Strong"])

    def test_apply_today_excludes_jsearch_without_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            db.insert_job({**self.job, "title": "Good Real Job", "source": "Woolpert Careers", "source_url": "https://example.com/good-real-linked", "match_score": 72, "date_posted": db.now_iso()}, path)
            db.insert_job({**self.job, "title": "JSearch Missing Link", "source": "JSearch GIS US", "apply_url": "", "source_url": "", "match_score": 99, "date_posted": db.now_iso(), "attribution_note": "Collected through JSearch/RapidAPI broad jobs API."}, path)
            rows = db.apply_today(path=path)

        self.assertEqual([job["title"] for job in rows], ["Good Real Job"])

    def test_apply_today_excludes_low_fit_international_broad_api_noise(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            db.insert_job({**self.job, "title": "Strong GIS Job", "source": "Woolpert Careers", "source_url": "https://example.com/strong-sea-real", "match_score": 82, "date_posted": db.now_iso()}, path)
            db.insert_job({
                **self.job,
                "title": "SEA Broad Noise",
                "source": "JSearch Southeast Asia GIS",
                "source_url": "https://example.com/sea-broad-noise",
                "location": "Singapore",
                "country": "Singapore",
                "international_region": "Southeast Asia",
                "match_score": 30,
                "date_posted": db.now_iso(),
                "attribution_note": "Collected through JSearch/RapidAPI broad jobs API.",
            }, path)
            rows = db.apply_today(path=path)

        self.assertEqual([job["title"] for job in rows], ["Strong GIS Job"])

    def test_apply_today_closing_soon_breaks_similar_score_tie(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            later_id, _ = db.insert_job({**self.job, "title": "Later Strong", "source_url": "https://example.com/later-strong", "match_score": 78, "score_band": "strong fit", "date_posted": db.now_iso()}, path)
            soon_id, _ = db.insert_job({**self.job, "title": "Soon Strong", "source_url": "https://example.com/soon-strong", "match_score": 78, "score_band": "strong fit", "source_closes_at": db.now_iso(), "date_posted": db.now_iso()}, path)
            ordered = [job["id"] for job in db.apply_today(path=path)]

        self.assertLess(ordered.index(soon_id), ordered.index(later_id))

    def test_apply_today_endpoint_uses_production_sample_filter(self):
        with patch("backend.app.api.ensure_seeded"), patch("backend.app.api.api_env", return_value="production"), patch("backend.app.api.db.apply_today", return_value=[]) as mocked:
            apply_today_endpoint()
        self.assertFalse(mocked.call_args.kwargs["include_sample"])

    def test_apply_today_frontend_route_exists(self):
        text = Path("frontend/components/DashboardPage.tsx").read_text(encoding="utf-8")
        self.assertIn("Apply Today", text)
        self.assertIn('/review/apply-today', text)
        self.assertTrue(Path("frontend/app/apply-today/page.tsx").exists())

    def test_review_update_does_not_change_application_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            job_id, _ = db.insert_job({**self.job, "source_url": "https://example.com/review-status", "status": "saved"}, path)
            updated = db.update_job_review(job_id, {"review_status": "interested", "priority_bucket": "high"}, path)
        self.assertEqual(updated["status"], "saved")
        self.assertEqual(updated["review_status"], "interested")
        self.assertEqual(updated["priority_bucket"], "high")
        self.assertTrue(updated["reviewed_at"])

    def test_refresh_summary_includes_review_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            jobs_path = Path(tmp) / "jobs.json"
            jobs_path.write_text(json.dumps([{**self.job, "source_url": "https://example.com/review-refresh", "date_posted": db.now_iso()}]), encoding="utf-8")
            result = collectors.refresh_jobs(path, sources_override=[{"name": "Temp Review Jobs", "type": "manual", "url": str(jobs_path), "enabled": True, "notes": ""}])
        for field in ["unreviewed_jobs", "high_match_unreviewed_jobs", "packets_ready", "applied_followups_needed"]:
            self.assertIn(field, result)
        self.assertGreaterEqual(result["unreviewed_jobs"], 1)

    def test_daily_report_file_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp) / "reports"
            result = {"sources_checked": 1, "jobs_collected": 1, "new_jobs_inserted": 1, "duplicates_updated": 0, "unreviewed_jobs": 1, "high_match_unreviewed_jobs": 1, "closing_soon_jobs": 1, "fresh_jobs": 1, "stale_jobs": 0, "packets_ready": 0, "applied_followups_needed": 0, "errors": {}}
            job = {**self.job, "match_score": 82, "source_posted_at": db.now_iso(), "source_closes_at": db.now_iso(), "close_days_remaining": 0, "review_status": "unreviewed"}
            path = reports.write_daily_report(result, [job], report_dir)
            text = path.read_text(encoding="utf-8")
            self.assertIn("Daily Review Digest", text)
            self.assertIn("GIS Analyst", text)
            self.assertIn("Closing in 0 days", text)

    def test_latest_report_endpoint_empty_state(self):
        with patch("backend.app.api.latest_daily_report", return_value={"exists": False, "date": "", "text": "No daily review report has been generated yet.", "summary": {}}):
            row = latest_report_endpoint()
        self.assertFalse(row["exists"])
        self.assertIn("No daily review report", row["text"])

    def test_latest_report_endpoint_returns_report(self):
        with patch("backend.app.api.latest_daily_report", return_value={"exists": True, "date": "2026-06-27", "text": "# Report", "summary": {"new_jobs_inserted": 2}}):
            row = latest_report_endpoint()
        self.assertTrue(row["exists"])
        self.assertEqual(row["summary"]["new_jobs_inserted"], 2)

    def test_daily_report_db_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            db.save_daily_report("2026-06-29", "2026-06-29T08:00:00Z", "test", {"new_jobs_inserted": 3}, "# Hosted Report", path)
            row = db.latest_daily_report(path)
        self.assertTrue(row["exists"])
        self.assertEqual(row["date"], "2026-06-29")
        self.assertEqual(row["summary"]["new_jobs_inserted"], 3)
        self.assertIn("Hosted Report", row["text"])

    def test_latest_report_uses_db_report_for_postgres(self):
        with patch("backend.app.paths.database_runtime_type", return_value="postgres"), patch("backend.app.db.latest_daily_report", return_value={"exists": True, "date": "2026-06-29", "text": "# DB Report", "summary": {}}):
            row = reports.latest_report()
        self.assertTrue(row["exists"])
        self.assertIn("DB Report", row["text"])

    def test_hosted_empty_report_state_is_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            row = db.latest_daily_report(Path(tmp) / "jobs.sqlite3")
        self.assertFalse(row["exists"])
        self.assertIn("No hosted report", row["text"])

    def test_report_does_not_contain_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            secret = "redacted-value"
            with patch.dict(os.environ, {"USAJOBS_AUTHORIZATION_KEY": secret}, clear=False):
                path = reports.write_daily_report({"errors": {"USAJobs": f"failed {secret}"}}, [], Path(tmp))
                self.assertNotIn(secret, path.read_text(encoding="utf-8"))

    def test_top_recommended_jobs_sort_by_closing_match_and_freshness(self):
        rows = [
            {**self.job, "title": "High Match", "match_score": 95, "posting_age_days": 1, "review_status": "unreviewed"},
            {**self.job, "title": "Closing Soon", "match_score": 60, "posting_age_days": 8, "close_days_remaining": 1, "review_status": "unreviewed"},
            {**self.job, "title": "Fresh Medium", "match_score": 70, "posting_age_days": 0, "review_status": "unreviewed"},
        ]
        ordered = reports.top_recommended_jobs(rows)
        self.assertEqual([job["title"] for job in ordered], ["High Match", "Fresh Medium", "Closing Soon"])

    def test_analyze_job_matches_runs_without_secrets(self):
        rows = [{**self.job, **score_job(self.job, self.profile), "id": 1, "source": "USAJobs API", "status": "new", "is_stale": False, "is_closed_or_missing": False, "posting_age_days": 1, "close_days_remaining": 3}]
        output = io.StringIO()
        with patch.dict(os.environ, {"USAJOBS_AUTHORIZATION_KEY": "do-not-print-me"}, clear=False), patch("scripts.analyze_job_matches.db.list_jobs", return_value=rows), redirect_stdout(output):
            self.assertEqual(analyze_job_matches.main(), 0)
        text = output.getvalue()
        self.assertIn("score distribution", text)
        self.assertNotIn("do-not-print-me", text)

    def test_runtime_reports_and_logs_are_ignored(self):
        patterns = Path(".gitignore").read_text(encoding="utf-8")
        self.assertIn("runtime/", patterns)
        self.assertIn("runtime/**", patterns)
        self.assertIn("runtime/secrets/", patterns)
        self.assertIn("runtime/secrets/**", patterns)

    def test_runtime_exports_are_ignored(self):
        patterns = Path(".gitignore").read_text(encoding="utf-8")
        self.assertIn("runtime/", patterns)

    def test_export_application_packet_refuses_missing_packet_clearly(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            job_id, _ = db.insert_job(self.job, path)
            with self.assertRaises(FileNotFoundError) as raised:
                export_application_packet.export_packet(job_id, path, Path(tmp) / "exports")
        self.assertIn("Generate the application packet first", str(raised.exception))

    def test_export_application_packet_excludes_secrets_and_private_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "jobs.sqlite3"
            packet_dir = root / "packet"
            packet_dir.mkdir()
            secret = "do-not-export-me"
            packet_dir.joinpath("cover_letter.md").write_text(
                rf"Hello {secret} C:\Dev\GisJobPortal\private\resume\resume_extracted.md",
                encoding="utf-8",
            )
            job_id, _ = db.insert_job({**self.job, "source_url": "https://example.com/export"}, db_path)
            db.update_job_fields(job_id, {"application_packet_dir": str(packet_dir), "document_checklist": {"transcript_required": False}}, db_path)
            with patch.dict(os.environ, {"FAKE_SECRET_KEY": secret}, clear=False):
                exported = export_application_packet.export_packet(job_id, db_path, root / "exports")
            combined = "\n".join(path.read_text(encoding="utf-8") for path in exported.glob("*.md"))
            names = {path.name for path in exported.glob("*.md")}
            self.assertIn("submission_checklist.md", names)
            self.assertIn("job_summary.md", names)
            self.assertIn("Source URL: https://example.com/export", exported.joinpath("job_summary.md").read_text(encoding="utf-8"))
            self.assertNotIn(secret, combined)
            self.assertNotIn(r"C:\Dev\GisJobPortal\private", combined)

    def test_export_application_packet_warns_when_link_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "jobs.sqlite3"
            packet_dir = root / "packet"
            packet_dir.mkdir()
            packet_dir.joinpath("cover_letter.md").write_text("hello", encoding="utf-8")
            job_id, _ = db.insert_job({**self.job, "source_url": "", "apply_url": ""}, db_path)
            db.update_job_fields(job_id, {"application_packet_dir": str(packet_dir)}, db_path)
            exported = export_application_packet.export_packet(job_id, db_path, root / "exports")
            summary = exported.joinpath("job_summary.md").read_text(encoding="utf-8")
        self.assertIn("No apply link available from source.", summary)
        self.assertIn("Link status: missing", summary)

    def test_refresh_creates_report_when_folder_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            report_dir = Path(tmp) / "missing" / "reports"
            jobs_path = Path(tmp) / "jobs.json"
            jobs_path.write_text(json.dumps([{**self.job, "source_url": "https://example.com/report-refresh", "date_posted": db.now_iso()}]), encoding="utf-8")
            result = collectors.refresh_jobs(path, sources_override=[{"name": "Temp Report Jobs", "type": "manual", "url": str(jobs_path), "enabled": True, "notes": ""}], report_dir=report_dir)
            self.assertTrue(Path(result["daily_report_path"]).exists())

    def test_freshness_score_boost_and_penalty(self):
        fresh = score_job(apply_freshness({**self.job, "date_posted": db.now_iso()}), self.profile)
        stale = score_job(apply_freshness({**self.job, "date_posted": "2000-01-01"}), self.profile)
        self.assertGreater(fresh["scoring_breakdown"]["freshness"], 0)
        self.assertLess(stale["scoring_breakdown"]["freshness"], 0)

    def test_refresh_summary_counts_fresh_stale_and_closing_soon_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            jobs_path = Path(tmp) / "jobs.json"
            jobs_path.write_text(json.dumps([
                {**self.job, "title": "Fresh GIS Analyst", "source_url": "https://example.com/fresh", "date_posted": db.now_iso(), "source_closes_at": db.now_iso()},
                {**self.job, "title": "Old GIS Analyst", "source_url": "https://example.com/old", "date_posted": "2000-01-01"},
            ]), encoding="utf-8")
            result = collectors.refresh_jobs(path, sources_override=[{"name": "Temp Jobs", "type": "manual", "url": str(jobs_path), "enabled": True, "notes": ""}])
        self.assertEqual(result["jobs_collected"], 2)
        self.assertEqual(result["new_jobs_inserted"], 2)
        self.assertGreaterEqual(result["fresh_jobs"], 1)
        self.assertGreaterEqual(result["stale_jobs"], 1)
        self.assertGreaterEqual(result["closing_soon_jobs"], 1)

    def test_refresh_marks_missing_jobs_without_reinserting(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            jobs_path = Path(tmp) / "jobs.json"
            jobs_path.write_text(json.dumps([{**self.job, "source": "Temp Jobs"}]), encoding="utf-8")
            source = {"name": "Temp Jobs", "type": "manual", "url": str(jobs_path), "enabled": True, "notes": ""}
            collectors.refresh_jobs(path, sources_override=[source])
            job_id = db.list_jobs(path=path)[0]["id"]
            jobs_path.write_text("[]", encoding="utf-8")
            result = collectors.refresh_jobs(path, sources_override=[source])
            job = db.get_job(job_id, path)
        self.assertEqual(result["jobs_marked_missing_or_closed"], 1)
        self.assertTrue(job["is_closed_or_missing"])

    def test_inserted_jobs_return_freshness_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            job_id, _ = db.insert_job({**self.job, "date_posted": db.now_iso()}, path)
            job = db.get_job(job_id, path)
        for field in ["source_posted_at", "first_seen_at", "last_seen_at", "posting_age_days", "freshness_bucket", "freshness_confidence"]:
            self.assertIn(field, job)
        self.assertEqual(job["outcome_status"], "not_started")
        self.assertEqual(job["application_started_at"], "")

    def test_sample_jobs_still_collect(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            result = collectors.refresh_jobs(path, sources_override=[{"name": "Sample GIS Jobs", "type": "manual", "url": "data/sample_jobs.json", "enabled": True, "notes": ""}])
        self.assertEqual(result["jobs_collected"], 5)

    def test_gitignore_protects_private_documents(self):
        patterns = Path(".gitignore").read_text(encoding="utf-8")
        for pattern in ["private/", "private/**", "generated/application_packets/", "generated/application_packets/**", "*.pdf", "*.docx", "*.db", ".env", ".env.*", "*.env", ".vercel"]:
            self.assertIn(pattern, patterns)
        self.assertIn("!private/resume/place_resume_here.md", patterns)

    def test_health_endpoint_reports_sqlite_connected(self):
        result = health()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["database"], "connected")
        self.assertIn("version", result)

    def test_deployment_status_does_not_expose_secrets(self):
        with patch.dict(os.environ, {"FAKE_SECRET_KEY": "do-not-print-me"}, clear=False):
            result = deployment_status()
        text = json.dumps(result)
        self.assertIn(result["database_type"], {"sqlite", "postgres", "unknown"})
        self.assertIn("cors_origins_count", result)
        self.assertNotIn("do-not-print-me", text)

    def test_production_admin_refresh_rejects_missing_token(self):
        with patch("backend.app.api.api_env", return_value="production"), patch("backend.app.api.admin_refresh_token", return_value="secret"):
            with self.assertRaises(HTTPException) as raised:
                admin_refresh_jobs()
        self.assertEqual(raised.exception.status_code, 403)

    def test_production_admin_refresh_accepts_valid_token_without_returning_it(self):
        result = {
            "sources_checked": 1,
            "jobs_collected": 2,
            "new_jobs_inserted": 1,
            "new_jobs_found": 1,
            "duplicates_skipped": 1,
            "duplicates_updated": 1,
            "stale_jobs": 0,
            "high_matches": 1,
            "errors": {},
            "daily_report_path": "runtime/reports/daily_review_2026-06-29.md",
        }
        with patch("backend.app.api.api_env", return_value="production"), patch("backend.app.api.admin_refresh_token", return_value="secret"), patch("backend.app.api.refresh_jobs", return_value=result):
            row = admin_refresh_jobs("secret")
        text = json.dumps(row)
        self.assertTrue(row["report_generated"])
        self.assertEqual(row["strong_excellent_matches"], 1)
        self.assertNotIn("secret", text)

    def test_local_refresh_endpoint_allows_missing_token(self):
        with patch("backend.app.api.api_env", return_value="local"), patch("backend.app.api.admin_refresh_token", return_value=""), patch("backend.app.api.refresh_jobs", return_value={"errors": {}, "daily_report_path": "x"}):
            row = refresh_endpoint()
        self.assertTrue(row["report_generated"])

    def test_env_driven_cors_and_database_url(self):
        with patch("backend.app.paths.load_backend_env"), patch.dict(os.environ, {"CORS_ORIGINS": "[http://localhost:3000,https://gis-job-portal.vercel.app]", "API_ENV": "test", "DATABASE_URL": "sqlite:///./tmp/test.db"}, clear=False):
            self.assertEqual(api_env(), "test")
            self.assertEqual(cors_origins(), ["http://localhost:3000", "https://gis-job-portal.vercel.app"])
            self.assertTrue(str(database_path()).endswith("tmp\\test.db") or str(database_path()).endswith("tmp/test.db"))

    def test_sqlite_remains_default_and_postgres_url_is_recognized(self):
        with patch("backend.app.paths.load_backend_env"):
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(database_url(), "sqlite:///./data/jobs.sqlite3")
                self.assertEqual(database_type(), "sqlite")
            with patch.dict(os.environ, {"DATABASE_URL": "postgresql+psycopg://user:pass@host:5432/db"}, clear=True):
                self.assertEqual(database_type(), "postgres")
                self.assertEqual(database_runtime_type(), "postgres")
                self.assertEqual(database_url_scheme(), "postgresql+psycopg")
                with self.assertRaises(ValueError):
                    database_path()

    def test_export_sqlite_to_json_does_not_include_secrets(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"FAKE_SECRET_KEY": "do-not-print-me"}, clear=False):
            db_path = Path(tmp) / "jobs.sqlite3"
            export_dir = Path(tmp) / "exports"
            db.insert_job({**self.job, "notes": "do-not-print-me", "application_packet_dir": r"C:\Dev\GisJobPortal\private\packet"}, db_path)
            output = export_sqlite_to_json.export_db(export_dir, db_path)
            text = output.read_text(encoding="utf-8")
        self.assertIn('"jobs"', text)
        self.assertNotIn("do-not-print-me", text)
        self.assertNotIn("application_packet_dir", text)
        self.assertNotIn(r"C:\Dev\GisJobPortal\private", text)

    def test_import_json_to_db_handles_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed = Path(tmp) / "seed.json"
            target = Path(tmp) / "target.sqlite3"
            seed.write_text(json.dumps({"sources": [], "jobs": [self.job]}), encoding="utf-8")
            first = import_json_to_db.import_file(seed, target)
            second = import_json_to_db.import_file(seed, target)
            rows = db.list_jobs(path=target)
        self.assertEqual(first["inserted"], 1)
        self.assertEqual(second["duplicates"], 1)
        self.assertEqual(len(rows), 1)

    def test_backend_env_example_uses_placeholders_only(self):
        text = Path("backend/.env.example").read_text(encoding="utf-8")
        self.assertIn("DATABASE_URL=sqlite:///./data/jobs.sqlite3", text)
        self.assertIn("postgresql+psycopg://USER:PASSWORD@HOST:PORT/DB", text)
        self.assertNotIn("OPENROUTER_API_KEY", text)
        self.assertNotRegex(text, r"vcp_|apiapi|AIza|sk-")

    def test_frontend_env_example_documents_api_mode(self):
        text = Path("frontend/.env.example").read_text(encoding="utf-8")
        self.assertIn("NEXT_PUBLIC_API_MODE=api", text)
        self.assertIn("NEXT_PUBLIC_API_BASE_URL=https://YOUR-HOSTED-BACKEND.example.com", text)
        self.assertIn("NEXT_PUBLIC_API_MODE=demo", text)

    def test_production_deployment_docs_exist(self):
        text = Path("docs/PRODUCTION_REAL_DATA_DEPLOYMENT.md").read_text(encoding="utf-8")
        checklist = Path("docs/HOSTED_BACKEND_CHECKLIST.md").read_text(encoding="utf-8")
        self.assertIn("127.0.0.1", text)
        self.assertIn("hosted Postgres", text)
        self.assertIn("/deployment/status", checklist)

    def test_postgres_url_is_explicitly_future_work(self):
        with patch("backend.app.paths.load_backend_env"), patch.dict(os.environ, {"DATABASE_URL": "postgresql://example"}, clear=False):
            with self.assertRaises(ValueError):
                database_path()

    def test_resume_extraction_creates_local_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            resume_dir = Path(tmp) / "resume"
            resume_dir.mkdir()
            (resume_dir / "resume.pdf").write_bytes(b"%PDF placeholder")
            output = resume_dir / "resume_extracted.md"
            with patch("backend.app.documents.read_pdf_text", return_value="Khoi Nguyen GIS Analyst Intern"):
                result = extract_resume(resume_dir, output)
            self.assertTrue(output.exists())
            self.assertIn("GIS Analyst Intern", output.read_text(encoding="utf-8"))
            self.assertEqual(result["output"], str(output))

    def test_transcript_extraction_creates_summary_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            transcript_dir = Path(tmp) / "transcript"
            transcript_dir.mkdir()
            (transcript_dir / "transcript.pdf").write_bytes(b"%PDF placeholder")
            output = transcript_dir / "transcript_summary.md"
            text = "Intro\nGIS Programming A\nUrban Planning B\nUnrelated line"
            with patch("backend.app.documents.read_pdf_text", return_value=text):
                extract_transcript(transcript_dir, output)
            summary = output.read_text(encoding="utf-8")
            self.assertIn("GIS Programming", summary)
            self.assertIn("Urban Planning", summary)
            self.assertNotIn("Unrelated line", summary)

    def test_transcript_is_only_used_when_relevant(self):
        self.assertFalse(should_use_transcript(self.job))
        relevant = {**self.job, "requirements": "Unofficial transcript required with GPA and relevant coursework."}
        self.assertTrue(should_use_transcript(relevant))

    def test_packet_includes_portfolio_and_document_checklist(self):
        scored_job = {"id": 7, **self.job, **score_job(self.job, self.profile)}
        checklist = detect_document_checklist(scored_job)
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}, clear=False), patch("backend.app.ai.service.load_backend_env"):
            files = build_packet_files(scored_job, self.profile, "Cabarrus County GIS Analyst Intern", "", checklist)
        combined = "\n".join(files.values())
        self.assertIn(self.profile["portfolio"], combined)
        self.assertIn("required_documents_checklist.md", files)

    def test_template_packet_quality_basics(self):
        scored_job = {"id": 7, **self.job, **score_job(self.job, self.profile)}
        checklist = detect_document_checklist(scored_job)
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}, clear=False), patch("backend.app.ai.service.load_backend_env"):
            files = build_packet_files(scored_job, self.profile, r"C:\Dev\GisJobPortal\private\resume\resume_extracted.md", "", checklist)
        combined = "\n".join(files.values())
        self.assertIn(self.profile["portfolio"], combined)
        self.assertIn("Cabarrus County", combined)
        self.assertNotRegex(combined, r"\b\d{3}[-.) ]?\d{3}[-. ]?\d{4}\b")
        self.assertNotIn("expert", combined.lower())
        self.assertNotIn("github", combined.lower())
        self.assertNotIn("resume_extracted.md", combined)
        self.assertNotIn("strong arcgis and web gis overlap uses", files["cover_letter.md"].lower())
        self.assertLess(len(files["followup_email.md"]), len(files["cover_letter.md"]))
        self.assertEqual(qa_application_packet.quality_checks(scored_job, {"files": files, "document_checklist": checklist}, self.profile), [])

    def test_checklist_flags_transcript_only_when_posting_requires_it(self):
        self.assertFalse(detect_document_checklist(self.job)["transcript_required"])
        relevant = {**self.job, "requirements": "Unofficial transcript required with GPA and relevant coursework."}
        self.assertTrue(detect_document_checklist(relevant)["transcript_required"])

    def test_generated_materials_do_not_include_phone_or_invent_experience(self):
        job = {**self.job, "requirements": "Drone mapping and AutoCAD required."}
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}, clear=False), patch("backend.app.ai.service.load_backend_env"):
            materials = generate_materials(job, self.profile, "Cabarrus County GIS Analyst Intern")
        combined = "\n".join(str(value) for value in materials.values())
        self.assertNotRegex(combined, r"\b\d{3}[-.) ]?\d{3}[-. ]?\d{4}\b")
        self.assertNotIn("drone", combined.lower())
        self.assertNotIn("autocad", combined.lower())

    def test_ai_status_endpoint_does_not_expose_key(self):
        with patch.dict(os.environ, {"AI_PROVIDER": "openrouter", "AI_MODEL": "openrouter/pony-alpha", "OPENROUTER_API_KEY": "dummy-openrouter-key"}, clear=False), patch("backend.app.ai.service.load_backend_env"):
            status = ai_status_endpoint()
        self.assertEqual(status["mode"], "pony_alpha")
        self.assertNotIn("dummy-openrouter-key", json.dumps(status))

    def test_missing_openrouter_key_uses_template_fallback(self):
        with patch.dict(os.environ, {"AI_PROVIDER": "openrouter", "AI_MODEL": "openrouter/pony-alpha", "OPENROUTER_API_KEY": ""}, clear=False), patch("backend.app.ai.service.load_backend_env"):
            status = ai_status()
            materials = generate_materials(self.job, self.profile)
        self.assertFalse(status["configured"])
        self.assertEqual(status["mode"], "template_fallback")
        self.assertEqual(materials["generation_mode"], "template_fallback")

    def test_configured_provider_reports_pony_alpha(self):
        with patch.dict(os.environ, {"AI_PROVIDER": "openrouter", "AI_MODEL": "openrouter/pony-alpha", "OPENROUTER_API_KEY": "dummy-openrouter-key"}, clear=False), patch("backend.app.ai.service.load_backend_env"):
            status = ai_status()
        self.assertTrue(status["configured"])
        self.assertEqual(status["mode"], "pony_alpha")
        self.assertEqual(status["model"], "openrouter/pony-alpha")

    def test_generated_prompts_do_not_include_private_paths_or_env_content(self):
        dirty_resume = r"C:\Dev\GisJobPortal\private\resume\resume_extracted.md OPENROUTER_API_KEY=secret .env.local"
        context = safe_generation_context(self.job, self.profile, dirty_resume, "")
        prompt = materials_user_prompt(context)
        self.assertNotIn("resume_extracted.md", prompt)
        self.assertNotIn(".env.local", prompt)
        self.assertNotIn("OPENROUTER_API_KEY", prompt)
        self.assertNotIn("secret", prompt.lower())
        self.assertNotIn("C:\\Users", prompt)

    def test_generated_prompts_skip_transcript_unless_allowed(self):
        context = safe_generation_context(self.job, self.profile, "resume summary", "")
        prompt = materials_user_prompt(context)
        self.assertNotIn("Academic Transcript Secret Text", prompt)
        relevant_job = {**self.job, "requirements": "Unofficial transcript required with GPA."}
        allowed_context = safe_generation_context(relevant_job, self.profile, "resume summary", "Academic Transcript Secret Text")
        allowed_prompt = materials_user_prompt(allowed_context)
        self.assertIn("Academic Transcript Secret Text", allowed_prompt)

    def test_openrouter_client_handles_missing_key_cleanly(self):
        with self.assertRaises(MissingAPIKeyError):
            OpenRouterClient(api_key="")

    def test_openrouter_client_parses_mock_response(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"choices":[{"message":{"content":"hello"}}]}'

        with patch("urllib.request.urlopen", return_value=FakeResponse()):
            client = OpenRouterClient(api_key="dummy-openrouter-key", model="openrouter/pony-alpha")
            self.assertEqual(client.generate_text("system", "user"), "hello")


if __name__ == "__main__":
    unittest.main()
