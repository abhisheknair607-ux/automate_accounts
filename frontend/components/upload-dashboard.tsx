"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState, useTransition } from "react";

import { api } from "@/lib/api";
import type { CaseSummary } from "@/lib/types";
import { StatusPill } from "@/components/status-pill";


export function UploadDashboard() {
  const router = useRouter();
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    api.listCases().then(setCases).catch((err) => setError(err.message));
  }, []);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);

    startTransition(async () => {
      try {
        setError(null);
        const created = await api.uploadCase(form);
        const refreshed = await api.listCases();
        setCases(refreshed);
        router.push(`/cases/${created.id}`);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Upload failed");
      }
    });
  };

  return (
    <div className="dashboard-grid">
      <section className="panel">
        <div className="panel-head">
          <span className="eyebrow">Ingestion</span>
          <h2>Upload sample documents</h2>
          <p>Upload the invoice and delivery docket only. The backend applies a fixed P&amp;L template automatically during export.</p>
        </div>
        <form className="upload-form" onSubmit={handleSubmit}>
          <label>
            <span>Supplier invoice PDF</span>
            <input name="invoice" required type="file" accept=".pdf,application/pdf" />
          </label>
          <label>
            <span>Delivery docket image/PDF</span>
            <input name="delivery_docket" required type="file" accept=".pdf,.jpg,.jpeg,.png,image/*" />
          </label>
          <button className="primary-button" disabled={isPending} type="submit">
            {isPending ? "Uploading..." : "Create Case"}
          </button>
        </form>
        <p className="hint">
          The backend ships with a constant P&amp;L template plus mock extraction fixtures tied to the Musgrave sample documents, so the first run behaves like a complete end-to-end MVP without a live OCR subscription.
        </p>
        {error ? <p className="error-banner">{error}</p> : null}
      </section>

      <section className="panel">
        <div className="panel-head">
          <span className="eyebrow">Queue</span>
          <h2>Recent reconciliation cases</h2>
        </div>
        <div className="case-list">
          {cases.length === 0 ? <p className="muted">No cases yet. Upload the sample documents to start.</p> : null}
          {cases.map((caseItem) => (
            <Link key={caseItem.id} className="case-card" href={`/cases/${caseItem.id}`}>
              <div className="case-card-top">
                <strong>{caseItem.name || caseItem.id}</strong>
                <StatusPill value={caseItem.status} />
              </div>
              <p>{caseItem.document_count} documents, {caseItem.open_issue_count} open issues</p>
              <small>Last update: {new Date(caseItem.updated_at).toLocaleString()}</small>
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}
