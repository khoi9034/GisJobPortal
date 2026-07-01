"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api, AiStatus, API_URL, ApplicationBoard, ApplicationPacket, ApplyTodayJob, DailyReport, Job, Source, Stats, dataModeLabel } from "../lib/api";

type View = "overview" | "applyToday" | "review" | "applications" | "new" | "best" | "saved" | "applied" | "follow" | "skipped" | "settings";
type FreshnessFilter = "active" | "fresh" | "last30" | "include_stale" | "closing" | "unknown";
type ReviewFilters = {
  freshOnly: boolean;
  highMatchOnly: boolean;
  closingSoon: boolean;
  unreviewedOnly: boolean;
  includeStale: boolean;
};

const nav = [
  ["overview", "/", "Overview"],
  ["applyToday", "/apply-today", "Apply Today"],
  ["review", "/daily-review", "Daily Review"],
  ["applications", "/applications", "Application Board"],
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
  applyToday: "Apply Today",
  new: "New Jobs",
  best: "Best Matches",
  saved: "Saved Jobs",
  applied: "Applied",
  follow: "Follow-Up Needed",
  skipped: "Skipped",
  settings: "Settings/Profile",
  review: "Daily Review",
  applications: "Application Board",
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
const SAMPLE_JOB_SOURCE = "Sample GIS Jobs";

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

function scoreBand(job: { score_band?: string; match_score: number }) {
  if (job.score_band) return job.score_band;
  if (job.match_score >= 85) return "excellent fit";
  if (job.match_score >= 70) return "strong fit";
  if (job.match_score >= 55) return "possible fit";
  if (job.match_score >= 40) return "weak/maybe";
  return "low fit";
}

function isSampleJob(job: { source: string }) {
  return job.source === SAMPLE_JOB_SOURCE;
}

function SampleJobBadge({ job }: { job: { source: string } }) {
  return isSampleJob(job) ? <span className="chip warning">Demo sample job — not a live posting</span> : null;
}

function jobLink(job: Pick<Job, "apply_url" | "source_url"> | Pick<ApplyTodayJob, "apply_url" | "source_url">) {
  return job.apply_url || job.source_url || "";
}

function LinkNotice({ job }: { job: Pick<Job, "apply_url" | "source_url" | "link_status"> | Pick<ApplyTodayJob, "apply_url" | "source_url" | "link_status"> }) {
  if (job.apply_url) return <span className="chip green">Apply link available</span>;
  if (job.source_url) return <span className="chip">Source-only link</span>;
  return <span className="chip warning">No apply link available from source.</span>;
}

function SourceAttribution({ job }: { job: Pick<Job, "source" | "original_source" | "attribution_note"> | Pick<ApplyTodayJob, "source" | "original_source" | "attribution_note"> }) {
  const isJsearch = /jsearch|rapidapi/i.test(`${job.source} ${job.attribution_note || ""}`);
  return (
    <>
      {isJsearch && <span className="chip">JSearch / Google Jobs result</span>}
      {job.original_source && <span className="chip">Original source: {job.original_source}</span>}
    </>
  );
}

function sourceConfidence(job: Job) {
  return job.freshness_confidence === "source_posted_date" ? 0 : 1;
}

function isActive(job: Job, includeStale: boolean) {
  const jobAge = age(job);
  if (job.is_closed_or_missing) return false;
  return includeStale || jobAge === null || jobAge <= HIDE_AFTER_DAYS || job.match_score >= 85;
}

function sortJobs(jobs: Job[]) {
  return [...jobs].sort((a, b) => {
    const closeA = parseDate(a.source_closes_at)?.getTime() || Number.MAX_SAFE_INTEGER;
    const closeB = parseDate(b.source_closes_at)?.getTime() || Number.MAX_SAFE_INTEGER;
    const posted = (parseDate(b.source_posted_at || b.date_posted)?.getTime() || 0) - (parseDate(a.source_posted_at || a.date_posted)?.getTime() || 0);
    const firstSeen = (parseDate(b.first_seen_at || b.date_found)?.getTime() || 0) - (parseDate(a.first_seen_at || a.date_found)?.getTime() || 0);
    return b.match_score - a.match_score || closeA - closeB || posted || sourceConfidence(a) - sourceConfidence(b) || firstSeen;
  });
}

function filterJobs(jobs: Job[], view: View, freshness: FreshnessFilter) {
  const includeStale = freshness === "include_stale";
  let rows = jobs.filter((job) => isActive(job, includeStale));
  if (view === "new") rows = rows.filter((job) => job.status === "new");
  if (view === "best") rows = rows.filter((job) => job.match_score >= 70 && job.status !== "skipped");
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

function reviewActive(job: Job, includeStale: boolean) {
  return !job.is_closed_or_missing && (includeStale || !job.is_stale);
}

function isUnreviewed(job: Job) {
  return (job.review_status || "unreviewed") === "unreviewed";
}

function buildReviewQueue(jobs: Job[], includeStale: boolean) {
  const today = new Date().toISOString().slice(0, 10);
  const rows = sortJobs(jobs.filter((job) => reviewActive(job, includeStale)));
  return {
    new_today: rows.filter((job) => isUnreviewed(job) && (job.first_seen_at || job.date_found) === today),
    fresh_high_match: rows.filter((job) => isUnreviewed(job) && job.match_score >= 70 && !job.is_stale),
    closing_soon: rows.filter((job) => isClosingSoon(job) && !["applied", "skipped"].includes(job.status)),
    needs_review: rows.filter(isUnreviewed),
    packet_ready: rows.filter((job) => ["materials_generated", "ready_to_apply"].includes(job.status)),
    applied_follow_up: rows.filter((job) => ["applied", "follow_up_needed"].includes(job.status)),
  };
}

function emptyApplicationBoard(): ApplicationBoard {
  return { ready_to_apply: [], started: [], applied: [], follow_up_due: [], interview: [], rejected_closed: [] };
}

function reviewFilterRows(jobs: Job[], filters: ReviewFilters) {
  return jobs.filter((job) => {
    if (filters.freshOnly && !(age(job) !== null && age(job)! <= FRESH_DAYS)) return false;
    if (filters.highMatchOnly && job.match_score < 70) return false;
    if (filters.closingSoon && !isClosingSoon(job)) return false;
    if (filters.unreviewedOnly && !isUnreviewed(job)) return false;
    return true;
  });
}

function credentialsPresent(source: Source) {
  if (!source.name.toLowerCase().includes("usajobs")) return "unknown";
  if ((source.last_error || source.errors_last_run || "").toLowerCase().includes("credentials missing")) return "no";
  return source.validation_status === "ok" ? "yes" : "unknown";
}

function nextSourceAction(source: Source) {
  if (credentialsPresent(source) === "no") return "Add credentials";
  if (!source.enabled) return "Enable source";
  if (!source.validation_status || source.validation_status === "disabled" || source.validation_status !== "ok") return "Validate source";
  if ((source.jobs_found_last_run || 0) === 0) return "Refresh jobs";
  return "Ready";
}

function sourceSummary(sources: Source[]) {
  const isInternational = (source: Source) => /international|southeast_asia|apac/i.test(`${source.region_scope || ""} ${source.international_region || ""}`);
  const isSea = (source: Source) => /southeast_asia|southeast asia/i.test(`${source.region_scope || ""} ${source.international_region || ""}`);
  const unsupported = sources.filter((source) => source.coverage_tier === "unsupported" || (source.coverage_tier !== "big_board_email_alert" && /unsupported|login|workday|linkedin|indeed/i.test(`${source.notes} ${source.url}`))).length;
  return {
    active: sources.filter((source) => source.enabled).length,
    disabled: sources.filter((source) => !source.enabled).length,
    unsupported,
    us: sources.filter((source) => !isInternational(source) && source.coverage_tier !== "unsupported").length,
    international: sources.filter(isInternational).length,
    southeastAsia: sources.filter(isSea).length,
    seaStrongMatches: sources.reduce((sum, source) => sum + (source.strong_matches_by_region?.southeast_asia || 0), 0),
    manualReview: sources.filter((source) => !source.enabled && ["manual", "static_url"].includes(source.type) && !/unsupported|login/i.test(source.notes)).length,
    broadApi: sources.filter((source) => source.coverage_tier === "broad_api" && source.enabled).length,
    emailAlerts: sources.filter((source) => source.coverage_tier === "big_board_email_alert").length,
    publicAts: sources.filter((source) => source.coverage_tier === "public_ats" && source.enabled).length,
    governmentApi: sources.filter((source) => source.coverage_tier === "government_api" && source.enabled).length,
    credentialMissing: sources.filter((source) => source.requires_api_key && source.credential_missing).length,
    sourceErrors: sources.filter((source) => source.last_error || source.errors_last_run || source.validation_status === "error").length,
  };
}

export default function DashboardPage({ view }: { view: View }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [applyTodayJobs, setApplyTodayJobs] = useState<ApplyTodayJob[]>([]);
  const [applicationBoard, setApplicationBoard] = useState<ApplicationBoard>(emptyApplicationBoard());
  const [report, setReport] = useState<DailyReport | null>(null);
  const [profile, setProfile] = useState<any>(null);
  const [aiStatus, setAiStatus] = useState<AiStatus | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [freshness, setFreshness] = useState<FreshnessFilter>("active");
  const [reviewFilters, setReviewFilters] = useState<ReviewFilters>({ freshOnly: false, highMatchOnly: false, closingSoon: false, unreviewedOnly: false, includeStale: false });
  const [message, setMessage] = useState("");
  const [alertSource, setAlertSource] = useState("linkedin");
  const [alertText, setAlertText] = useState("");

  async function load() {
    setLoaded(false);
    const [jobRows, overview, sourceRows, applyTodayRows, boardRows, reportRow, profileRow, aiRow] = await Promise.allSettled([
      api<Job[]>("/jobs"),
      api<Stats>("/stats/overview"),
      api<Source[]>("/sources"),
      api<ApplyTodayJob[]>("/review/apply-today"),
      api<ApplicationBoard>("/application/board"),
      api<DailyReport>("/reports/latest"),
      api<any>("/profile"),
      api<AiStatus>("/ai/status"),
    ]);
    const failures: string[] = [];
    if (jobRows.status === "fulfilled") setJobs(jobRows.value); else failures.push(`/jobs: ${jobRows.reason}`);
    if (overview.status === "fulfilled") setStats(overview.value); else failures.push(`/stats/overview: ${overview.reason}`);
    if (sourceRows.status === "fulfilled") setSources(sourceRows.value); else failures.push(`/sources: ${sourceRows.reason}`);
    if (applyTodayRows.status === "fulfilled") setApplyTodayJobs(applyTodayRows.value); else failures.push(`/review/apply-today: ${applyTodayRows.reason}`);
    if (boardRows.status === "fulfilled") setApplicationBoard(boardRows.value); else failures.push(`/application/board: ${boardRows.reason}`);
    if (reportRow.status === "fulfilled") setReport(reportRow.value); else failures.push(`/reports/latest: ${reportRow.reason}`);
    if (profileRow.status === "fulfilled") setProfile(profileRow.value); else failures.push(`/profile: ${profileRow.reason}`);
    if (aiRow.status === "fulfilled") setAiStatus(aiRow.value); else failures.push(`/ai/status: ${aiRow.reason}`);
    if (failures.length) setMessage(`Live API connected, but ${failures.join("; ")}`);
    setLoaded(true);
  }

  useEffect(() => {
    load().catch((error) => {
      setMessage(error.message);
      setLoaded(true);
    });
  }, []);

  const visibleJobs = useMemo(() => filterJobs(jobs, view, freshness), [jobs, view, freshness]);
  const reviewQueue = useMemo(() => buildReviewQueue(jobs, reviewFilters.includeStale), [jobs, reviewFilters.includeStale]);
  const sourceCounts = useMemo(() => sourceSummary(sources), [sources]);
  const emailAlertSources = sources.filter((source) => source.coverage_tier === "big_board_email_alert");
  const remotiveApac = sources.find((source) => source.name === "Remotive APAC Remote");
  const latestAlertSource = emailAlertSources.find((source) => source.last_checked_at || source.last_checked || source.jobs_total || source.last_error || source.errors_last_run);

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

  async function importAlertText() {
    const result = await api<{ inserted: number; duplicates_updated: number }>("/imports/job-alert-email-text", {
      method: "POST",
      body: JSON.stringify({ source_hint: alertSource, raw_email_text: alertText }),
    });
    setMessage(`Imported ${result.inserted} alert jobs, updated ${result.duplicates_updated} duplicates.`);
    setAlertText("");
    await load();
  }

  async function setStatus(job: Job, status: string) {
    await api<Job>(`/jobs/${job.id}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    });
    await load();
  }

  async function setReview(job: Pick<Job, "id">, review_status: string) {
    await api<Job>(`/jobs/${job.id}/review`, {
      method: "PATCH",
      body: JSON.stringify({ review_status }),
    });
    await load();
  }

  async function patchApplication(job: Pick<Job, "id">, fields: Partial<Job>) {
    await api<Job>(`/jobs/${job.id}/application`, {
      method: "PATCH",
      body: JSON.stringify(fields),
    });
    await load();
  }

  async function markStarted(job: Pick<Job, "id">) {
    await api<Job>(`/jobs/${job.id}/mark-application-started`, { method: "POST" });
    await load();
  }

  async function markApplied(job: Pick<Job, "id">) {
    await api<Job>(`/jobs/${job.id}/mark-applied`, { method: "POST" });
    await load();
  }

  async function markFollowUpSent(job: Job) {
    await api<Job>(`/jobs/${job.id}/mark-follow-up-sent`, { method: "POST" });
    await load();
  }

  async function openApply(job: Job) {
    const link = jobLink(job);
    if (!link) {
      setMessage("No apply link available from source.");
      return;
    }
    window.open(link, "_blank", "noopener,noreferrer");
    await patchApplication(job, { application_url_opened_at: new Date().toISOString().slice(0, 10) });
  }

  async function setFollowUp(job: Job) {
    const value = window.prompt("Follow-up due date (YYYY-MM-DD)", job.follow_up_due_at || "");
    if (value !== null) await patchApplication(job, { follow_up_due_at: value, outcome_status: value ? "follow_up_due" : job.outcome_status });
  }

  async function addSubmissionNotes(job: Pick<Job, "id" | "application_submission_notes">) {
    const value = window.prompt("Submission notes", job.application_submission_notes || "");
    if (value !== null) await patchApplication(job, { application_submission_notes: value });
  }

  async function updateBlocker(job: Pick<Job, "id">, blocker_type: string, fields: Record<string, unknown>) {
    await api(`/jobs/${job.id}/blockers`, { method: "PATCH", body: JSON.stringify({ blocker_type, ...fields }) });
    await load();
  }

  async function noteBlocker(job: Pick<Job, "id">, blocker_type: string) {
    const note = window.prompt("Blocker note", "");
    if (note !== null) await updateBlocker(job, blocker_type, { resolution_note: note });
  }

  async function overrideReady(job: Pick<Job, "id">) {
    const reason = window.prompt("Manual override reason");
    if (reason) {
      await api(`/jobs/${job.id}/blockers`, { method: "PATCH", body: JSON.stringify({ manual_apply_override: true, manual_apply_override_reason: reason }) });
      await load();
    }
  }

  async function generate(job: Job) {
    await api<Job>(`/jobs/${job.id}/generate-materials`, { method: "POST" });
    setMessage(`Generated materials for ${job.title}.`);
    await load();
  }

  async function generatePacket(job: Pick<Job, "id" | "title">) {
    const row = await api<ApplicationPacket>(`/jobs/${job.id}/generate-application-packet`, { method: "POST" });
    setMessage(`${job.title}: ${row.generation_mode === "pony_alpha" ? "Pony Alpha" : "template fallback"} packet generated.`);
    await load();
  }

  async function copy(text: string, label: string) {
    await navigator.clipboard.writeText(text);
    setMessage(`Copied ${label}.`);
  }

  const headerMeta = {
    mode: dataModeLabel(),
    apiUrl: API_URL,
    sourceCount: loaded ? String(sources.length) : "loading",
    lastRefresh: loaded ? reportTimestamp(report) : "loading",
  };

  if (view === "settings") {
    return (
      <Shell view={view}>
        <Header title={titles[view]} onRefresh={refreshJobs} message={message} meta={headerMeta} />
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
            <div className="stats">
              <div className="stat"><strong>{sourceCounts.active}</strong><span>Active sources</span></div>
              <div className="stat"><strong>{sourceCounts.broadApi}</strong><span>Active broad APIs</span></div>
              <div className="stat"><strong>{sourceCounts.emailAlerts}</strong><span>Email alert sources</span></div>
              <div className="stat"><strong>{sourceCounts.publicAts}</strong><span>Active ATS</span></div>
              <div className="stat"><strong>{sourceCounts.governmentApi}</strong><span>Government APIs</span></div>
              <div className="stat"><strong>{sourceCounts.us}</strong><span>US sources</span></div>
              <div className="stat"><strong>{sourceCounts.international}</strong><span>International sources</span></div>
              <div className="stat"><strong>{sourceCounts.southeastAsia}</strong><span>Southeast Asia sources</span></div>
              <div className="stat"><strong>{sourceCounts.seaStrongMatches}</strong><span>SEA strong matches</span></div>
              <div className="stat"><strong>{sourceCounts.disabled}</strong><span>Disabled sources</span></div>
              <div className="stat"><strong>{sourceCounts.manualReview}</strong><span>Manual review</span></div>
              <div className="stat"><strong>{sourceCounts.unsupported}</strong><span>Unsupported</span></div>
              <div className="stat"><strong>{sourceCounts.credentialMissing}</strong><span>Credentials missing</span></div>
              <div className="stat"><strong>{sourceCounts.sourceErrors}</strong><span>Source errors</span></div>
            </div>
            {sources.map((source) => (
              <p key={source.name}>
                <strong>{source.name}</strong> <span className="chip">{source.type}</span> {source.coverage_tier && <span className="chip">{source.coverage_tier.replaceAll("_", " ")}</span>} {source.region_scope && <span className="chip">{source.region_scope.replaceAll("_", " ")}</span>} <span className={source.enabled ? "chip green" : "chip"}>{source.enabled ? "enabled" : "disabled"}</span> <span className={source.validation_status === "error" ? "chip red" : source.validation_status === "warning" ? "chip warning" : source.validation_status === "ok" ? "chip green" : "chip"}>{source.validation_status || source.status || "disabled"}</span>{source.requires_api_key && <span className={source.credentials_configured ? "chip green" : "chip warning"}>{source.credentials_configured ? "credentials present" : "credentials missing"}</span>}<br />
                <span className="muted">{source.notes}</span>
                {source.coverage_tier === "big_board_email_alert" && (
                  <>
                    <br />
                    <span className="muted">
                      Gmail ingestion: {source.gmail_ingestion_enabled ? "enabled" : "disabled"} / {source.gmail_configured ? "configured" : "not configured"} | Query: {source.gmail_alert_query || "not set"} | Safety: no scraping, no auto-apply
                    </span>
                  </>
                )}
                {(source.last_checked_at || source.last_checked || source.last_status) && (
                  <>
                    <br />
                    <span className="muted">
                      Last checked: {source.last_checked_at || source.last_checked || "never"}{source.last_success_at ? ` | Last success: ${source.last_success_at}` : ""}
                    </span>
                  </>
                )}
                <br />
                <span className="muted">Jobs last run: {source.jobs_found_last_run ?? 0} | total visible: {source.jobs_total ?? 0} | strong matches: {source.strong_matches ?? 0} | missing links: {source.missing_links ?? 0} | SEA strong: {source.strong_matches_by_region?.southeast_asia ?? 0} | sampled: {source.jobs_sampled ?? 0}{source.last_error || source.errors_last_run ? ` | Error: ${source.last_error || source.errors_last_run}` : ""}</span>
                <div className="chips">
                  {(source.supports_posted_date || source.posted_date_supported) && <span className="chip green">posted date</span>}
                  {(source.supports_close_date || source.close_date_supported) && <span className="chip green">close date</span>}
                  {(source.supports_updated_date || source.updated_date_supported) && <span className="chip">updated date</span>}
                  {source.first_seen_only && <span className="chip">first seen only</span>}
                  {source.max_jobs_per_source_per_refresh && <span className="chip">max {source.max_jobs_per_source_per_refresh}/refresh</span>}
                  {source.min_score_by_source && <span className="chip">min score {source.min_score_by_source}</span>}
                  {source.terms_notes && <span className="chip">terms noted</span>}
                  {source.requires_oauth && <span className={source.gmail_configured ? "chip green" : "chip warning"}>{source.gmail_configured ? "Gmail configured" : "Gmail not configured"}</span>}
                  {source.scraping_supported === false && <span className="chip">no scraping</span>}
                  {source.auto_apply_supported === false && <span className="chip">no auto-apply</span>}
                </div>
                <ActivationChecklist source={source} />
              </p>
            ))}
          </section>
          <section className="settings-section">
            <h3>Job Alert Ingestion</h3>
            <p className="muted">LinkedIn, Indeed, JobStreet, Glints, VietnamWorks, and TopCV coverage comes from authorized Gmail job-alert emails. No scraping, no login automation, no auto-apply.</p>
            <p className="muted">Gmail ingestion: {emailAlertSources.some((source) => source.gmail_ingestion_enabled) ? "enabled" : "disabled"} | Gmail setup: {emailAlertSources.some((source) => source.gmail_configured) ? "configured" : "not configured"} | Query: {emailAlertSources.find((source) => source.gmail_alert_query)?.gmail_alert_query || "not set"} | Imported alert jobs: {emailAlertSources.reduce((sum, source) => sum + (source.jobs_total || 0), 0)}</p>
            <p className="muted">Last alert status: {latestAlertSource ? `${latestAlertSource.name} checked ${latestAlertSource.last_checked_at || latestAlertSource.last_checked || "recently"}; jobs ${latestAlertSource.jobs_total || 0}; errors ${latestAlertSource.last_error || latestAlertSource.errors_last_run || 0}` : "no alert ingestion run yet"} | Remotive APAC: {remotiveApac?.enabled ? "enabled" : "disabled"} / {remotiveApac?.last_error || remotiveApac?.errors_last_run || "no errors"}</p>
            <div className="chips">{emailAlertSources.map((source) => <span className={source.enabled ? "chip green" : "chip"} key={source.name}>{source.name}: {source.enabled ? "enabled" : "disabled"}</span>)}</div>
            <label className="muted" htmlFor="alert-source">Source</label>
            <select id="alert-source" value={alertSource} onChange={(event) => setAlertSource(event.target.value)}>
              <option value="linkedin">LinkedIn</option>
              <option value="indeed">Indeed</option>
              <option value="jobstreet">JobStreet / JobsDB</option>
              <option value="glints">Glints</option>
              <option value="vietnamworks">VietnamWorks</option>
              <option value="topcv">TopCV</option>
            </select>
            <textarea value={alertText} onChange={(event) => setAlertText(event.target.value)} placeholder="Paste a full job alert email here to test parsing." rows={7} />
            <button className="button" onClick={importAlertText} disabled={!alertText.trim()}>Import Pasted Alert Text</button>
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

  if (view === "review") {
    return (
      <Shell view={view}>
        <Header title={titles[view]} onRefresh={refreshJobs} message={message} meta={headerMeta} />
        <DailyDigest report={report} />
        <ReviewFilterBar filters={reviewFilters} setFilters={setReviewFilters} />
        <ReviewGroup title="New Today" jobs={reviewFilterRows(reviewQueue.new_today, reviewFilters)} onReview={setReview} onStatus={setStatus} onGeneratePacket={generatePacket} />
        <ReviewGroup title="Fresh High Match" jobs={reviewFilterRows(reviewQueue.fresh_high_match, reviewFilters)} onReview={setReview} onStatus={setStatus} onGeneratePacket={generatePacket} />
        <ReviewGroup title="Closing Soon" jobs={reviewFilterRows(reviewQueue.closing_soon, reviewFilters)} onReview={setReview} onStatus={setStatus} onGeneratePacket={generatePacket} />
        <ReviewGroup title="Needs Review" jobs={reviewFilterRows(reviewQueue.needs_review, reviewFilters)} onReview={setReview} onStatus={setStatus} onGeneratePacket={generatePacket} />
        <ReviewGroup title="Packet Ready" jobs={reviewFilterRows(reviewQueue.packet_ready, reviewFilters)} onReview={setReview} onStatus={setStatus} onGeneratePacket={generatePacket} />
      </Shell>
    );
  }

  if (view === "applyToday") {
    return (
      <Shell view={view}>
        <Header title={titles[view]} onRefresh={refreshJobs} message={message} meta={headerMeta} />
        <section className="settings-section">
          <h3>Top 5 Jobs To Act On First</h3>
          <p className="muted">Real live postings only by default. Review the packet before applying manually.</p>
        </section>
        <div className="jobs-grid">
          {applyTodayJobs.map((job) => (
            <ApplyTodayCard key={job.id} job={job} onReview={setReview} onStarted={markStarted} onApplied={markApplied} onGeneratePacket={generatePacket} onNotes={addSubmissionNotes} onCopy={copy} onResolveBlocker={updateBlocker} onNoteBlocker={noteBlocker} onOverrideReady={overrideReady} />
          ))}
          {!applyTodayJobs.length && <p className="muted">{loaded ? "No priority jobs ready right now." : "Loading priority jobs..."}</p>}
        </div>
      </Shell>
    );
  }

  if (view === "applications") {
    return (
      <Shell view={view}>
        <Header title={titles[view]} onRefresh={refreshJobs} message={message} meta={headerMeta} />
        <section className="settings-section">
          <h3>Manual Apply Checklist</h3>
          <p className="muted">This portal prepares and tracks materials only. Submit applications manually outside the app.</p>
          <ul>
            <li>Open apply link</li>
            <li>Upload resume manually</li>
            <li>Upload cover letter manually if required</li>
            <li>Upload transcript manually only if required</li>
            <li>Paste/check answers, submit manually, record confirmation number, then mark applied</li>
          </ul>
        </section>
        <ApplicationGroup title="Ready to Apply" jobs={applicationBoard.ready_to_apply} onOpenApply={openApply} onStarted={markStarted} onApplied={markApplied} onFollowUp={setFollowUp} onFollowUpSent={markFollowUpSent} onNotes={addSubmissionNotes} onCopy={copy} />
        <ApplicationGroup title="Started" jobs={applicationBoard.started} onOpenApply={openApply} onStarted={markStarted} onApplied={markApplied} onFollowUp={setFollowUp} onFollowUpSent={markFollowUpSent} onNotes={addSubmissionNotes} onCopy={copy} />
        <ApplicationGroup title="Applied" jobs={applicationBoard.applied} onOpenApply={openApply} onStarted={markStarted} onApplied={markApplied} onFollowUp={setFollowUp} onFollowUpSent={markFollowUpSent} onNotes={addSubmissionNotes} onCopy={copy} />
        <ApplicationGroup title="Follow-Up Due" jobs={applicationBoard.follow_up_due} onOpenApply={openApply} onStarted={markStarted} onApplied={markApplied} onFollowUp={setFollowUp} onFollowUpSent={markFollowUpSent} onNotes={addSubmissionNotes} onCopy={copy} />
        <ApplicationGroup title="Interview" jobs={applicationBoard.interview} onOpenApply={openApply} onStarted={markStarted} onApplied={markApplied} onFollowUp={setFollowUp} onFollowUpSent={markFollowUpSent} onNotes={addSubmissionNotes} onCopy={copy} />
        <ApplicationGroup title="Rejected / Closed" jobs={applicationBoard.rejected_closed} onOpenApply={openApply} onStarted={markStarted} onApplied={markApplied} onFollowUp={setFollowUp} onFollowUpSent={markFollowUpSent} onNotes={addSubmissionNotes} onCopy={copy} />
      </Shell>
    );
  }

  return (
    <Shell view={view}>
      <Header title={titles[view]} onRefresh={refreshJobs} message={message} meta={headerMeta} />
      {view === "overview" && <div className="toolbar"><Link className="button primary" href="/apply-today">View Apply Today</Link></div>}
      {view === "overview" && <DailyDigest report={report} />}
      {stats && (
        <div className="stats">
          <div className="stat"><strong>{stats.total}</strong><span>Total jobs</span></div>
          <div className="stat"><strong>{stats.high_matches}</strong><span>70+ strong fits</span></div>
          <div className="stat"><strong>{stats.medium_matches}</strong><span>55-69 possible</span></div>
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
        {!visibleJobs.length && (
          <p className="muted">
            {!loaded
              ? "Loading live jobs..."
              : dataModeLabel() === "Live API" && (jobs.length || stats?.total)
              ? `Live API connected, but no jobs returned for this filter. Backend reports ${stats?.total ?? jobs.length} jobs. Try Include stale or Refresh jobs.`
              : "No jobs in this view yet."}
          </p>
        )}
      </div>
    </Shell>
  );
}

function ApplicationGroup({
  title,
  jobs,
  onOpenApply,
  onStarted,
  onApplied,
  onFollowUp,
  onFollowUpSent,
  onNotes,
  onCopy,
}: {
  title: string;
  jobs: Job[];
  onOpenApply: (job: Job) => void;
  onStarted: (job: Job) => void;
  onApplied: (job: Job) => void;
  onFollowUp: (job: Job) => void;
  onFollowUpSent: (job: Job) => void;
  onNotes: (job: Job) => void;
  onCopy: (text: string, label: string) => void;
}) {
  return (
    <section>
      <h3>{title}</h3>
      <div className="jobs-grid">
        {jobs.map((job) => (
          <ApplicationJobCard key={`${title}-${job.id}`} job={job} onOpenApply={onOpenApply} onStarted={onStarted} onApplied={onApplied} onFollowUp={onFollowUp} onFollowUpSent={onFollowUpSent} onNotes={onNotes} onCopy={onCopy} />
        ))}
        {!jobs.length && <p className="muted">No jobs in this group.</p>}
      </div>
    </section>
  );
}

function ApplyTodayCard({
  job,
  onReview,
  onStarted,
  onApplied,
  onGeneratePacket,
  onNotes,
  onCopy,
  onResolveBlocker,
  onNoteBlocker,
  onOverrideReady,
}: {
  job: ApplyTodayJob;
  onReview: (job: Pick<Job, "id">, reviewStatus: string) => void;
  onStarted: (job: Pick<Job, "id">) => void;
  onApplied: (job: Pick<Job, "id">) => void;
  onGeneratePacket: (job: Pick<Job, "id" | "title">) => void;
  onNotes: (job: Pick<Job, "id" | "application_submission_notes">) => void;
  onCopy: (text: string, label: string) => void;
  onResolveBlocker: (job: Pick<Job, "id">, blockerType: string, fields: Record<string, unknown>) => void;
  onNoteBlocker: (job: Pick<Job, "id">, blockerType: string) => void;
  onOverrideReady: (job: Pick<Job, "id">) => void;
}) {
  const link = jobLink(job);
  const exportCommand = `python scripts/export_application_packet.py --job-id ${job.id}`;
  return (
    <article className="job-card">
      <div className="job-head">
        <div>
          <h3>{job.title}</h3>
          <p className="muted">{job.company} | {job.location} | {job.source}</p>
          <p className="muted">
            Posted {job.source_posted_at || "unknown"}
            {job.source_closes_at ? ` | closes ${job.source_closes_at}` : ""}
            {job.close_days_remaining !== null && job.close_days_remaining !== undefined ? ` | ${job.close_days_remaining} days left` : ""}
          </p>
          <p className="muted">{job.recommendation_reason}</p>
          <p><strong>{priorityLabel(job.application_priority)}</strong>{job.application_priority_reason ? ` - ${job.application_priority_reason}` : ""}</p>
          {job.application_blockers?.length ? <p className="muted">Blockers: {job.application_blockers.join(", ")}</p> : null}
          {job.next_action ? <p className="muted">Next: {job.next_action}</p> : null}
        </div>
        <div className="score"><strong>{job.match_score}</strong><span>{scoreBand(job)}</span></div>
      </div>
      <div className="chips">
        <span className="chip green">{priorityLabel(job.application_priority)}</span>
        <span className="chip green">{scoreBand(job)}</span>
        <span className="chip">{job.freshness_bucket || "unknown"}</span>
        <span className="chip">{job.packet_status}</span>
        <span className="chip">{job.link_ready ? "Link ready" : "Link missing"}</span>
        <span className="chip">{job.document_ready ? "Docs ready" : "Docs need review"}</span>
        <span className="chip">{job.review_status || "unreviewed"}</span>
        <SampleJobBadge job={job} />
        <SourceAttribution job={job} />
        <LinkNotice job={job} />
      </div>
      <Blockers job={job} onResolveBlocker={onResolveBlocker} onNoteBlocker={onNoteBlocker} />
      <div className="actions">
        <Link className="button" href={`/jobs/${job.id}`}>View Details</Link>
        <button className="button warning" onClick={() => onGeneratePacket(job)}>Generate Packet</button>
        <Link className="button" href={`/jobs/${job.id}`}>View Packet</Link>
        <button className="button" onClick={() => onCopy(exportCommand, "export command")}>Export Packet</button>
        {link ? <a className="button primary" href={link} target="_blank">Open Apply Link</a> : null}
        <button className="button" onClick={() => onReview(job, "interested")}>Mark Interested</button>
        <button className="button" onClick={() => onStarted(job)}>Mark Started</button>
        <button className="button" onClick={() => onApplied(job)}>Mark Applied</button>
        <button className="button" onClick={() => onNotes(job)}>Add Notes</button>
        <button className="button warning" onClick={() => onOverrideReady(job)}>Override to Ready to Apply</button>
      </div>
      <p className="muted">Manual override does not apply automatically. It only marks this job ready for your review.</p>
    </article>
  );
}

function Blockers({
  job,
  onResolveBlocker,
  onNoteBlocker,
}: {
  job: ApplyTodayJob;
  onResolveBlocker: (job: Pick<Job, "id">, blockerType: string, fields: Record<string, unknown>) => void;
  onNoteBlocker: (job: Pick<Job, "id">, blockerType: string) => void;
}) {
  const rows = job.blockers || [];
  if (!rows.length) return null;
  return (
    <div>
      <h4>Blockers</h4>
      {["hard_blocker", "review_needed", "soft_warning"].map((severity) => {
        const items = rows.filter((blocker) => blocker.severity === severity && !blocker.resolved);
        return items.length ? (
          <div key={severity}>
            <p className="muted">{severity.replaceAll("_", " ")}</p>
            {items.map((blocker) => (
              <div className="blocker-row" key={`${blocker.blocker_type}-${blocker.evidence_text}`}>
                <p><strong>{blocker.label || blocker.blocker_type}</strong>: {blocker.evidence_text}</p>
                <p className="muted">Source: {blocker.source_field}</p>
                <div className="actions">
                  <button className="button" onClick={() => onResolveBlocker(job, blocker.blocker_type, { resolved: true, resolution_note: "Cleared from Apply Today." })}>Clear blocker</button>
                  <button className="button" onClick={() => onResolveBlocker(job, blocker.blocker_type, { not_applicable: true, resolution_note: "Marked not applicable." })}>Mark not applicable</button>
                  <button className="button" onClick={() => onNoteBlocker(job, blocker.blocker_type)}>Add note</button>
                </div>
              </div>
            ))}
          </div>
        ) : null;
      })}
    </div>
  );
}

function priorityLabel(value?: string) {
  if (value === "apply_now") return "Apply Now";
  if (value === "review_first") return "Review First";
  if (value === "skip") return "Skip";
  return "Maybe";
}

function ApplicationJobCard({
  job,
  onOpenApply,
  onStarted,
  onApplied,
  onFollowUp,
  onFollowUpSent,
  onNotes,
  onCopy,
}: {
  job: Job;
  onOpenApply: (job: Job) => void;
  onStarted: (job: Job) => void;
  onApplied: (job: Job) => void;
  onFollowUp: (job: Job) => void;
  onFollowUpSent: (job: Job) => void;
  onNotes: (job: Job) => void;
  onCopy: (text: string, label: string) => void;
}) {
  const packetExists = Boolean(job.application_packet_dir || job.packet_generated_at || !job.needs_packet);
  const link = jobLink(job);
  return (
    <article className="job-card">
      <div className="job-head">
        <div>
          <h3>{job.title}</h3>
          <p className="muted">{job.company} | {job.source}</p>
          <p className="muted">
            Closes {job.source_closes_at || "unknown"} | applied {job.applied_at || "not yet"} | follow-up {job.follow_up_due_at || "not set"}
          </p>
          <p className="muted">Method: {job.application_method || "not set"} | Packet: {packetExists ? "available" : "not generated"}</p>
          <p className="muted">Export: python scripts/export_application_packet.py --job-id {job.id}</p>
        </div>
        <div className="score"><strong>{job.match_score}</strong><span>{scoreBand(job)}</span></div>
      </div>
      <div className="chips">
        <span className="chip green">{job.outcome_status || "not_started"}</span>
        <span className="chip">{job.status}</span>
        <span className="chip">{scoreBand(job)}</span>
        <SampleJobBadge job={job} />
        <SourceAttribution job={job} />
        <LinkNotice job={job} />
      </div>
      <div className="actions">
        <Link className="button" href={`/jobs/${job.id}`}>View Details</Link>
        {link ? <button className="button" onClick={() => onOpenApply(job)}>Open Apply Link</button> : null}
        <Link className="button" href={`/jobs/${job.id}`}>View Packet</Link>
        <button className="button" disabled={!job.generated_cover_letter} onClick={() => onCopy(job.generated_cover_letter, "cover letter")}>Copy Cover Letter</button>
        <button className="button" disabled={!job.generated_followup_email} onClick={() => onCopy(job.generated_followup_email, "follow-up email")}>Copy Follow-Up Email</button>
        <button className="button" onClick={() => onStarted(job)}>Mark Started</button>
        <button className="button" onClick={() => onApplied(job)}>Mark Applied</button>
        <button className="button" onClick={() => onFollowUp(job)}>Set Follow-Up Date</button>
        <button className="button" onClick={() => onFollowUpSent(job)}>Mark Follow-Up Sent</button>
        <button className="button" onClick={() => onNotes(job)}>Add Submission Notes</button>
      </div>
    </article>
  );
}

function ActivationChecklist({ source }: { source: Source }) {
  return (
    <div className="muted">
      <br />
      Credentials present: {credentialsPresent(source)}
      <br />
      Source enabled: {source.enabled ? "yes" : "no"}
      <br />
      Validation status: {source.validation_status || "unknown"}
      <br />
      Last sampled jobs: {source.jobs_sampled ?? 0}
      <br />
      Next action: {nextSourceAction(source)}
    </div>
  );
}

function reportTimestamp(report: DailyReport | null) {
  return report?.text.match(/Refresh timestamp: (.+)/)?.[1] || report?.date || "not generated";
}

function DailyDigest({ report }: { report: DailyReport | null }) {
  const summary = report?.summary || {};
  return (
    <section className="settings-section">
      <h3>Latest Daily Digest</h3>
      <p className="muted">Last refresh: {reportTimestamp(report)}</p>
      <div className="stats">
        <div className="stat"><strong>{summary.new_jobs_inserted ?? 0}</strong><span>New jobs</span></div>
        <div className="stat"><strong>{summary.high_match_unreviewed_jobs ?? 0}</strong><span>High match unreviewed</span></div>
        <div className="stat"><strong>{summary.closing_soon_jobs ?? 0}</strong><span>Closing soon</span></div>
        <div className="stat"><strong>{summary.packet_ready_jobs ?? summary.packets_ready ?? 0}</strong><span>Packet ready</span></div>
        <div className="stat"><strong>{summary.follow_up_due_jobs ?? 0}</strong><span>Follow-up due</span></div>
        <div className="stat"><strong>{summary.source_errors ?? 0}</strong><span>Source errors</span></div>
      </div>
      <details>
        <summary className="button">View Latest Report</summary>
        <pre>{report?.text || (dataModeLabel() === "Live API" ? "No hosted report generated yet. Live stats and review queue counts are still available." : "No daily review report has been generated yet.")}</pre>
      </details>
    </section>
  );
}

function ReviewFilterBar({
  filters,
  setFilters,
}: {
  filters: ReviewFilters;
  setFilters: (filters: ReviewFilters) => void;
}) {
  const rows: Array<[keyof ReviewFilters, string]> = [
    ["freshOnly", "Fresh only"],
    ["highMatchOnly", "High match only"],
    ["closingSoon", "Closing soon"],
    ["unreviewedOnly", "Unreviewed only"],
    ["includeStale", "Include stale"],
  ];
  return (
    <div className="toolbar">
      {rows.map(([key, label]) => (
        <label className="check-row" key={key}>
          <input type="checkbox" checked={filters[key]} onChange={(event) => setFilters({ ...filters, [key]: event.target.checked })} />
          {label}
        </label>
      ))}
    </div>
  );
}

function ReviewGroup({
  title,
  jobs,
  onReview,
  onStatus,
  onGeneratePacket,
}: {
  title: string;
  jobs: Job[];
  onReview: (job: Job, reviewStatus: string) => void;
  onStatus: (job: Job, status: string) => void;
  onGeneratePacket: (job: Job) => void;
}) {
  return (
    <section>
      <h3>{title}</h3>
      <div className="jobs-grid">
        {jobs.map((job) => (
          <ReviewJobCard job={job} key={`${title}-${job.id}`} onReview={onReview} onStatus={onStatus} onGeneratePacket={onGeneratePacket} />
        ))}
        {!jobs.length && <p className="muted">No jobs in this group.</p>}
      </div>
    </section>
  );
}

function ReviewJobCard({
  job,
  onReview,
  onStatus,
  onGeneratePacket,
}: {
  job: Job;
  onReview: (job: Job, reviewStatus: string) => void;
  onStatus: (job: Job, status: string) => void;
  onGeneratePacket: (job: Job) => void;
}) {
  const closeDays = job.close_days_remaining ?? daysUntil(job.source_closes_at);
  const link = jobLink(job);
  return (
    <article className="job-card">
      <div className="job-head">
        <div>
          <h3>{job.title}</h3>
          <p className="muted">{job.company} | {job.location} | {job.source}</p>
          <p className="muted">
            Posted {job.source_posted_at || job.date_posted || "unknown"} | first seen {job.first_seen_at || job.date_found}
            {job.source_closes_at ? ` | closes ${job.source_closes_at}` : ""}
            {closeDays !== null && closeDays !== undefined ? ` | ${closeDays} days left` : ""}
          </p>
        </div>
        <div className="score"><strong>{job.match_score}</strong><span>{scoreBand(job)}</span></div>
      </div>
      <div className="chips">
        <span className="chip green">{job.review_status || "unreviewed"}</span>
        <span className="chip green">{scoreBand(job)}</span>
        <span className="chip">{job.priority_bucket || "medium"}</span>
        <SampleJobBadge job={job} />
        <SourceAttribution job={job} />
        <LinkNotice job={job} />
        <FreshnessChips job={job} />
        {job.fit_reasons?.[0] && <span className="chip">{job.fit_reasons[0]}</span>}
      </div>
      <div className="actions">
        <Link className="button" href={`/jobs/${job.id}`}>View Details</Link>
        <button className="button" onClick={() => onReview(job, "interested")}>Interested</button>
        <button className="button" onClick={() => onReview(job, "maybe")}>Maybe</button>
        <button className="button" onClick={() => onReview(job, "not_interested")}>Not Interested</button>
        <button className="button warning" onClick={() => onGeneratePacket(job)}>Generate Packet</button>
        <button className="button" onClick={() => onStatus(job, "ready_to_apply")}>Mark Ready to Apply</button>
        <button className="button" onClick={() => onStatus(job, "applied")}>Mark Applied</button>
        {link ? <a className="button primary" href={link} target="_blank">Open Apply Link</a> : null}
      </div>
    </article>
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

function Header({
  title,
  onRefresh,
  message,
  meta,
}: {
  title: string;
  onRefresh: () => void;
  message: string;
  meta: { mode: string; apiUrl: string; sourceCount: string; lastRefresh: string };
}) {
  return (
    <>
      <div className="topbar">
        <div>
          <p className="eyebrow">Human approval required before applying</p>
          <h2>{title}</h2>
          <div className="chips">
            <span className={meta.mode === "Demo Mode" ? "chip warning" : "chip green"}>{meta.mode}</span>
            {meta.mode !== "Demo Mode" && meta.apiUrl && <span className="chip">{meta.apiUrl}</span>}
            <span className="chip">{meta.sourceCount === "loading" ? "Loading sources" : `${meta.sourceCount} sources`}</span>
            <span className="chip">Last refresh: {meta.lastRefresh}</span>
          </div>
        </div>
        {meta.mode === "Live API" ? (
          <div>
            <button className="button primary" disabled>Hosted refresh admin-only</button>
            <p className="muted">Run the admin refresh script or scheduled backend refresh.</p>
          </div>
        ) : (
          <button className="button primary" onClick={onRefresh}>Refresh Jobs</button>
        )}
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
  const link = jobLink(job);
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
        <div className="score"><strong>{job.match_score}</strong><span>{scoreBand(job)}</span></div>
      </div>
      <div className="chips">
        <span className="chip green">{job.status}</span>
        <span className="chip green">{scoreBand(job)}</span>
        <SampleJobBadge job={job} />
        <SourceAttribution job={job} />
        <LinkNotice job={job} />
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
        {link ? <a className="button" href={link} target="_blank">Open Apply Link</a> : null}
        <button className="button" disabled={!job.generated_cover_letter} onClick={() => onCopy(job.generated_cover_letter, "cover letter")}>Copy Cover Letter</button>
        <button className="button" disabled={!job.generated_followup_email} onClick={() => onCopy(job.generated_followup_email, "follow-up email")}>Copy Follow-Up Email</button>
      </div>
    </article>
  );
}
