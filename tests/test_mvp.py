import tempfile
import unittest
from pathlib import Path

from backend.app import db
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

    def test_source_loading(self):
        sources = load_sources()
        self.assertTrue(any(source["type"] == "manual" and source["enabled"] for source in sources))
        self.assertTrue(all(source["type"] in {"api", "rss", "greenhouse", "lever", "static_url", "manual"} for source in sources))


if __name__ == "__main__":
    unittest.main()
