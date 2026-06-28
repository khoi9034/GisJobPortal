import tempfile
import unittest
import io
import os
import json
from pathlib import Path
from datetime import date, timedelta
from contextlib import redirect_stdout
from unittest.mock import patch

from scripts import analyze_job_matches, check_frontend_data_mode, check_ports, discover_sources, export_application_packet, qa_application_packet, setup_usajobs, source_toggle, validate_target_sources
from backend.app import collectors, db, reports
from backend.app.ai.base import MissingAPIKeyError
from backend.app.ai.openrouter_client import OpenRouterClient
from backend.app.ai.prompts import materials_user_prompt, safe_generation_context
from backend.app.ai.service import ai_status
from backend.app.api import ai_status_endpoint, application_board as application_board_endpoint, health, latest_report as latest_report_endpoint, sources as sources_endpoint, validate_source_config
from backend.app.documents import (
    build_packet_files,
    detect_document_checklist,
    extract_resume,
    extract_transcript,
    should_use_transcript,
)
from backend.app.freshness import apply_freshness
from backend.app.materials import format_material_context, generate_materials
from backend.app.paths import api_env, cors_origins, database_path
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
        self.assertTrue(all(source["type"] in {"api", "rss", "greenhouse", "lever", "static_url", "manual"} for source in sources))

    def test_search_profile_loading(self):
        profiles = load_search_profiles()
        self.assertIn("gis_analyst_nc", profiles)
        self.assertIn("GIS Analyst", profiles["gis_analyst_nc"]["keywords"])
        self.assertTrue(profiles["planning_gis_nc"]["include_remote"])

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
        for field in ["supports_posted_date", "supports_updated_date", "supports_close_date", "freshness_confidence_default", "last_checked_at", "last_error"]:
            self.assertIn(field, rows[0])

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
        self.assertIn("Local API mode is enabled but NEXT_PUBLIC_API_BASE_URL is missing.", text)
        self.assertNotIn("catch {\n    return demoApi", text)

    def test_frontend_data_mode_badge_text_logic_exists(self):
        api_text = Path("frontend/lib/api.ts").read_text(encoding="utf-8")
        dashboard_text = Path("frontend/components/DashboardPage.tsx").read_text(encoding="utf-8")
        for label in ["Demo Mode", "Local Backend", "Hosted Backend"]:
            self.assertIn(label, api_text)
        self.assertIn("dataModeLabel()", dashboard_text)

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

    def test_launcher_script_does_not_contain_secrets(self):
        text = Path("scripts/start_local_dev.ps1").read_text(encoding="utf-8")
        self.assertIn("NEXT_PUBLIC_API_MODE=local", text)
        self.assertNotRegex(text, r"vcp_|USAJOBS_AUTHORIZATION_KEY=|OPENROUTER_API_KEY=")

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
            self.assertNotIn(secret, combined)
            self.assertNotIn(r"C:\Dev\GisJobPortal\private", combined)

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

    def test_env_driven_cors_and_database_url(self):
        with patch.dict(os.environ, {"CORS_ORIGINS": "[http://localhost:3000,https://gis-job-portal.vercel.app]", "API_ENV": "test", "DATABASE_URL": "sqlite:///./tmp/test.db"}, clear=False):
            self.assertEqual(api_env(), "test")
            self.assertEqual(cors_origins(), ["http://localhost:3000", "https://gis-job-portal.vercel.app"])
            self.assertTrue(str(database_path()).endswith("tmp\\test.db") or str(database_path()).endswith("tmp/test.db"))

    def test_postgres_url_is_explicitly_future_work(self):
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://example"}, clear=False):
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
