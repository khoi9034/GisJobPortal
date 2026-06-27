import tempfile
import unittest
import os
import json
from pathlib import Path
from unittest.mock import patch

from backend.app import collectors, db
from backend.app.ai.base import MissingAPIKeyError
from backend.app.ai.openrouter_client import OpenRouterClient
from backend.app.ai.prompts import materials_user_prompt, safe_generation_context
from backend.app.ai.service import ai_status
from backend.app.api import ai_status_endpoint, health
from backend.app.documents import (
    build_packet_files,
    detect_document_checklist,
    extract_resume,
    extract_transcript,
    should_use_transcript,
)
from backend.app.materials import format_material_context, generate_materials
from backend.app.paths import api_env, cors_origins, database_path
from backend.app.profile import load_profile
from backend.app.scoring import score_job
from backend.app.sources import load_sources


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

    def test_duplicate_detection_uses_company_title_location_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            first_id, first_duplicate = db.insert_job(self.job, path)
            second_id, second_duplicate = db.insert_job(self.job, path)
            self.assertIsNotNone(first_id)
            self.assertFalse(first_duplicate)
            self.assertIsNone(second_id)
            self.assertTrue(second_duplicate)

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

    def test_source_loading(self):
        sources = load_sources()
        self.assertTrue(any(source["type"] == "manual" and source["enabled"] for source in sources))
        self.assertTrue(all(source["type"] in {"api", "rss", "greenhouse", "lever", "static_url", "manual"} for source in sources))

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
        self.assertIn("spatial analysis", job["requirements"])

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
        dirty_resume = r"C:\Users\khoia\OneDrive\Documents\GisJobPortal\private\resume\resume_extracted.md OPENROUTER_API_KEY=secret .env.local"
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
