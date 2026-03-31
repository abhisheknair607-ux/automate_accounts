import { CaseDetail, CaseSummary } from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.headers || {})
    }
  });

  if (!response.ok) {
    let message = `Request failed with ${response.status}`;
    try {
      const payload = await response.json();
      message = payload.detail || message;
    } catch {}
    throw new Error(message);
  }

  return (await response.json()) as T;
}

export const api = {
  listCases: () => request<CaseSummary[]>("/cases"),
  getCase: (caseId: string) => request<CaseDetail>(`/cases/${caseId}`),
  getInvoice: (caseId: string) => request<Record<string, unknown>>(`/cases/${caseId}/invoice`),
  getDocket: (caseId: string) => request<Record<string, unknown>>(`/cases/${caseId}/delivery-docket`),
  getReconciliation: (caseId: string) =>
    request<Record<string, unknown>>(`/cases/${caseId}/reconciliation`),
  getExceptions: (caseId: string) => request<Record<string, unknown>>(`/cases/${caseId}/exceptions`),
  getExports: (caseId: string) => request<Record<string, unknown>[]>(`/cases/${caseId}/exports`),
  uploadCase: async (formData: FormData) =>
    request<CaseDetail>("/cases/uploads", {
      method: "POST",
      body: formData
    }),
  extractCase: (caseId: string) =>
    request<Record<string, unknown>>(`/cases/${caseId}/extract`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ force: true })
    }),
  reconcileCase: (caseId: string) =>
    request<Record<string, unknown>>(`/cases/${caseId}/reconcile`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({})
    }),
  createExport: (caseId: string, exportFormat: "csv" | "json" | "reco_csv" | "reco_excel" | "ocr_excel" | "pnl_csv" = "csv") =>
    request<Record<string, unknown>>(`/exports/cases/${caseId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ export_format: exportFormat })
    }),
  exportDownloadUrl: (exportId: string) => `${API_BASE}/exports/${exportId}/download`
};
