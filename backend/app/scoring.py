from __future__ import annotations

import re
from typing import Any

from .freshness import freshness_score

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
    "QGIS",
    "remote sensing",
    "smart city",
    "smart cities",
    "location intelligence",
    "climate resilience",
]

PENALTY_KEYWORDS = [
    "senior",
    "principal",
    "7+ years",
    "10+ years",
    "PE license",
    "AICP required",
    "master's required",
    "PhD",
    "manager",
    "director",
]

NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

SENIORITY_TERMS = ["senior", "lead", "principal", "manager", "director", "sme", "subject matter expert"]
CERTIFICATION_BLOCKERS = ["PE required", "Professional Engineer required", "AICP required", "PMP required", "PE registration"]

TITLE_STRONG_KEYWORDS = [
    "gis analyst",
    "geospatial analyst",
    "spatial analyst",
    "cartographer",
    "geographer",
    "community planner",
    "urban planning analyst",
    "transportation planning analyst",
    "data analyst gis",
]

ENTRY_KEYWORDS = [
    "recent graduate",
    "recent graduates",
    "student trainee",
    "pathways",
    "entry level",
    "entry-level",
    "gis technician",
    "planning technician",
]

CATEGORY_KEYWORDS = {
    "gis_relevance": ["GIS", "geospatial", "spatial analysis", "web map", "web GIS"],
    "planning_relevance": ["planning", "urban planning", "zoning", "land use", "permits"],
    "entry_level_fit": ["analyst", "technician", "associate", "entry level", "entry-level", "0-2 years", "1-3 years", "internship"],
    "public_sector_county_city_relevance": ["county", "city", "municipal", "public sector", "public works", "government", "federal", "agency", "administration"],
    "arcgis_relevance": ["ArcGIS", "ArcGIS Pro", "ArcGIS Online", "ArcGIS Enterprise", "Portal", "ArcPy"],
    "python_sql_automation_relevance": ["Python", "SQL", "PostGIS", "automation", "GeoPandas", "scripting"],
    "parcel_zoning_land_use_relevance": ["parcel", "parcels", "zoning", "land use", "address", "boundaries"],
    "location_fit": ["Concord", "Cabarrus", "Charlotte", "North Carolina", "NC", "remote", "hybrid"],
}

SEA_LOCATION_KEYWORDS = [
    "Vietnam",
    "Singapore",
    "Malaysia",
    "Thailand",
    "Indonesia",
    "Philippines",
    "Southeast Asia",
    "SEA",
    "APAC",
    "Asia Pacific",
    "Remote APAC",
]

INTERNATIONAL_CONSTRAINT_PATTERNS = [
    ("local citizenship required", r"\b(citizen|citizenship|permanent resident)\b.{0,35}\b(required|only|must)\b"),
    ("work authorization unclear", r"\b(must be authorized|valid work permit|eligible to work|work authorization required)\b"),
    ("local candidates only", r"\b(local candidates only|local applicants only)\b"),
    ("native language only", r"\b(native|fluent)\s+(thai|bahasa|malay|tagalog|filipino|indonesian)\b"),
    ("relocation required", r"\b(relocation required|must relocate|onsite only)\b"),
]

CATEGORY_WEIGHTS = {
    "gis_relevance": 18,
    "planning_relevance": 12,
    "entry_level_fit": 12,
    "public_sector_county_city_relevance": 12,
    "arcgis_relevance": 14,
    "python_sql_automation_relevance": 10,
    "parcel_zoning_land_use_relevance": 10,
    "location_fit": 14,
}


def score_band(score: int) -> str:
    if score >= 85:
        return "excellent fit"
    if score >= 70:
        return "strong fit"
    if score >= 55:
        return "possible fit"
    if score >= 40:
        return "weak/maybe"
    return "low fit"


def normalized_text(job: dict[str, Any]) -> str:
    return " ".join(
        str(job.get(field, ""))
        for field in [
            "title",
            "company",
            "location",
            "country",
            "region",
            "international_region",
            "work_authorization_note",
            "language_requirement",
            "timezone_note",
            "description",
            "requirements",
            "remote_status",
            "source",
        ]
    ).lower()


def find_matches(text: str, keywords: list[str]) -> list[str]:
    matches = []
    for keyword in keywords:
        pattern = r"(?<!\w)" + re.escape(keyword.lower()) + r"(?!\w)"
        if re.search(pattern, text):
            matches.append(keyword)
    return matches


def _num(value: str) -> int | None:
    lowered = value.lower()
    match = re.search(r"\d+", lowered)
    if match:
        return int(match.group())
    return NUMBER_WORDS.get(lowered.strip())


def _experience_mentions(text: str, source_field: str) -> list[dict[str, Any]]:
    token = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)(?:\s*\(\s*\d+\s*\))?"
    mentions = []
    for chunk in re.split(r"[\n.;•]+", text):
        if "year" not in chunk.lower() or ("experience" not in chunk.lower() and source_field != "metadata"):
            continue
        match = re.search(rf"\b(?P<first>{token})\s*(?:\+|plus)?(?:\s*(?:-|to)\s*(?P<second>{token}))?\s+years?\b", chunk, re.IGNORECASE)
        if not match:
            continue
        years = _num(match.group("first"))
        if years is None:
            continue
        lowered = chunk.lower()
        required = not any(word in lowered for word in ["preferred", "nice to have", "desired", "bonus", "plus"])
        if any(word in lowered for word in ["required", "minimum", "at least", "must", "shall", "requires", "requirement"]):
            required = True
        mentions.append({"years": years, "required": required, "evidence": chunk.strip()[:240], "source_field": source_field})
    return mentions


def analyze_experience(job: dict[str, Any]) -> dict[str, Any]:
    title = str(job.get("title") or "")
    metadata_years = _num(str(job.get("required_experience_years") or ""))
    fields = {
        "title": title,
        "description": str(job.get("description") or ""),
        "requirements": str(job.get("requirements") or ""),
        "metadata": str(job.get("required_experience_years") or ""),
    }
    mentions = [mention for field, text in fields.items() for mention in _experience_mentions(text, field)]
    if metadata_years is not None:
        mentions.append({"years": metadata_years, "required": True, "evidence": f"required_experience_years: {metadata_years}", "source_field": "metadata"})
    required = [mention for mention in mentions if mention["required"]]
    preferred = [mention for mention in mentions if not mention["required"]]
    required_years = max((mention["years"] for mention in required), default=None)
    preferred_years = max((mention["years"] for mention in preferred), default=None)
    entry_language = bool(find_matches(" ".join(fields.values()).lower(), ENTRY_KEYWORDS))
    flags = []
    for term in SENIORITY_TERMS:
        source_field = "title" if re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", title, re.IGNORECASE) else ""
        evidence = title if source_field else evidence_for_any(fields, term) if term in {"sme", "subject matter expert"} else ""
        if evidence:
            flags.append({"term": term, "type": "seniority", "evidence": evidence, "source_field": source_field or "description"})
    for term in CERTIFICATION_BLOCKERS:
        evidence = evidence_for_any(fields, term)
        if evidence:
            flags.append({"term": term, "type": "certification", "evidence": evidence, "source_field": "requirements"})
    hard_seniority = bool(flags) and not entry_language
    if hard_seniority or (required_years or 0) >= 10:
        fit = "too_senior"
    elif required_years and required_years > 5:
        fit = "over_cap"
    elif required_years and required_years >= 4:
        fit = "stretch"
    elif required_years is not None:
        fit = "early_career" if required_years >= 3 else "entry"
    elif entry_language:
        fit = "entry"
    else:
        fit = "unknown"
    reason = ""
    evidence = max(required, key=lambda item: item["years"])["evidence"] if required else ""
    if fit in {"over_cap", "too_senior", "stretch"}:
        reason = evidence or (flags[0]["evidence"] if flags else "")
    return {
        "required_experience_years": required_years,
        "preferred_experience_years": preferred_years,
        "experience_fit": fit,
        "experience_blocker_reason": reason,
        "seniority_flags_json": flags,
    }


def evidence_for_any(fields: dict[str, str], phrase: str) -> str:
    for text in fields.values():
        match = re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text, re.IGNORECASE)
        if match:
            start = max(text.rfind(".", 0, match.start()), text.rfind("\n", 0, match.start()))
            end_candidates = [index for index in [text.find(".", match.end()), text.find("\n", match.end())] if index != -1]
            end = min(end_candidates) if end_candidates else min(len(text), match.end() + 160)
            return text[start + 1:end + 1].strip()[:240]
    return ""


def title_matches(title: str) -> list[str]:
    title_text = title.lower()
    return [keyword for keyword in TITLE_STRONG_KEYWORDS if keyword in title_text]


def find_penalties(job: dict[str, Any], text: str) -> list[str]:
    title = str(job.get("title", "")).lower()
    matches = []
    for keyword in ["senior", "principal", "manager", "director"]:
        if re.search(r"(?<!\w)" + re.escape(keyword) + r"(?!\w)", title):
            matches.append(keyword)
    if re.search(r"\b(?:[7-9]|1\d)\+?\s+years\b", text):
        matches.append("7+ years")
    if re.search(r"\bgs-1[1-5]\b", text):
        matches.append("GS-11+ specialized experience")
    for keyword in ["PE license", "AICP required", "master's required", "PhD"]:
        if keyword.lower() in text:
            matches.append(keyword)
    return sorted(set(matches), key=str.lower)


def find_international_constraints(text: str) -> list[str]:
    return sorted({label for label, pattern in INTERNATIONAL_CONSTRAINT_PATTERNS if re.search(pattern, text)}, key=str.lower)


def category_score(text: str, keywords: list[str], weight: int) -> tuple[int, list[str]]:
    matches = find_matches(text, keywords)
    # ponytail: linear keyword count is enough for MVP; add ML ranking only after bad reviewed matches prove it.
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
    title_hits = title_matches(str(job.get("title", "")))
    entry_hits = find_matches(text, ENTRY_KEYWORDS)

    for category, keywords in CATEGORY_KEYWORDS.items():
        score, matches = category_score(text, keywords, CATEGORY_WEIGHTS[category])
        breakdown[category] = score
        keyword_matches.extend(matches)

    experience = analyze_experience(job)
    penalties = find_penalties(job, text)
    if breakdown["entry_level_fit"] and not penalties:
        breakdown["entry_level_fit"] = CATEGORY_WEIGHTS["entry_level_fit"]
    breakdown["title_match"] = 30 if title_hits else 0
    breakdown["gis_title_depth"] = 8 if title_hits and breakdown["gis_relevance"] >= 9 and breakdown["arcgis_relevance"] >= 9 else 0
    breakdown["entry_pathways_boost"] = 12 if entry_hits and (title_hits or breakdown["gis_relevance"] >= 9 or breakdown["planning_relevance"] >= 8) else 0
    seniority_penalty = min(35, len(penalties) * 12)
    breakdown["seniority_penalty"] = -seniority_penalty
    experience_fit = experience["experience_fit"]
    breakdown["experience_fit_penalty"] = -35 if experience_fit == "too_senior" else -30 if experience_fit == "over_cap" else -10 if experience_fit == "stretch" else 6 if experience_fit in {"entry", "early_career"} else 0
    breakdown["freshness"] = freshness_score(job)
    sea_hits = find_matches(text, SEA_LOCATION_KEYWORDS)
    is_gis_or_planning = bool(title_hits or breakdown["gis_relevance"] >= 9 or breakdown["planning_relevance"] >= 8)
    remote_apac = "remote" in text and any(term in text for term in ["apac", "southeast asia", "asia pacific"])
    english_hit = "english" in text
    international_constraints = find_international_constraints(text)
    breakdown["international_region_fit"] = 8 if sea_hits and is_gis_or_planning else 0
    breakdown["remote_apac_fit"] = 5 if remote_apac and is_gis_or_planning else 0
    breakdown["english_role_fit"] = 4 if english_hit and sea_hits else 0
    breakdown["work_authorization_language_penalty"] = -min(24, len(international_constraints) * 8)

    total = max(0, min(100, sum(breakdown.values())))
    required_years = experience["required_experience_years"]
    if required_years and required_years > 5:
        total = min(total, 54)
    if required_years and required_years >= 7:
        total = min(total, 40)
    if (required_years and required_years >= 10) or experience_fit == "too_senior":
        total = min(total, 25)
    if required_years and required_years > 5:
        penalties.append(f"{required_years}+ years required")
    if experience_fit in {"too_senior", "over_cap", "stretch"}:
        penalties.append(experience_fit.replace("_", " "))
    penalties.extend(flag["term"] for flag in experience["seniority_flags_json"])
    penalties = sorted(set(penalties + international_constraints), key=str.lower)
    positives = sorted(set(keyword_matches + title_hits + entry_hits + sea_hits + (["English"] if english_hit and sea_hits else [])), key=str.lower)
    missing = missing_qualifications(text, profile)
    fit_reasons = []
    if breakdown["title_match"]:
        fit_reasons.append("Strong GIS/planning title match")
    if breakdown["gis_title_depth"]:
        fit_reasons.append("Title is backed by real GIS/ArcGIS content")
    if breakdown["arcgis_relevance"] >= 9:
        fit_reasons.append("Strong ArcGIS and web GIS overlap")
    if breakdown["parcel_zoning_land_use_relevance"] >= 7:
        fit_reasons.append("Matches parcel, zoning, and land use experience")
    if breakdown["public_sector_county_city_relevance"] >= 7:
        fit_reasons.append("Fits public-sector GIS workflows")
    if breakdown["python_sql_automation_relevance"] >= 7:
        fit_reasons.append("Uses Python, SQL, or automation skills")
    if breakdown["location_fit"] >= 9:
        fit_reasons.append("Good North Carolina or remote location fit")
    if breakdown["entry_pathways_boost"]:
        fit_reasons.append("Entry-level or recent-graduate language helps fit")
    if breakdown["international_region_fit"]:
        fit_reasons.append("Matches Southeast Asia or APAC target geography")
    if breakdown["remote_apac_fit"]:
        fit_reasons.append("Remote APAC language helps international fit")
    if seniority_penalty:
        fit_reasons.append("Seniority requirements may be above current target level")
    if international_constraints:
        fit_reasons.append("Work authorization, language, or relocation constraints need review")
    if experience_fit in {"too_senior", "over_cap"}:
        fit_reasons.append("Required experience is above the early-career target")
    elif experience_fit == "stretch":
        fit_reasons.append("Required experience is a 4-5 year stretch")

    if "parcel" in text or "zoning" in text or "land use" in text:
        resume_angle = "Lead with Cabarrus County GIS, parcels, zoning, public data, and Cabarrus FutureScape."
    elif "qgis" in text or "remote sensing" in text:
        resume_angle = "Lead with GIS analysis, ArcGIS/QGIS-adjacent workflows, Python, SQL/PostGIS, and spatial data communication."
    elif "python" in text or "sql" in text:
        resume_angle = "Lead with GIS automation, Python/SQL, GeoPandas, and data workflow experience."
    else:
        resume_angle = "Lead with ArcGIS Enterprise, public GIS data, web maps, and planning dataset work."

    reason_parts = [score_band(total).capitalize()]
    if title_hits:
        reason_parts.append("title is directly GIS/planning aligned")
    if breakdown["gis_relevance"] or breakdown["arcgis_relevance"]:
        reason_parts.append("GIS/ArcGIS language matched")
    if breakdown["python_sql_automation_relevance"]:
        reason_parts.append("Python/SQL/automation matched")
    if penalties:
        reason_parts.append("seniority or credential penalties applied")
    if experience_fit in {"too_senior", "over_cap", "stretch"}:
        reason_parts.append(f"experience fit: {experience_fit.replace('_', ' ')}")
    if sea_hits:
        reason_parts.append("SEA/APAC geography matched")
    if breakdown["freshness"] > 0:
        reason_parts.append("freshness helped")
    elif breakdown["freshness"] < 0:
        reason_parts.append("freshness hurt")

    return {
        "match_score": total,
        "scoring_breakdown": breakdown,
        "keyword_matches": sorted(set(keyword_matches), key=str.lower),
        "positive_matches": positives,
        "penalty_matches": penalties,
        "score_reason": "; ".join(reason_parts) + ".",
        "score_band": score_band(total),
        "fit_reasons": fit_reasons or ["GIS-related role worth reviewing"],
        "fit_summary": " ".join(fit_reasons[:3]) if fit_reasons else "GIS-related role worth reviewing.",
        "missing_skills": missing,
        "recommended_resume_angle": resume_angle,
        **experience,
    }
