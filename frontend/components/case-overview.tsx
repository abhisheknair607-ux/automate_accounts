"use client";

import Link from "next/link";
import { useEffect, useState, useTransition } from "react";

import { CaseNav } from "@/components/case-nav";
import { StatusPill } from "@/components/status-pill";
import { api } from "@/lib/api";
import type { CaseDetail } from "@/lib/types";


export function CaseOverview({ caseId }: { caseId: string }) {
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const load = async () => {
    try {
      setError(null);
      setDetail(await api.getCase(caseId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load case");
    }
  };

  useEffect(() => {
    load();
  }, [caseId]);

  const trigger = (label: string, action: () => Promise<unknown>) => {
    startTransition(async () => {
      try {
        setBusyAction(label);
        await action();
        await load();
      } catch (err) {
        setError(err instanceof Error ? err.message : `Failed to ${label.toLowerCase()}`);
      } finally {
        setBusyAction(null);
      }
    });
  };

  if (error && !detail) {
    return <p className="error-banner">{error}</p>;
  }

  if (!detail) {
    return <p className="muted">Loading case...</p>;
  }

  return (
    <div className="case-shell">
      <header className="hero-card">
        <div>
          <span className="eyebrow">Review Workspace</span>
          <h1>{detail.name || detail.id}</h1>
          <p>Document ingestion, extraction, reconciliation, and raw OCR plus P&amp;L exports all stay in one case timeline.</p>
        </div>
        <div className="hero-metrics">
          <div>
            <small>Status</small>
            <StatusPill value={detail.status} />
          </div>
          <div>
            <small>Documents</small>
            <strong>{detail.document_count}</strong>
          </div>
          <div>
            <small>Open issues</small>
            <strong>{detail.open_issue_count}</strong>
          </div>
        </div>
      </header>

      <CaseNav caseId={caseId} />

      <section className="dashboard-grid">
        <div className="panel">
          <div className="panel-head">
            <span className="eyebrow">Workflow</span>
            <h2>Run the MVP pipeline</h2>
          </div>
          <div className="action-row">
            <button className="primary-button" disabled={isPending} onClick={() => trigger("Extract documents", () => api.extractCase(caseId))}>
              {busyAction === "Extract documents" ? "Extracting..." : "1. Extract documents"}
            </button>
            <button className="secondary-button" disabled={isPending} onClick={() => trigger("Reconcile case", () => api.reconcileCase(caseId))}>
              {busyAction === "Reconcile case" ? "Reconciling..." : "2. Reconcile case"}
            </button>
            <button
              className="secondary-button"
              disabled={isPending}
              onClick={() => trigger("Create reconciliation export", () => api.createExport(caseId, "reco_excel"))}
            >
              {busyAction === "Create reconciliation export" ? "Exporting..." : "3. Create reconciliation Excel"}
            </button>
            <button
              className="secondary-button"
              disabled={isPending}
              onClick={() => trigger("Create raw OCR export", () => api.createExport(caseId, "ocr_excel"))}
            >
              {busyAction === "Create raw OCR export" ? "Exporting..." : "4. Create raw OCR Excel"}
            </button>
            <button
              className="secondary-button"
              disabled={isPending}
              onClick={() => trigger("Create P&L export", () => api.createExport(caseId, "pnl_csv"))}
            >
              {busyAction === "Create P&L export" ? "Exporting..." : "5. Create P&L CSV"}
            </button>
          </div>
          {error ? <p className="error-banner">{error}</p> : null}
        </div>

        <div className="panel">
          <div className="panel-head">
            <span className="eyebrow">Documents</span>
            <h2>Case assets</h2>
          </div>
          <div className="document-list">
            {detail.documents.map((document) => (
              <div className="document-row" key={document.id}>
                <div>
                  <strong>{document.source_filename}</strong>
                  <p>{document.doc_type}</p>
                </div>
                <StatusPill value={document.extraction_status} />
              </div>
            ))}
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">
            <span className="eyebrow">Review</span>
            <h2>Direct navigation</h2>
          </div>
          <div className="link-stack">
            <Link href={`/cases/${caseId}/invoice`}>Open extracted invoice</Link>
            <Link href={`/cases/${caseId}/docket`}>Open extracted delivery docket</Link>
            <Link href={`/cases/${caseId}/reconciliation`}>Open reconciliation results</Link>
            <Link href={`/cases/${caseId}/exceptions`}>Open exception review</Link>
            <Link href={`/cases/${caseId}/exports`}>Open exports</Link>
          </div>
        </div>
      </section>
    </div>
  );
}
