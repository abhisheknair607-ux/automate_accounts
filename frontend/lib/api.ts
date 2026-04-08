import { CaseDetail, CaseSummary } from "@/lib/types";
import type { ReconciliationConfigInput } from "@/lib/reconciliation-config";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api";
const TUNNEL_BYPASS_HEADER = "bypass-tunnel-reminder";

function buildHeaders(init?: RequestInit): HeadersInit {
  const headers = new Headers(init?.headers || {});

  if (API_BASE.includes(".loca.lt")) {
    headers.set(TUNNEL_BYPASS_HEADER, "true");
  }

  return headers;
}

async function extractErrorMessage(response: Response): Promise<string> {
  const contentType = response.headers.get("content-type") || "";

  if (contentType.includes("application/json")) {
    try {
      const payload = (await response.json()) as { detail?: string };
      return payload.detail || `Request failed with ${response.status}`;
    } catch {
      return `Request failed with ${response.status}`;
    }
  }

  try {
    const text = await response.text();
    return text || `Request failed with ${response.status}`;
  } catch {
    return `Request failed with ${response.status}`;
  }
}

function inferDownloadFilename(response: Response, exportId: string): string {
  const contentDisposition = response.headers.get("content-disposition") || "";
  const filenameMatch = contentDisposition.match(/filename="?([^"]+)"?/i);

  if (filenameMatch?.[1]) {
    return filenameMatch[1];
  }

  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("spreadsheetml")) {
    return `${exportId}.xlsx`;
  }
  if (contentType.includes("text/html")) {
    return `${exportId}.html`;
  }
  if (contentType.includes("json")) {
    return `${exportId}.json`;
  }
  if (contentType.includes("text/csv")) {
    return `${exportId}.csv`;
  }
  return `${exportId}.csv`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: buildHeaders(init)
  });

  if (!response.ok) {
    throw new Error(await extractErrorMessage(response));
  }

  return (await response.json()) as T;
}

async function downloadExport(exportId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/exports/${exportId}/download`, {
    headers: buildHeaders()
  });

  if (!response.ok) {
    throw new Error(await extractErrorMessage(response));
  }

  const blob = await response.blob();
  const downloadUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");

  link.href = downloadUrl;
  link.download = inferDownloadFilename(response, exportId);
  document.body.appendChild(link);
  link.click();
  link.remove();

  URL.revokeObjectURL(downloadUrl);
}

export const api = {
  listCases: () => request<CaseSummary[]>("/cases"),
  getCase: (caseId: string) => request<CaseDetail>(`/cases/${caseId}`),
  getInvoice: (caseId: string) => request<Record<string, unknown>>(`/cases/${caseId}/invoice`),
  updateInvoice: (
    caseId: string,
    rows: {
      supplier: string;
      product_code: string;
      product_name: string;
      quantity_invoice: string;
      pre_amount_invoice: string;
      vat_invoice: string;
      total_invoice: string;
    }[]
  ) =>
    request<Record<string, unknown>>(`/cases/${caseId}/invoice`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rows })
    }),
  getDocket: (caseId: string) => request<Record<string, unknown>>(`/cases/${caseId}/delivery-docket`),
  updateDocket: (
    caseId: string,
    rows: {
      supplier: string;
      product_code: string;
      product_name: string;
      quantity_docket: string;
      amount_docket: string;
    }[]
  ) =>
    request<Record<string, unknown>>(`/cases/${caseId}/delivery-docket`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rows })
    }),
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
  reconcileCase: (
    caseId: string,
    config?: ReconciliationConfigInput
  ) =>
    request<Record<string, unknown>>(`/cases/${caseId}/reconcile`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(config ? { config } : {})
    }),
  applyManualReconciliation: (
    caseId: string,
    requestBody: {
      base_reconciliation_run_id: string;
      config?: ReconciliationConfigInput;
      pairs: {
        invoice_line_number: number;
        docket_line_number: number;
        position: number;
      }[];
    }
  ) =>
    request<Record<string, unknown>>(`/cases/${caseId}/reconciliation/manual`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestBody)
    }),
  createExport: (caseId: string, exportFormat: "csv" | "json" | "reco_csv" | "reco_excel" | "ocr_excel" | "ocr_html" | "pnl_csv" = "csv") =>
    request<Record<string, unknown>>(`/exports/cases/${caseId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ export_format: exportFormat })
    }),
  downloadExport
};
