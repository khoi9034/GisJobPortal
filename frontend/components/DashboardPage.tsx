"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api, AiStatus, Job, Source, Stats } from "../lib/api";

type View = "overview" | "new" | "best" | "saved" | "applied" | "follow" | "skipped" | "settings";
type FreshnessFilter = "active" | "fresh" | "last30" | "include_stale" | "closing" | "unknown";

const nav = [
  ["overview", "/", "Overview"],
  ["new", "/new-jobs", "New Jobs"],
  ["best", "/best-matches", "Best Matches"],
  ["saved", "/saved", "Saved Jobs"],
  ["applied", "/applied", "Applied"],
  ["follow", "/follow-up-needed", "Follow-Up Needed"],
  ["skipped", "/skipped", "Skipped"],
  ["settings", "/settings", "Settings/Profile"],
] as const;

const titles: Record<View, string> = {
  overview: "Overview",
  new: "New Jobs",
  best: "Best Matches",
  saved: "Saved Jobs",
  applied: "Applied",
  follow: "Follow-Up Needed",
  skipped: "Skipped",
  settings: "Settings/Profile",
};

function Shell({ view, children }: { view: View; children: React.ReactNode }) {
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <h1>GIS Apply Copilot</h1>
          <p>Human-reviewed GIS job matching and application materials.</p>
        </div>
        <nav className="nav" aria-label="Dashboard views">
          {nav.map(([key, href, label]) => (
            <Link className={view === key ? "active" : ""} href={href} key={key}>
              {label}
            </Link>
          ))}
        </nav>
      </aside>
      <main className="main">{children}</main>
    </div>
  );
}

const FRESH_DAYS = 14;
const LAST_30_DAYS = 30;
const HIDE_AFTER_DAYS = 45;
const CLOSING_SOON_DAYS = 7;

function parseDate(value?: string) {
  return value ? new Date(`${value.slice(0, 10)}T00:00:00`) : null;
}

function daysUntil(value?: string) {
  const date = parseDate(value);
  if (!date) return null;
  return Math.ceil((date.getTime() - Date.now()) / 86400000);
}

function age(job: Job) {
  return job.posting_age_days ?? null;
}

function isClosingSoon(job: Job) {
  const days = daysUntil(job.source_closes_at);
  return days !== null && days >= 0 && days <= CLOSING_SOON_DAYS;
}

function isActive(job: Job, includeStale: boolean) {
  const jobAge = age(job);
  if (job.is_closed_or_missing) return false;
  return includeStale || jobAge === null || jobAge <= HIDE_AFTER_DAYS || job.match_score >= 85;
}

function sortJobs(jobs: Job[]) {
  return [...jobs].sort((a, b) => {
    const posted = (parseDate(b.source_posted_at || b.date_posted)?.getTime() || 0) - (parseDate(a.source_posted_at || a.date_posted)?.getTime() || 0);
    const closeA = parseDate(a.source_closes_at)?.getTime() || Number.MAX_SAFE_INTEGER;
    const closeB = parseDate(b.source_closes_at)?.getTime() || Number.MAX_SAFE_INTEGER;
    const firstSeen = (parseDate(b.first_seen_at || b.date_found)?.getTime() || 0) - (parseDate(a.first_seen_at || a.date_found)?.getTime() || 0);
    return b.match_score - a.match_score || posted || closeA - closeB || firstSeen;
  });
}

function filterJobs(jobs: Job[], view: View, freshness: FreshnessFilter) {
  const includeStale = freshness === "include_stale";
  let rows = jobs.filter((job) => isActive(job, includeStale));
  if (view === "new") rows = rows.filter((job) => job.status === "new");
  if (view === "best") rows = rows.filter((job) => job.match_score >= 75 && job.status !== "skipped");
  if (view === "saved") rows = rows.filter((job) => job.status === "saved");
  if (view === "applied") rows = rows.filter((job) => job.status === "applied");
  if (view === "follow") rows = rows.filter((job) => job.status === "follow_up_needed");
  if (view === "skipped") rows = rows.filter((job) => job.status === "skipped");
  if (freshness === "fresh") rows = rows.filter((job) => age(job) !== null && age(job)! <= FRESH_DAYS);
  if (freshness === "last30") rows = rows.filter((job) => age(job) !== null && age(job)! <= LAST_30_DAYS);
  if (freshness === "closing") rows = rows.filter(isClosingSoon);
  if (freshness === "unknown") rows = rows.filter((job) => !job.source_posted_at && job.freshness_confidence !== "source_posted_date");
  return sortJobs(rows);
}

export default function DashboardPage({ view }: { view: View }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [profile, setProfile] = useState<any>(null);
  const [aiStatus, setAiStatus] = useState<AiStatus | null>(null);
  const [freshness, setFreshness] = useState<FreshnessFilter>("active");
  const [message, setMessage] = useState("");

  async function load() {
    const [jobRows, overview, sourceRows, profileRow, aiRow] = await Promise.all([
      api<Job[]>("/jobs"),
      api<Stats>("/stats/overview"),
      api<Source[]>("/sources"),
      api<any>("/profile"),
      api<AiStatus>("/ai/status"),
    ]);
    setJobs(jobRows);
    setStats(overview);
    setSources(sourceRows);
    setProfile(profileRow);
    setAiStatus(aiRow);
  }

  useEffect(() => {
    load().catch((error) => setMessage(error.message));
  }, []);

  const visibleJobs = useMemo(() => filterJobs(jobs, view, freshness), [jobs, view, freshness]);

  async function refreshJobs() {
    const result = await api<Record<string, number>>("/jobs/refresh", { method: "POST" });
    setMessage(
      `Refresh complete: ${result.new_jobs_found} new, ${result.duplicates_skipped} duplicates skipped.`
    );
    await load();
  }

  async function validateSources() {
    const rows = await api<Source[]>("/sources/validate");
    setSources(rows);
    setMessage("Source validation complete.");
  }

  async function setStatus(job: Job, status: string) {
    await api<Job>(`/jobs/${job.id}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    });
    await load();
  }

  async function generate(job: Job) {
    await api<Job>(`/jobs/${job.id}/generate-materials`, { method: "POST" });
    setMessage(`Generated materials for ${job.title}.`);
    await load();
  }

  async function copy(text: string, label: string) {
    await navigator.clipboard.writeText(text);
    setMessage(`Copied ${label}.`);
  }

  if (view === "settings") {
    return (
      <Shell view={view}>
        <Header title={titles[view]} onRefresh={refreshJobs} message={message} />
        <div className="detail-grid">
          <section className="settings-section">
            <h3>Candidate Profile</h3>
            {profile ? (
              <>
                <p>
                  <strong>{profile.name}</strong><br />
                  {profile.email}<br />
                  {profile.location}<br />
                  <a href={profile.portfolio} target="_blank">Portfolio</a>
                </p>
                <p className="muted">{profile.education?.[0]?.degree} at {profile.education?.[0]?.school}</p>
                <div className="chips">{profile.skills?.map((skill: string) => <span className="chip" key={skill}>{skill}</span>)}</div>
              </>
            ) : <p className="muted">Loading profile...</p>}
          </section>
          <section className="settings-section">
            <h3>Job Sources</h3>
            <button className="button" onClick={validateSources}>Validate Sources</button>
            {sources.map((source) => (
              <p key={source.name}>
                <strong>{source.name}</strong> <span className="chip">{source.type}</span> <span className={source.enabled ? "chip green" : "chip"}>{source.enabled ? "enabled" : "disabled"}</span> <span className={source.validation_status === "error" ? "chip red" : source.validation_status === "warning" ? "chip warning" : source.validation_status === "ok" ? "chip green" : "chip"}>{source.validation_status || source.status || "disabled"}</span><br />
                <span className="muted">{source.notes}</span>
                {(source.last_checked_at || source.last_checked || source.last_status) && (
                  <>
                    <br />
                    <span className="muted">
                      Last checked: {source.last_checked_at || source.last_checked || "never"}{source.last_success_at ? ` | Last success: ${source.last_success_at}` : ""}
                    </span>
                  </>
                )}
                <br />
                <span className="muted">Jobs last run: {source.jobs_found_last_run ?? 0} | sampled: {source.jobs_sampled ?? 0}{source.last_error || source.errors_last_run ? ` | Error: ${source.last_error || source.errors_last_run}` : ""}</span>
                <div className="chips">
                  {(source.supports_posted_date || source.posted_date_supported) && <span className="chip green">posted date</span>}
                  {(source.supports_close_date || source.close_date_supported) && <span className="chip green">close date</span>}
                  {(source.supports_updated_date || source.updated_date_supported) && <span className="chip">updated date</span>}
                  {source.first_seen_only && <span className="chip">first seen only</span>}
                </div>
              </p>
            ))}
          </section>
          <section className="settings-section">
            <h3>AI Settings</h3>
            {aiStatus ? (
              <>
                <p><strong>AI Provider:</strong> OpenRouter</p>
                <p><strong>Model:</strong> Pony Alpha</p>
                <p><strong>Status:</strong> {aiStatus.configured ? "Connected" : "Template fallback"}</p>
                <p className="muted">Private resume/transcript files are not sent automatically.</p>
              </>
            ) : <p className="muted">Loading AI status...</p>}
          </section>
        </div>
      </Shell>
    );
  }

  return (
    <Shell view={view}>
      <Header title={titles[view]} onRefresh={refreshJobs} message={message} />
      {stats && (
        <div className="stats">
          <div className="stat"><strong>{stats.total}</strong><span>Total jobs</span></div>
          <div className="stat"><strong>{stats.high_matches}</strong><span>75+ matches</span></div>
          <div className="stat"><strong>{stats.medium_matches}</strong><span>50-74 matches</span></div>
          <div className="stat"><strong>{stats.by_status.follow_up_needed || 0}</strong><span>Need follow-up</span></div>
        </div>
      )}
      <div className="toolbar">
        <label className="muted" htmlFor="freshness-filter">Freshness</label>
        <select id="freshness-filter" value={freshness} onChange={(event) => setFreshness(event.target.value as FreshnessFilter)}>
          <option value="active">Default active</option>
          <option value="fresh">Fresh only: 0-14 days</option>
          <option value="last30">Last 30 days</option>
          <option value="include_stale">Include stale</option>
          <option value="closing">Closing soon</option>
          <option value="unknown">Unknown posted date</option>
        </select>
      </div>
      <div className="jobs-grid">
        {visibleJobs.map((job) => (
          <JobCard
            job={job}
            key={job.id}
            onStatus={setStatus}
            onGenerate={generate}
            onCopy={copy}
          />
        ))}
        {!visibleJobs.length && <p className="muted">No jobs in this view yet.</p>}
      </div>
    </Shell>
  );
}

function FreshnessChips({ job }: { job: Job }) {
  return (
    <>
      <span className="chip">{job.freshness_bucket || "unknown"}</span>
      <span className="chip">{job.freshness_confidence || "unknown"}</span>
      {job.is_stale && <span className="chip red">stale</span>}
      {isClosingSoon(job) && <span className="chip warning">closing soon</span>}
    </>
  );
}

function Header({ title, onRefresh, message }: { title: string; onRefresh: () => void; message: string }) {
  return (
    <>
      <div className="topbar">
        <div>
          <p className="eyebrow">Human approval required before applying</p>
          <h2>{title}</h2>
        </div>
        <button className="button primary" onClick={onRefresh}>Refresh Jobs</button>
      </div>
      {message && <p className="muted">{message}</p>}
    </>
  );
}

function JobCard({
  job,
  onStatus,
  onGenerate,
  onCopy,
}: {
  job: Job;
  onStatus: (job: Job, status: string) => void;
  onGenerate: (job: Job) => void;
  onCopy: (text: string, label: string) => void;
}) {
  return (
    <article className="job-card">
      <div className="job-head">
        <div>
          <h3>{job.title}</h3>
          <p className="muted">{job.company} | {job.location} | {job.source} | found {job.date_found}</p>
          <p className="muted">
            Posted {job.source_posted_at || job.date_posted || "unknown"} | first seen {job.first_seen_at || job.date_found}
            {job.source_closes_at ? ` | closes ${job.source_closes_at}` : ""}
          </p>
        </div>
        <div className="score"><strong>{job.match_score}</strong><span>match</span></div>
      </div>
      <div className="chips">
        <span className="chip green">{job.status}</span>
        <FreshnessChips job={job} />
        {(job.fit_reasons || []).slice(0, 3).map((reason) => <span className="chip" key={reason}>{reason}</span>)}
        {(job.missing_skills || []).slice(0, 3).map((skill) => <span className="chip red" key={skill}>{skill}</span>)}
      </div>
      <p className="muted">{job.fit_summary}</p>
      <div className="actions">
        <Link className="button" href={`/jobs/${job.id}`}>View Details</Link>
        <button className="button" onClick={() => onStatus(job, "saved")}>Save</button>
        <button className="button" onClick={() => onStatus(job, "skipped")}>Skip</button>
        <button className="button" onClick={() => onStatus(job, "applied")}>Mark Applied</button>
        <button className="button warning" onClick={() => onGenerate(job)}>Generate Materials</button>
        <a className="button" href={job.apply_url} target="_blank">Open Apply Link</a>
        <button className="button" disabled={!job.generated_cover_letter} onClick={() => onCopy(job.generated_cover_letter, "cover letter")}>Copy Cover Letter</button>
        <button className="button" disabled={!job.generated_followup_email} onClick={() => onCopy(job.generated_followup_email, "follow-up email")}>Copy Follow-Up Email</button>
      </div>
    </article>
  );
}
