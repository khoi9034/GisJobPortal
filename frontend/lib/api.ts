export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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
};

export type Stats = {
  total: number;
  high_matches: number;
  medium_matches: number;
  low_matches: number;
  by_status: Record<string, number>;
};

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json() as Promise<T>;
}
