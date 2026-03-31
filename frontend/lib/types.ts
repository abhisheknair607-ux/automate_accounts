export type DocumentSummary = {
  id: string;
  case_id: string;
  doc_type: string;
  source_filename: string;
  mime_type?: string | null;
  file_size_bytes: number;
  classification_confidence?: number | null;
  extraction_status: string;
  latest_provider?: string | null;
  low_confidence_fields?: Record<string, unknown>[] | null;
  created_at: string;
  updated_at: string;
};

export type CaseSummary = {
  id: string;
  name?: string | null;
  status: string;
  priority: string;
  created_at: string;
  updated_at: string;
  document_count: number;
  open_issue_count: number;
  latest_reconciliation_status?: string | null;
};

export type CaseDetail = CaseSummary & {
  documents: DocumentSummary[];
  invoice?: Record<string, unknown> | null;
  delivery_docket?: Record<string, unknown> | null;
  latest_reconciliation?: Record<string, unknown> | null;
  latest_exception_case?: Record<string, unknown> | null;
  exports: Record<string, unknown>[];
};
