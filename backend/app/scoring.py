from __future__ import annotations

import re
from typing import Any

POSITIVE_KEYWORDS = [
    "ArcGIS",
    "ArcGIS Pro",
    "ArcGIS Online",
    "ArcGIS Enterprise",
    "Portal",
    "ArcPy",
    "Python",
    "SQL",
    "PostGIS",
    "GIS",
    "geospatial",
    "spatial analysis",
    "zoning",
    "land use",
    "parcels",
    "planning",
    "transportation",
    "utilities",
    "permits",
    "public works",
    "open data",
    "dashboard",
    "web map",
    "web GIS",
    "digital twin",
    "urban planning",
    "data analyst",
]

PENALTY_KEYWORDS = [
    "senior",
    "principal",
    "7+ years",
    "10+ years",
    "PE license",
    "AICP required",
    "master's required",
    "master’s required",
    "PhD",
    "manager",
    "director",
]

CATEGORY_KEYWORDS = {
    "gis_relevance": ["GIS", "geospatial", "spatial analysis", "web map", "web GIS"],
    "planning_relevance": ["planning", "urban planning", "zoning", "land use", "permits"],
    "entry_level_fit": ["analyst", "technician", "associate", "entry", "0-2 years", "1-3 years", "internship"],
    "public_sector_county_city_relevance": ["county", "city", "municipal", "public sector", "public works", "government"],
    "arcgis_relevance": ["ArcGIS", "ArcGIS Pro", "ArcGIS Online", "ArcGIS Enterprise", "Portal", "ArcPy"],
    "python_sql_automation_relevance": ["Python", "SQL", "PostGIS", "automation", "GeoPandas", "scripting"],
    "parcel_zoning_land_use_relevance": ["parcel", "parcels", "zoning", "land use", "address", "boundaries"],
    "location_fit": ["Concord", "Cabarrus", "Charlotte", "North Carolina", "NC", "remote", "hybrid"],
}

CATEGORY_WEIGHTS = {
    "gis_relevance": 18,
    "planning_relevance": 12,
    "entry_level_fit": 12,
    "public_sector_county_city_relevance": 10,
    "arcgis_relevance": 14,
    "python_sql_automation_relevance": 10,
    "parcel_zoning_land_use_relevance": 10,
    "location_fit": 14,
}


def normalized_text(job: dict[str, Any]) -> str:
    return " ".join(
        str(job.get(field, ""))
        for field in ["title", "company", "location", "description", "requirements", "remote_status"]
    ).lower()


def find_matches(text: str, keywords: list[str]) -> list[str]:
    matches = []
    for keyword in keywords:
        pattern = r"(?<!\w)" + re.escape(keyword.lower()) + r"(?!\w)"
        if re.search(pattern, text):
            matches.append(keyword)
    return matches


def category_score(text: str, keywords: list[str], weight: int) -> tuple[int, list[str]]:
    matches = find_matches(text, keywords)
    # ponytail: linear keyword count is enough for MVP; replace with model ranking if false positives matter.
    return min(weight, round(weight * len(matches) / min(3, len(keywords)))), matches


def missing_qualifications(text: str, profile: dict[str, Any]) -> list[str]:
    profile_text = " ".join(profile.get("skills", [])).lower()
    watch_terms = ["Power BI", "AutoCAD", "CAD", "LiDAR", "remote sensing", "AICP", "PE license", "master's"]
    missing = []
    for term in watch_terms:
        if term.lower() in text and term.lower() not in profile_text:
            missing.append(term)
    missing.extend(find_matches(text, [item for item in PENALTY_KEYWORDS if "required" in item.lower()]))
    return sorted(set(missing))


def score_job(job: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    text = normalized_text(job)
    breakdown: dict[str, int] = {}
    keyword_matches: list[str] = []

    for category, keywords in CATEGORY_KEYWORDS.items():
        score, matches = category_score(text, keywords, CATEGORY_WEIGHTS[category])
        breakdown[category] = score
        keyword_matches.extend(matches)

    penalty_matches = find_matches(text, PENALTY_KEYWORDS)
    if breakdown["entry_level_fit"] and not penalty_matches:
        breakdown["entry_level_fit"] = CATEGORY_WEIGHTS["entry_level_fit"]
    seniority_penalty = min(30, len(penalty_matches) * 8)
    breakdown["seniority_penalty"] = -seniority_penalty

    total = max(0, min(100, sum(breakdown.values())))
    unique_matches = sorted(set(keyword_matches), key=str.lower)
    missing = missing_qualifications(text, profile)
    fit_reasons = []
    if breakdown["arcgis_relevance"] >= 9:
        fit_reasons.append("Strong ArcGIS and web GIS overlap")
    if breakdown["parcel_zoning_land_use_relevance"] >= 7:
        fit_reasons.append("Matches parcel, zoning, and land use experience")
    if breakdown["public_sector_county_city_relevance"] >= 7:
        fit_reasons.append("Fits county/city public GIS workflows")
    if breakdown["python_sql_automation_relevance"] >= 7:
        fit_reasons.append("Uses Python, SQL, or automation skills")
    if breakdown["location_fit"] >= 9:
        fit_reasons.append("Good North Carolina or remote location fit")
    if seniority_penalty:
        fit_reasons.append("Seniority requirements may be above current target level")

    if "parcel" in text or "zoning" in text or "land use" in text:
        resume_angle = "Lead with Cabarrus County GIS, parcels, zoning, public data, and Cabarrus FutureScape."
    elif "python" in text or "sql" in text:
        resume_angle = "Lead with GIS automation, Python/SQL, GeoPandas, and data workflow experience."
    else:
        resume_angle = "Lead with ArcGIS Enterprise, public GIS data, web maps, and planning dataset work."

    return {
        "match_score": total,
        "scoring_breakdown": breakdown,
        "keyword_matches": unique_matches,
        "fit_reasons": fit_reasons or ["GIS-related role worth reviewing"],
        "fit_summary": " ".join(fit_reasons[:3]) if fit_reasons else "GIS-related role worth reviewing.",
        "missing_skills": missing,
        "recommended_resume_angle": resume_angle,
    }
