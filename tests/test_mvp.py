import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app import db
from backend.app.documents import (
    build_packet_files,
    detect_document_checklist,
    extract_resume,
    extract_transcript,
    should_use_transcript,
)
from backend.app.materials import format_material_context, generate_materials
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

    def test_gitignore_protects_private_documents(self):
        patterns = Path(".gitignore").read_text(encoding="utf-8")
        for pattern in ["private/", "private/**", "generated/application_packets/", "generated/application_packets/**", "*.pdf", "*.docx", ".env", ".env.*", "*.env", ".vercel"]:
            self.assertIn(pattern, patterns)
        self.assertIn("!private/resume/place_resume_here.md", patterns)

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
        files = build_packet_files(scored_job, self.profile, "Cabarrus County GIS Analyst Intern", "", checklist)
        combined = "\n".join(files.values())
        self.assertIn(self.profile["portfolio"], combined)
        self.assertIn("required_documents_checklist.md", files)

    def test_generated_materials_do_not_include_phone_or_invent_experience(self):
        job = {**self.job, "requirements": "Drone mapping and AutoCAD required."}
        materials = generate_materials(job, self.profile, "Cabarrus County GIS Analyst Intern")
        combined = "\n".join(str(value) for value in materials.values())
        self.assertNotRegex(combined, r"\b\d{3}[-.) ]?\d{3}[-. ]?\d{4}\b")
        self.assertNotIn("drone", combined.lower())
        self.assertNotIn("autocad", combined.lower())


if __name__ == "__main__":
    unittest.main()
