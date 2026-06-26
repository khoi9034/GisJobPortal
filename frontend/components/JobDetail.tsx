"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, ApplicationPacket, DocumentChecklist, Job } from "../lib/api";

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
    setMessage("Application packet generated.");
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
        </div>
        <div className="score"><strong>{job.match_score}</strong><span>match</span></div>
      </div>
      <div className="toolbar">
        <Link className="button" href="/">Back</Link>
        <button className="button" onClick={() => updateStatus("saved")}>Save</button>
        <button className="button" onClick={() => updateStatus("skipped")}>Skip</button>
        <button className="button" onClick={() => updateStatus("ready_to_apply")}>Mark Ready to Apply</button>
        <button className="button" onClick={() => updateStatus("applied")}>Mark Applied</button>
        <button className="button" onClick={() => updateStatus("follow_up_needed")}>Mark Follow-Up Needed</button>
        <button className="button" onClick={score}>Rescore</button>
        <button className="button warning" onClick={generate}>Generate Application Packet</button>
        <button className="button" onClick={viewPacket}>View Application Packet</button>
        <a className="button primary" href={job.apply_url} target="_blank">Open Apply Link</a>
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
          <h3>Document Checklist</h3>
          <Checklist checklist={checklist} setChecklist={setChecklist} />
          <button className="button" onClick={saveChecklist}>Save Checklist</button>
          <h3>Scoring Breakdown</h3>
          {Object.entries(job.scoring_breakdown || {}).map(([key, value]) => (
            <p key={key}><strong>{key.replaceAll("_", " ")}</strong>: {value}</p>
          ))}
          <h3>Keyword Matches</h3>
          <div className="chips">{job.keyword_matches.map((item) => <span className="chip green" key={item}>{item}</span>)}</div>
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
