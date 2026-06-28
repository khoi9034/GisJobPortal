export const API_URL = process.env.NEXT_PUBLIC_API_BASE_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const API_MODE = process.env.NEXT_PUBLIC_API_MODE || "local";

export type Job = {
  id: number;
  title: string;
  company: string;
  location: string;
  remote_status: string;
  source: string;
  source_url: string;
  apply_url: string;
  description: string;
  requirements: string;
  salary_min: number | null;
  salary_max: number | null;
  date_posted: string;
  date_found: string;
  source_posted_at?: string;
  source_updated_at?: string;
  source_closes_at?: string;
  first_seen_at?: string;
  last_seen_at?: string;
  last_checked_at?: string;
  posting_age_days?: number | null;
  freshness_bucket?: string;
  freshness_confidence?: string;
  is_stale?: boolean;
  is_closed_or_missing?: boolean;
  reviewed_at?: string;
  review_status?: "unreviewed" | "interested" | "not_interested" | "maybe" | "applied" | "archived";
  review_notes?: string;
  priority_bucket?: "urgent" | "high" | "medium" | "low";
  close_days_remaining?: number | null;
  needs_packet?: boolean;
  packet_generated_at?: string;
  application_url_opened_at?: string;
  application_started_at?: string;
  applied_at?: string;
  follow_up_due_at?: string;
  follow_up_sent_at?: string;
  application_method?: "employer_portal" | "email" | "referral" | "recruiter" | "other" | "";
  application_contact_name?: string;
  application_contact_email?: string;
  application_confirmation_number?: string;
  application_submission_notes?: string;
  outcome_status?: "not_started" | "ready_to_apply" | "applied" | "follow_up_due" | "interview" | "rejected" | "closed" | "withdrawn";
  status: string;
  match_score: number;
  fit_summary: string;
  missing_skills: string[];
  generated_cover_letter: string;
  generated_followup_email: string;
  recruiter_message: string;
  resume_bullet_suggestions: string[];
  notes: string;
  scoring_breakdown: Record<string, number>;
  fit_reasons: string[];
  keyword_matches: string[];
  positive_matches?: string[];
  penalty_matches?: string[];
  score_reason?: string;
  score_band?: string;
  recommended_resume_angle: string;
  application_packet_dir: string;
  document_checklist: DocumentChecklist;
};

export type DocumentChecklist = {
  resume_required?: boolean;
  cover_letter_required?: boolean;
  transcript_required?: boolean;
  portfolio_link_included?: boolean;
  references_required?: boolean;
  writing_sample_required?: boolean;
  other_documents?: string;
};

export type ApplicationPacket = {
  job_id: number;
  exists: boolean;
  packet_dir: string;
  files: Record<string, string>;
  document_checklist: DocumentChecklist;
  generation_mode: "pony_alpha" | "template_fallback";
};

export type AiStatus = {
  provider: string;
  model: string;
  configured: boolean;
  mode: "pony_alpha" | "template_fallback";
};

export type Source = {
  name: string;
  type: string;
  url: string;
  enabled: boolean;
  status?: string;
  validation_status?: "disabled" | "ok" | "warning" | "error";
  notes: string;
  last_checked?: string;
  last_status?: string;
  last_checked_at?: string;
  last_success_at?: string;
  last_error?: string;
  last_validated_at?: string;
  jobs_sampled?: number;
  jobs_found_last_run?: number;
  errors_last_run?: string;
  posted_date_supported?: boolean;
  close_date_supported?: boolean;
  updated_date_supported?: boolean;
  first_seen_only?: boolean;
  supports_posted_date?: boolean;
  supports_close_date?: boolean;
  supports_updated_date?: boolean;
  freshness_confidence_default?: string;
};

export type Stats = {
  total: number;
  high_matches: number;
  medium_matches: number;
  low_matches: number;
  by_status: Record<string, number>;
};

export type ReviewQueue = {
  new_today: Job[];
  fresh_high_match: Job[];
  closing_soon: Job[];
  needs_review: Job[];
  packet_ready: Job[];
  applied_follow_up: Job[];
};

export type ApplicationBoard = {
  ready_to_apply: Job[];
  started: Job[];
  applied: Job[];
  follow_up_due: Job[];
  interview: Job[];
  rejected_closed: Job[];
};

export type DailyReport = {
  exists: boolean;
  date: string;
  path?: string;
  text: string;
  summary: Record<string, number>;
};

const demoJobs: Job[] = [
  {
    id: 1,
    title: "GIS Analyst",
    company: "City of Concord",
    location: "Concord, NC",
    remote_status: "onsite",
    source: "Demo",
    source_url: "https://example.com/concord-gis-analyst",
    apply_url: "https://example.com/concord-gis-analyst/apply",
    description: "Support city GIS operations, parcel data maintenance, zoning layers, web maps, public works datasets, and ArcGIS Enterprise services.",
    requirements: "ArcGIS Pro, ArcGIS Online, ArcGIS Enterprise, Python scripting, SQL, parcel data, zoning, land use, and city department communication.",
    salary_min: 58000,
    salary_max: 72000,
    date_posted: "2026-06-12",
    date_found: "2026-06-26",
    source_posted_at: "2026-06-12",
    source_updated_at: "",
    source_closes_at: "2026-07-03",
    first_seen_at: "2026-06-26",
    last_seen_at: "2026-06-26",
    last_checked_at: "2026-06-26",
    posting_age_days: 14,
    freshness_bucket: "8-14 days",
    freshness_confidence: "source_posted_date",
    is_stale: false,
    is_closed_or_missing: false,
    reviewed_at: "",
    review_status: "unreviewed",
    review_notes: "",
    priority_bucket: "urgent",
    close_days_remaining: 6,
    needs_packet: true,
    packet_generated_at: "",
    application_url_opened_at: "",
    application_started_at: "",
    applied_at: "",
    follow_up_due_at: "",
    follow_up_sent_at: "",
    application_method: "",
    application_contact_name: "",
    application_contact_email: "",
    application_confirmation_number: "",
    application_submission_notes: "",
    outcome_status: "not_started",
    status: "new",
    match_score: 80,
    fit_summary: "Strong ArcGIS and web GIS overlap. Matches parcel, zoning, and land use experience.",
    missing_skills: [],
    generated_cover_letter: "",
    generated_followup_email: "",
    recruiter_message: "",
    resume_bullet_suggestions: [],
    notes: "",
    scoring_breakdown: {
      gis_relevance: 18,
      planning_relevance: 12,
      entry_level_fit: 12,
      public_sector_county_city_relevance: 10,
      arcgis_relevance: 14,
      python_sql_automation_relevance: 10,
      parcel_zoning_land_use_relevance: 10,
      location_fit: 14,
      seniority_penalty: -10,
    },
    fit_reasons: ["Strong ArcGIS and web GIS overlap", "Matches parcel, zoning, and land use experience", "Fits county/city public GIS workflows"],
    keyword_matches: ["ArcGIS", "ArcGIS Enterprise", "ArcGIS Online", "ArcGIS Pro", "GIS", "Python", "SQL", "parcels", "planning", "zoning"],
    positive_matches: ["GIS Analyst", "ArcGIS", "ArcGIS Enterprise", "ArcGIS Online", "ArcGIS Pro", "GIS", "Python", "SQL", "parcels", "planning", "zoning"],
    penalty_matches: [],
    score_reason: "Strong fit; title is directly GIS/planning aligned; GIS/ArcGIS language matched; Python/SQL/automation matched.",
    score_band: "strong fit",
    recommended_resume_angle: "Lead with Cabarrus County GIS, parcels, zoning, public data, and Cabarrus FutureScape.",
    application_packet_dir: "",
    document_checklist: {
      resume_required: true,
      cover_letter_required: false,
      transcript_required: false,
      portfolio_link_included: true,
      references_required: false,
      writing_sample_required: false,
      other_documents: "",
    },
  },
  {
    id: 2,
    title: "Transportation Planning Analyst",
    company: "Regional Mobility Council",
    location: "Charlotte, NC",
    remote_status: "hybrid",
    source: "Demo",
    source_url: "https://example.com/transportation-planning-analyst",
    apply_url: "https://example.com/transportation-planning-analyst/apply",
    description: "Support corridor studies, transportation planning maps, open data dashboards, parcel analysis, and spatial analysis for growth planning.",
    requirements: "Urban planning, transportation, GIS, ArcGIS Pro, web GIS, Python automation, public agency coordination, and data analyst experience.",
    salary_min: 60000,
    salary_max: 78000,
    date_posted: "2026-06-15",
    date_found: "2026-06-26",
    source_posted_at: "2026-06-15",
    source_updated_at: "",
    source_closes_at: "",
    first_seen_at: "2026-06-26",
    last_seen_at: "2026-06-26",
    last_checked_at: "2026-06-26",
    posting_age_days: 11,
    freshness_bucket: "8-14 days",
    freshness_confidence: "source_posted_date",
    is_stale: false,
    is_closed_or_missing: false,
    reviewed_at: "",
    review_status: "unreviewed",
    review_notes: "",
    priority_bucket: "medium",
    close_days_remaining: null,
    needs_packet: true,
    packet_generated_at: "",
    application_url_opened_at: "",
    application_started_at: "",
    applied_at: "",
    follow_up_due_at: "",
    follow_up_sent_at: "",
    application_method: "",
    application_contact_name: "",
    application_contact_email: "",
    application_confirmation_number: "",
    application_submission_notes: "",
    outcome_status: "not_started",
    status: "new",
    match_score: 71,
    fit_summary: "Planning, GIS, Python automation, and North Carolina location fit.",
    missing_skills: [],
    generated_cover_letter: "",
    generated_followup_email: "",
    recruiter_message: "",
    resume_bullet_suggestions: [],
    notes: "",
    scoring_breakdown: {},
    fit_reasons: ["Good North Carolina or remote location fit", "Uses Python, SQL, or automation skills"],
    keyword_matches: ["ArcGIS Pro", "GIS", "Python", "planning", "transportation", "web GIS"],
    positive_matches: ["Transportation Planning Analyst", "ArcGIS Pro", "GIS", "Python", "planning", "transportation", "web GIS"],
    penalty_matches: [],
    score_reason: "Strong fit; title is directly GIS/planning aligned; GIS/ArcGIS language matched; Python/SQL/automation matched.",
    score_band: "strong fit",
    recommended_resume_angle: "Lead with GIS automation, Python/SQL, GeoPandas, and data workflow experience.",
    application_packet_dir: "",
    document_checklist: { resume_required: true, portfolio_link_included: true },
  },
];

function demoStats(): Stats {
  return {
    total: demoJobs.length,
    high_matches: demoJobs.filter((job) => job.match_score >= 70).length,
    medium_matches: demoJobs.filter((job) => job.match_score >= 55 && job.match_score < 70).length,
    low_matches: demoJobs.filter((job) => job.match_score < 55).length,
    by_status: demoJobs.reduce<Record<string, number>>((rows, job) => {
      rows[job.status] = (rows[job.status] || 0) + 1;
      return rows;
    }, {}),
  };
}

function demoPacket(job: Job): ApplicationPacket {
  const portfolio = "https://portfolio-gamma-six-p15gdz1e0v.vercel.app/";
  const files = {
    "cover_letter.md": `Dear ${job.company} Hiring Team,\n\nI am excited to apply for the ${job.title} role. My background includes county GIS workflows, ArcGIS Enterprise/Portal, public GIS data, parcels, zoning, planning layers, and Python/SQL automation.\n\nPortfolio: ${portfolio}\n\nBest,\nKhoi Nguyen`,
    "followup_email.md": `Subject: Application Follow-Up - ${job.title}\n\nHi ${job.company} Team,\n\nI recently applied for the ${job.title} role and wanted to briefly share my interest. I work with county GIS, ArcGIS Enterprise/Portal, public GIS data, parcels, zoning, and planning-related datasets.\n\nPortfolio: ${portfolio}\n\nBest,\nKhoi Nguyen`,
    "recruiter_message.md": `Hi ${job.company} team, I applied for the ${job.title} role and wanted to share my portfolio: ${portfolio}.`,
    "resume_angle.md": job.recommended_resume_angle,
    "resume_bullet_suggestions.md": "- Supported Cabarrus County GIS workflows across ArcGIS Enterprise/Portal, ArcGIS Online, feature services, web maps, and metadata.",
    "required_documents_checklist.md": "- [x] Resume required\n- [ ] Transcript required\n- [x] Portfolio link included",
    "application_notes.md": "Review every material before submitting. This deployed demo does not connect to private local documents.",
  };
  return { job_id: job.id, exists: true, packet_dir: "demo", files, document_checklist: job.document_checklist, generation_mode: "template_fallback" };
}

function demoReviewQueue(): ReviewQueue {
  return {
    new_today: [],
    fresh_high_match: demoJobs.filter((job) => job.match_score >= 70 && job.review_status === "unreviewed"),
    closing_soon: demoJobs.filter((job) => (job.close_days_remaining ?? 99) <= 7),
    needs_review: demoJobs.filter((job) => job.review_status === "unreviewed"),
    packet_ready: demoJobs.filter((job) => ["materials_generated", "ready_to_apply"].includes(job.status)),
    applied_follow_up: demoJobs.filter((job) => ["applied", "follow_up_needed"].includes(job.status)),
  };
}

function demoApplicationBoard(): ApplicationBoard {
  return {
    ready_to_apply: demoJobs.filter((job) => (job.status === "ready_to_apply" || job.outcome_status === "ready_to_apply") && !job.application_started_at && !job.applied_at),
    started: demoJobs.filter((job) => job.application_started_at && !job.applied_at),
    applied: demoJobs.filter((job) => job.status === "applied" || job.outcome_status === "applied"),
    follow_up_due: demoJobs.filter((job) => job.status === "follow_up_needed" || job.outcome_status === "follow_up_due"),
    interview: demoJobs.filter((job) => job.status === "interview" || job.outcome_status === "interview"),
    rejected_closed: demoJobs.filter((job) => job.status === "rejected" || ["rejected", "closed", "withdrawn"].includes(job.outcome_status || "")),
  };
}

function demoReport(): DailyReport {
  return {
    exists: true,
    date: "demo",
    text: "# Daily Review Digest - demo\n\nDemo mode uses bundled sample jobs.",
    summary: {
      new_jobs_inserted: 2,
      high_match_unreviewed_jobs: 1,
      closing_soon_jobs: 1,
      packet_ready_jobs: 0,
      source_errors: 0,
    },
  };
}

function demoApi<T>(path: string, init?: RequestInit): T {
  const method = init?.method || "GET";
  const jobMatch = path.match(/^\/jobs\/(\d+)/);
  const job = jobMatch ? demoJobs.find((row) => row.id === Number(jobMatch[1])) || demoJobs[0] : demoJobs[0];
  if (path === "/jobs") return demoJobs as T;
  if (path.startsWith("/review/queue")) return demoReviewQueue() as T;
  if (path === "/application/board") return demoApplicationBoard() as T;
  if (path === "/reports/latest") return demoReport() as T;
  if (path === "/stats/overview") return demoStats() as T;
  if (path === "/sources") {
    return [
      {
        name: "Demo Jobs",
        type: "manual",
        url: "demo",
        enabled: true,
        status: "ok",
        validation_status: "ok",
        notes: "Bundled frontend demo data",
        last_checked: "",
        last_checked_at: "",
        last_success_at: "",
        last_error: "",
        last_validated_at: "",
        jobs_sampled: demoJobs.length,
        last_status: "demo mode",
        jobs_found_last_run: demoJobs.length,
        errors_last_run: "",
        posted_date_supported: true,
        close_date_supported: false,
        updated_date_supported: false,
        first_seen_only: false,
        supports_posted_date: true,
        supports_close_date: false,
        supports_updated_date: false,
        freshness_confidence_default: "source_posted_date",
      },
    ] as T;
  }
  if (path === "/sources/validate") {
    return [
      {
        name: "Demo Jobs",
        type: "manual",
        enabled: true,
        status: "ok",
        validation_status: "ok",
        notes: "Bundled frontend demo data",
        jobs_sampled: demoJobs.length,
        supports_posted_date: true,
        supports_updated_date: false,
        supports_close_date: false,
        first_seen_only: false,
        freshness_confidence_default: "source_posted_date",
        last_error: "",
      },
    ] as T;
  }
  if (path === "/profile") return { name: "Khoi Nguyen", portfolio: "https://portfolio-gamma-six-p15gdz1e0v.vercel.app/", skills: ["ArcGIS Pro", "ArcGIS Enterprise", "Python", "SQL"] } as T;
  if (path === "/ai/status") return { provider: "openrouter", model: "openrouter/pony-alpha", configured: false, mode: "template_fallback" } as T;
  if (path.includes("/generate-application-packet")) {
    job.status = "materials_generated";
    job.needs_packet = false;
    job.packet_generated_at = new Date().toISOString().slice(0, 10);
    return demoPacket(job) as T;
  }
  if (path.includes("/application-packet")) return demoPacket(job) as T;
  if (jobMatch && method !== "GET") {
    if (path.endsWith("/status") && init?.body) job.status = JSON.parse(String(init.body)).status;
    if (path.endsWith("/review") && init?.body) Object.assign(job, JSON.parse(String(init.body)), { reviewed_at: new Date().toISOString().slice(0, 10) });
    if (path.endsWith("/application") && init?.body) Object.assign(job, JSON.parse(String(init.body)));
    if (path.endsWith("/mark-application-started")) Object.assign(job, { application_started_at: new Date().toISOString().slice(0, 10), application_url_opened_at: new Date().toISOString().slice(0, 10), outcome_status: "ready_to_apply" });
    if (path.endsWith("/mark-applied")) Object.assign(job, { status: "applied", applied_at: new Date().toISOString().slice(0, 10), outcome_status: "applied" });
    if (path.endsWith("/mark-follow-up-sent")) Object.assign(job, { status: "applied", follow_up_sent_at: new Date().toISOString().slice(0, 10), outcome_status: "applied" });
    if (path.endsWith("/notes") && init?.body) job.notes = JSON.parse(String(init.body)).notes;
    if (path.endsWith("/document-checklist") && init?.body) job.document_checklist = JSON.parse(String(init.body)).checklist || job.document_checklist;
    return job as T;
  }
  if (jobMatch) return job as T;
  return {} as T;
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  if (API_MODE === "demo") return demoApi<T>(path, init);
  try {
    const response = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    });
    if (!response.ok) throw new Error(await response.text());
    return response.json() as Promise<T>;
  } catch {
    return demoApi<T>(path, init);
  }
}
