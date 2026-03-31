"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { CaseNav } from "@/components/case-nav";
import { StatusPill } from "@/components/status-pill";
import { api } from "@/lib/api";

type Section = "invoice" | "docket" | "reconciliation" | "exceptions" | "exports";

const endpointMap: Record<Section, (caseId: string) => Promise<unknown>> = {
  invoice: (caseId) => api.getInvoice(caseId),
  docket: (caseId) => api.getDocket(caseId),
  reconciliation: (caseId) => api.getReconciliation(caseId),
  exceptions: (caseId) => api.getExceptions(caseId),
  exports: (caseId) => api.getExports(caseId)
};

const titles: Record<Section, { eyebrow: string; heading: string; description: string }> = {
  invoice: {
    eyebrow: "Invoice Extraction",
    heading: "Canonical invoice payload",
    description: "Header, line items, VAT, discount, department, and delivery summaries all normalize into the internal schema."
  },
  docket: {
    eyebrow: "Docket Extraction",
    heading: "Canonical delivery docket payload",
    description: "This view focuses on the delivery-side fields used by the reconciliation engine."
  },
  reconciliation: {
    eyebrow: "Reconciliation",
    heading: "Rule results and line comparisons",
    description: "Tolerance-based approval, mismatch reasons, and low-confidence flags are all surfaced here."
  },
  exceptions: {
    eyebrow: "Exception Review",
    heading: "Review queue",
    description: "Blocking mismatches and low-confidence extraction items are grouped into a lightweight exception workflow."
  },
  exports: {
    eyebrow: "Exports",
    heading: "Export history",
    description: "Reconciliation workbooks, raw OCR workbooks, and built-in P&L CSV outputs are all available from the same case."
  }
};

export function CaseSectionView({ caseId, section }: { caseId: string; section: Section }) {
  const [payload, setPayload] = useState<unknown>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    endpointMap[section](caseId).then(setPayload).catch((err) => setError(err.message));
  }, [caseId, section]);

  const meta = titles[section];

  return (
    <div className="case-shell">
      <header className="hero-card">
        <div>
          <span className="eyebrow">{meta.eyebrow}</span>
          <h1>{meta.heading}</h1>
          <p>{meta.description}</p>
        </div>
        <Link className="ghost-link" href={`/cases/${caseId}`}>
          Back to overview
        </Link>
      </header>

      <CaseNav caseId={caseId} />

      {error ? <p className="error-banner">{error}</p> : null}
      {!payload && !error ? <p className="muted">Loading {section}...</p> : null}

      {Array.isArray(payload) ? (
        <section className="panel">
          <div className="panel-head">
            <h2>Records</h2>
          </div>
          {payload.length === 0 ? <p className="muted">No records yet.</p> : null}
          <div className="stack">
            {payload.map((item, index) => {
              const exportId = (item as Record<string, unknown>).id as string | undefined;
              return (
                <div className="json-card" key={exportId || index}>
                  <div className="json-card-head">
                    <strong>{(item as Record<string, unknown>).export_format?.toString() || `Record ${index + 1}`}</strong>
                    {exportId ? <StatusPill value={(item as Record<string, unknown>).status as string} /> : null}
                  </div>
                  {exportId ? (
                    <button
                      className="ghost-link"
                      onClick={() =>
                        api.downloadExport(exportId).catch((err) =>
                          setError(err instanceof Error ? err.message : "Failed to download export")
                        )
                      }
                    >
                      Download export
                    </button>
                  ) : null}
                  <pre>{JSON.stringify(item, null, 2)}</pre>
                </div>
              );
            })}
          </div>
        </section>
      ) : null}

      {!Array.isArray(payload) && payload ? (
        <section className="panel">
          <div className="panel-head">
            <h2>Payload</h2>
          </div>
          <pre className="json-dump">{JSON.stringify(payload, null, 2)}</pre>
        </section>
      ) : null}
    </div>
  );
}
