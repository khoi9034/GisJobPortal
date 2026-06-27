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
  notes: string;
  last_checked?: string;
  last_status?: string;
};

export type Stats = {
  total: number;
  high_matches: number;
  medium_matches: number;
  low_matches: number;
  by_status: Record<string, number>;
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
    recommended_resume_angle: "Lead with GIS automation, Python/SQL, GeoPandas, and data workflow experience.",
    application_packet_dir: "",
    document_checklist: { resume_required: true, portfolio_link_included: true },
  },
];

function demoStats(): Stats {
  return {
    total: demoJobs.length,
    high_matches: demoJobs.filter((job) => job.match_score >= 75).length,
    medium_matches: demoJobs.filter((job) => job.match_score >= 50 && job.match_score < 75).length,
    low_matches: demoJobs.filter((job) => job.match_score < 50).length,
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

function demoApi<T>(path: string, init?: RequestInit): T {
  const method = init?.method || "GET";
  const jobMatch = path.match(/^\/jobs\/(\d+)/);
  const job = jobMatch ? demoJobs.find((row) => row.id === Number(jobMatch[1])) || demoJobs[0] : demoJobs[0];
  if (path === "/jobs") return demoJobs as T;
  if (path === "/stats/overview") return demoStats() as T;
  if (path === "/sources") {
    return [
      {
        name: "Demo Jobs",
        type: "manual",
        url: "demo",
        enabled: true,
        notes: "Bundled frontend demo data",
        last_checked: "",
        last_status: "demo mode",
      },
    ] as T;
  }
  if (path === "/profile") return { name: "Khoi Nguyen", portfolio: "https://portfolio-gamma-six-p15gdz1e0v.vercel.app/", skills: ["ArcGIS Pro", "ArcGIS Enterprise", "Python", "SQL"] } as T;
  if (path === "/ai/status") return { provider: "openrouter", model: "openrouter/pony-alpha", configured: false, mode: "template_fallback" } as T;
  if (path.includes("/application-packet") || path.includes("/generate-application-packet")) return demoPacket(job) as T;
  if (jobMatch && method !== "GET") {
    if (path.endsWith("/status") && init?.body) job.status = JSON.parse(String(init.body)).status;
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
