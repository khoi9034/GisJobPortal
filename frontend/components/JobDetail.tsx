"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, ApplicationPacket, DocumentChecklist, Job } from "../lib/api";

function daysUntil(value?: string) {
  if (!value) return null;
  return Math.ceil((new Date(`${value.slice(0, 10)}T00:00:00`).getTime() - Date.now()) / 86400000);
}

function isClosingSoon(job: Job) {
  const days = daysUntil(job.source_closes_at);
  return days !== null && days >= 0 && days <= 7;
}

function scoreBand(job: Job) {
  if (job.score_band) return job.score_band;
  if (job.match_score >= 85) return "excellent fit";
  if (job.match_score >= 70) return "strong fit";
  if (job.match_score >= 55) return "possible fit";
  if (job.match_score >= 40) return "weak/maybe";
  return "low fit";
}

function sampleJobBadge(job: Job) {
  return job.source === "Sample GIS Jobs" ? <span className="chip warning">Demo sample job — not a live posting</span> : null;
}

export default function JobDetail({ id }: { id: string }) {
  const [job, setJob] = useState<Job | null>(null);
  const [packet, setPacket] = useState<ApplicationPacket | null>(null);
  const [checklist, setChecklist] = useState<DocumentChecklist>({});
  const [notes, setNotes] = useState("");
  const [message, setMessage] = useState("");

  async function load() {
    const row = await api<Job>(`/jobs/${id}`);
    setJob(row);
    setNotes(row.notes || "");
    setChecklist(row.document_checklist || {});
  }

  useEffect(() => {
    load().catch((error) => setMessage(error.message));
  }, [id]);

  async function updateStatus(status: string) {
    await api<Job>(`/jobs/${id}/status`, { method: "PATCH", body: JSON.stringify({ status }) });
    await load();
  }

  async function updateApplication(fields: Partial<Job>) {
    await api<Job>(`/jobs/${id}/application`, { method: "PATCH", body: JSON.stringify(fields) });
    await load();
  }

  async function markStarted() {
    await api<Job>(`/jobs/${id}/mark-application-started`, { method: "POST" });
    await load();
  }

  async function markApplied() {
    await api<Job>(`/jobs/${id}/mark-applied`, { method: "POST" });
    await load();
  }

  async function markFollowUpSent() {
    await api<Job>(`/jobs/${id}/mark-follow-up-sent`, { method: "POST" });
    await load();
  }

  async function openApply() {
    window.open(job?.apply_url, "_blank", "noopener,noreferrer");
    await updateApplication({ application_url_opened_at: new Date().toISOString().slice(0, 10) });
  }

  async function setFollowUpDate() {
    const value = window.prompt("Follow-up due date (YYYY-MM-DD)", job?.follow_up_due_at || "");
    if (value !== null) await updateApplication({ follow_up_due_at: value, outcome_status: value ? "follow_up_due" : job?.outcome_status });
  }

  async function addSubmissionNotes() {
    const value = window.prompt("Submission notes", job?.application_submission_notes || "");
    if (value !== null) await updateApplication({ application_submission_notes: value });
  }

  async function saveNotes() {
    await api<Job>(`/jobs/${id}/notes`, { method: "PATCH", body: JSON.stringify({ notes }) });
    setMessage("Notes saved.");
    await load();
  }

  async function score() {
    await api<Job>(`/jobs/${id}/score`, { method: "POST" });
    setMessage("Score refreshed.");
    await load();
  }

  async function generate() {
    const row = await api<ApplicationPacket>(`/jobs/${id}/generate-application-packet`, { method: "POST" });
    setPacket(row);
    setChecklist(row.document_checklist || {});
    setMessage(row.generation_mode === "pony_alpha" ? "Generated with Pony Alpha." : "Generated with template fallback.");
    await load();
  }

  async function viewPacket() {
    const row = await api<ApplicationPacket>(`/jobs/${id}/application-packet`);
    setPacket(row);
    setChecklist(row.document_checklist || checklist);
    setMessage(row.exists ? "Application packet loaded." : "No packet generated yet.");
  }

  async function saveChecklist() {
    const row = await api<Job>(`/jobs/${id}/document-checklist`, {
      method: "PATCH",
      body: JSON.stringify({ checklist }),
    });
    setJob(row);
    setChecklist(row.document_checklist || {});
    setMessage("Document checklist saved.");
  }

  async function copy(text: string, label: string) {
    await navigator.clipboard.writeText(text);
    setMessage(`Copied ${label}.`);
  }

  if (!job) {
    return (
      <main className="main">
        <Link className="button" href="/">Back</Link>
        <p className="muted">{message || "Loading job..."}</p>
      </main>
    );
  }

  return (
    <main className="main">
      <div className="topbar">
        <div>
          <p className="eyebrow">{job.status}</p>
          <h2>{job.title}</h2>
          <p className="muted">{job.company} | {job.location} | {job.source}</p>
          <p className="muted">
            Posted {job.source_posted_at || job.date_posted || "unknown"} | first seen {job.first_seen_at || job.date_found}
            {job.source_closes_at ? ` | closes ${job.source_closes_at}` : ""}
          </p>
          <div className="chips">
            <span className="chip">{job.freshness_bucket || "unknown"}</span>
            <span className="chip">{job.freshness_confidence || "unknown"}</span>
            {sampleJobBadge(job)}
            {job.is_stale && <span className="chip red">stale</span>}
            {isClosingSoon(job) && <span className="chip warning">closing soon</span>}
          </div>
        </div>
        <div className="score"><strong>{job.match_score}</strong><span>{scoreBand(job)}</span></div>
      </div>
      <div className="toolbar">
        <Link className="button" href="/">Back</Link>
        <button className="button" onClick={() => updateStatus("saved")}>Save</button>
        <button className="button" onClick={() => updateStatus("skipped")}>Skip</button>
        <button className="button" onClick={() => updateStatus("ready_to_apply")}>Mark Ready to Apply</button>
        <button className="button" onClick={markStarted}>Mark Started</button>
        <button className="button" onClick={markApplied}>Mark Applied</button>
        <button className="button" onClick={() => updateStatus("follow_up_needed")}>Mark Follow-Up Needed</button>
        <button className="button" onClick={setFollowUpDate}>Set Follow-Up Date</button>
        <button className="button" onClick={markFollowUpSent}>Mark Follow-Up Sent</button>
        <button className="button" onClick={score}>Rescore</button>
        <button className="button warning" onClick={generate}>Generate Application Packet</button>
        <button className="button" onClick={viewPacket}>View Application Packet</button>
        <button className="button" onClick={addSubmissionNotes}>Add Submission Notes</button>
        <button className="button primary" onClick={openApply}>Open Apply Link</button>
      </div>
      {message && <p className="muted">{message}</p>}

      <div className="detail-grid">
        <section className="detail-section">
          <h3>Description</h3>
          <p>{job.description}</p>
          <h3>Requirements</h3>
          <p>{job.requirements}</p>
          <h3>Generated Cover Letter</h3>
          <pre>{job.generated_cover_letter || "Generate materials to create a draft."}</pre>
          <button className="button" disabled={!job.generated_cover_letter} onClick={() => copy(job.generated_cover_letter, "cover letter")}>Copy Cover Letter</button>
          <h3>Generated Follow-Up Email</h3>
          <pre>{job.generated_followup_email || "Generate materials to create a draft."}</pre>
          <button className="button" disabled={!job.generated_followup_email} onClick={() => copy(job.generated_followup_email, "follow-up email")}>Copy Follow-Up Email</button>
          <h3>Recruiter Message</h3>
          <pre>{job.recruiter_message || "Generate materials to create a draft."}</pre>
          <button className="button" disabled={!job.recruiter_message} onClick={() => copy(job.recruiter_message, "recruiter message")}>Copy Recruiter Message</button>
          <PacketView packet={packet} />
        </section>

        <aside className="detail-section">
          <h3>Application Execution</h3>
          <p className="muted">Manual apply only. This app never logs in, submits applications, or sends emails.</p>
          <p><strong>Packet:</strong> {job.application_packet_dir || job.packet_generated_at ? "available" : "not generated"}</p>
          <p><strong>Export command:</strong></p>
          <pre>python scripts/export_application_packet.py --job-id {job.id}</pre>
          <p><strong>Started:</strong> {job.application_started_at || "not started"}</p>
          <p><strong>Applied:</strong> {job.applied_at || "not applied"}</p>
          <p><strong>Follow-up due:</strong> {job.follow_up_due_at || "not set"}</p>
          <p><strong>Follow-up sent:</strong> {job.follow_up_sent_at || "not sent"}</p>
          <p><strong>Method:</strong> {job.application_method || "not set"}</p>
          <p><strong>Confirmation:</strong> {job.application_confirmation_number || "not recorded"}</p>
          <h3>Manual Submission Checklist</h3>
          <ul>
            <li>Open apply link</li>
            <li>Upload resume manually</li>
            <li>Upload cover letter manually if required</li>
            <li>Upload transcript manually only if required</li>
            <li>Paste/check answers</li>
            <li>Submit manually outside the portal</li>
            <li>Record confirmation number and mark applied</li>
          </ul>
          <h3>Document Checklist</h3>
          <Checklist checklist={checklist} setChecklist={setChecklist} />
          <button className="button" onClick={saveChecklist}>Save Checklist</button>
          <h3>Scoring Breakdown</h3>
          <p>{job.score_reason || "Score explanation will appear after refresh/rescore."}</p>
          {Object.entries(job.scoring_breakdown || {}).map(([key, value]) => (
            <p key={key}><strong>{key.replaceAll("_", " ")}</strong>: {value}</p>
          ))}
          <h3>Positive Matches</h3>
          <div className="chips">{(job.positive_matches || job.keyword_matches || []).map((item) => <span className="chip green" key={item}>{item}</span>)}</div>
          <h3>Penalty Matches</h3>
          <div className="chips">{job.penalty_matches?.length ? job.penalty_matches.map((item) => <span className="chip red" key={item}>{item}</span>) : <span className="muted">None flagged.</span>}</div>
          <h3>Missing Skills</h3>
          <div className="chips">{job.missing_skills.length ? job.missing_skills.map((item) => <span className="chip red" key={item}>{item}</span>) : <span className="muted">None flagged.</span>}</div>
          <h3>Resume Angle</h3>
          <p>{job.recommended_resume_angle}</p>
          <h3>Resume Bullet Suggestions</h3>
          <ul>{job.resume_bullet_suggestions.map((item) => <li key={item}>{item}</li>)}</ul>
          <h3>Notes</h3>
          <textarea value={notes} onChange={(event) => setNotes(event.target.value)} />
          <button className="button" onClick={saveNotes}>Save Notes</button>
        </aside>
      </div>
    </main>
  );
}

function Checklist({
  checklist,
  setChecklist,
}: {
  checklist: DocumentChecklist;
  setChecklist: (checklist: DocumentChecklist) => void;
}) {
  const rows: Array<[keyof DocumentChecklist, string]> = [
    ["resume_required", "Resume required"],
    ["cover_letter_required", "Cover letter required"],
    ["transcript_required", "Transcript required"],
    ["portfolio_link_included", "Portfolio link included"],
    ["references_required", "References required"],
    ["writing_sample_required", "Writing sample required"],
  ];
  return (
    <div>
      {rows.map(([key, label]) => (
        <label className="check-row" key={key}>
          <input
            type="checkbox"
            checked={Boolean(checklist[key])}
            onChange={(event) => setChecklist({ ...checklist, [key]: event.target.checked })}
          />
          {label}
        </label>
      ))}
      <label className="muted" htmlFor="other-documents">Other documents</label>
      <textarea
        id="other-documents"
        value={checklist.other_documents || ""}
        onChange={(event) => setChecklist({ ...checklist, other_documents: event.target.value })}
      />
    </div>
  );
}

function PacketView({ packet }: { packet: ApplicationPacket | null }) {
  if (!packet) return null;
  return (
    <section>
      <h3>Application Packet</h3>
      <p className="muted">{packet.generation_mode === "pony_alpha" ? "Generated with Pony Alpha" : "Generated with template fallback"}</p>
      <p className="muted">{packet.packet_dir}</p>
      {Object.entries(packet.files).map(([name, content]) => (
        <details key={name}>
          <summary>{name}</summary>
          <pre>{content}</pre>
        </details>
      ))}
    </section>
  );
}
