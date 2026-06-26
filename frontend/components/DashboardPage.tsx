"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api, Job, Stats } from "../lib/api";

type View = "overview" | "new" | "best" | "saved" | "applied" | "follow" | "skipped" | "settings";

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

function filterJobs(jobs: Job[], view: View) {
  if (view === "new") return jobs.filter((job) => job.status === "new");
  if (view === "best") return jobs.filter((job) => job.match_score >= 75 && job.status !== "skipped");
  if (view === "saved") return jobs.filter((job) => job.status === "saved");
  if (view === "applied") return jobs.filter((job) => job.status === "applied");
  if (view === "follow") return jobs.filter((job) => job.status === "follow_up_needed");
  if (view === "skipped") return jobs.filter((job) => job.status === "skipped");
  return jobs;
}

export default function DashboardPage({ view }: { view: View }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [sources, setSources] = useState<any[]>([]);
  const [profile, setProfile] = useState<any>(null);
  const [message, setMessage] = useState("");

  async function load() {
    const [jobRows, overview, sourceRows, profileRow] = await Promise.all([
      api<Job[]>("/jobs"),
      api<Stats>("/stats/overview"),
      api<any[]>("/sources"),
      api<any>("/profile"),
    ]);
    setJobs(jobRows);
    setStats(overview);
    setSources(sourceRows);
    setProfile(profileRow);
  }

  useEffect(() => {
    load().catch((error) => setMessage(error.message));
  }, []);

  const visibleJobs = useMemo(() => filterJobs(jobs, view), [jobs, view]);

  async function refreshJobs() {
    const result = await api<Record<string, number>>("/jobs/refresh", { method: "POST" });
    setMessage(
      `Refresh complete: ${result.new_jobs_found} new, ${result.duplicates_skipped} duplicates skipped.`
    );
    await load();
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
            {sources.map((source) => (
              <p key={source.name}>
                <strong>{source.name}</strong> <span className="chip">{source.type}</span> <span className={source.enabled ? "chip green" : "chip"}>{source.enabled ? "enabled" : "disabled"}</span><br />
                <span className="muted">{source.notes}</span>
              </p>
            ))}
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
        </div>
        <div className="score"><strong>{job.match_score}</strong><span>match</span></div>
      </div>
      <div className="chips">
        <span className="chip green">{job.status}</span>
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
