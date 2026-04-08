"use client";

import Link from "next/link";
import { useEffect, useState, type DragEvent } from "react";

import { CaseNav } from "@/components/case-nav";
import { StatusPill } from "@/components/status-pill";
import { api } from "@/lib/api";
import {
  clearReconciliationConfig,
  DEFAULT_RECONCILIATION_CONFIG,
  loadReconciliationConfig,
  saveReconciliationConfig,
  type ReconciliationConfigInput
} from "@/lib/reconciliation-config";

type Section = "invoice" | "docket" | "reconciliation" | "exports";

const endpointMap: Record<Section, (caseId: string) => Promise<unknown>> = {
  invoice: (caseId) => api.getInvoice(caseId),
  docket: (caseId) => api.getDocket(caseId),
  reconciliation: (caseId) => api.getReconciliation(caseId),
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
    heading: "Manual reconciliation workspace",
    description: "Drag invoice and docket rows into merged matches, then apply them as the saved reconciliation source of truth."
  },
  exports: {
    eyebrow: "Exports",
    heading: "Export history",
    description: "Raw OCR audit workbooks stay separate from canonical reconciliation workbooks and canonical P&L CSV outputs."
  }
};

type InvoiceTableRow = {
  supplier: string;
  productCode: string;
  productName: string;
  quantityInvoice: string;
  preAmountInvoice: string;
  vatInvoice: string;
  totalInvoice: string;
};

type DocketTableRow = {
  supplier: string;
  productCode: string;
  productName: string;
  quantityDocket: string;
  amountDocket: string;
};

type InvoiceWorkspaceRow = InvoiceTableRow & {
  id: string;
  lineNumber: number;
  comment: string;
  status: string;
};

type DocketWorkspaceRow = DocketTableRow & {
  id: string;
  lineNumber: number;
  comment: string;
  status: string;
};

type MergedWorkspaceRow = {
  id: string;
  supplier: string;
  productCode: string;
  productName: string;
  quantityInvoice: string;
  preAmountInvoice: string;
  vatInvoice: string;
  totalInvoice: string;
  quantityDocket: string;
  amountDocket: string;
  commentOnMatch: string;
  status: string;
  matchOrigin: "auto" | "manual";
  manualPairPosition: number | null;
  invoiceLineNumber: number;
  docketLineNumber: number;
};

type ReconciliationWorkspace = {
  baseReconciliationRunId: string;
  mergedRows: MergedWorkspaceRow[];
  unmatchedInvoiceRows: InvoiceWorkspaceRow[];
  unmatchedDocketRows: DocketWorkspaceRow[];
};

type ReconciliationDisplayRow = {
  id: string;
  source: "invoice" | "docket";
  supplier: string;
  productCode: string;
  productName: string;
  quantityInvoice: string;
  preAmountInvoice: string;
  vatInvoice: string;
  totalInvoice: string;
  quantityDocket: string;
  amountDocket: string;
  statusLabel: string;
  matchedWith: string;
  comment: string;
  dragItem: DragItem;
  invoiceLineNumber: number | null;
  docketLineNumber: number | null;
  mergedRowId: string | null;
  mergedIndex: number | null;
  showReviewCells: boolean;
  reviewRowSpan: number;
  isGroupStart: boolean;
  isGroupEnd: boolean;
  canUnpair: boolean;
};

type ExportCardRow = {
  id: string;
  exportFormat: string;
  status: string;
  rowCount: string;
  createdAt: string;
  contentType: string;
};

type DragItem =
  | { kind: "invoice"; lineNumber: number }
  | { kind: "docket"; lineNumber: number }
  | { kind: "merged"; rowId: string };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function asString(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  return String(value);
}

function invoiceRowsFromPayload(responsePayload: unknown): InvoiceTableRow[] {
  if (!isRecord(responsePayload)) {
    return [];
  }

  const canonicalPayload = responsePayload.payload;
  if (!isRecord(canonicalPayload)) {
    return [];
  }

  const supplier =
    (isRecord(canonicalPayload.supplier) ? asString(canonicalPayload.supplier.name) : "") ||
    (isRecord(canonicalPayload.header) ? asString(canonicalPayload.header.supplier_name) : "");
  const lines = Array.isArray(canonicalPayload.lines) ? canonicalPayload.lines : [];

  return lines.filter(isRecord).map((line) => ({
    supplier,
    productCode: asString(line.product_code),
    productName: asString(line.description),
    quantityInvoice: asString(line.quantity),
    preAmountInvoice: asString(line.net_amount),
    vatInvoice: asString(line.vat_amount),
    totalInvoice: asString(line.gross_amount)
  }));
}

function docketRowsFromPayload(responsePayload: unknown): DocketTableRow[] {
  if (!isRecord(responsePayload)) {
    return [];
  }

  const canonicalPayload = responsePayload.payload;
  if (!isRecord(canonicalPayload)) {
    return [];
  }

  const supplier = asString(canonicalPayload.supplier_name);
  const lines = Array.isArray(canonicalPayload.lines) ? canonicalPayload.lines : [];

  return lines.filter(isRecord).map((line) => ({
    supplier,
    productCode: asString(line.product_code),
    productName: asString(line.description),
    quantityDocket: asString(line.quantity_delivered),
    amountDocket: asString(line.extended_amount)
  }));
}

function toInvoiceSaveRows(rows: InvoiceTableRow[]) {
  return rows.map((row) => ({
    supplier: row.supplier,
    product_code: row.productCode,
    product_name: row.productName,
    quantity_invoice: row.quantityInvoice,
    pre_amount_invoice: row.preAmountInvoice,
    vat_invoice: row.vatInvoice,
    total_invoice: row.totalInvoice
  }));
}

function toDocketSaveRows(rows: DocketTableRow[]) {
  return rows.map((row) => ({
    supplier: row.supplier,
    product_code: row.productCode,
    product_name: row.productName,
    quantity_docket: row.quantityDocket,
    amount_docket: row.amountDocket
  }));
}

function commentOnMatchForLine(line: Record<string, unknown>): string {
  const reasonMessages: Record<string, string> = {
    line_missing_in_docket: "Missing in docket",
    line_only_on_docket: "Only on docket",
    line_qty_mismatch: "Quantity mismatch",
    line_unit_price_mismatch: "Unit price mismatch",
    line_amount_mismatch: "Amount mismatch"
  };
  const reasons = Array.isArray(line.reason_codes) ? line.reason_codes : [];
  const comments = reasons
    .map((reason) => reasonMessages[asString(reason)])
    .filter((value): value is string => Boolean(value));

  if (comments.length > 0) {
    return Array.from(new Set(comments)).join("; ");
  }

  const status = asString(line.status);
  if (status === "matched") {
    return "Matched";
  }
  if (status === "within_tolerance") {
    return "Within tolerance";
  }
  if (status === "mismatch") {
    return "Mismatch";
  }
  return "Review required";
}

function sortInvoiceRows(rows: InvoiceWorkspaceRow[]): InvoiceWorkspaceRow[] {
  return [...rows].sort((left, right) => left.lineNumber - right.lineNumber);
}

function sortDocketRows(rows: DocketWorkspaceRow[]): DocketWorkspaceRow[] {
  return [...rows].sort((left, right) => left.lineNumber - right.lineNumber);
}

function buildInvoiceWorkspaceRow(
  line: Record<string, unknown>,
  supplier: string,
  comment: string,
  status: string
): InvoiceWorkspaceRow {
  const lineNumber = Number(line.line_number);
  return {
    id: `invoice-${lineNumber}`,
    lineNumber,
    supplier,
    productCode: asString(line.product_code),
    productName: asString(line.description),
    quantityInvoice: asString(line.quantity),
    preAmountInvoice: asString(line.net_amount),
    vatInvoice: asString(line.vat_amount),
    totalInvoice: asString(line.gross_amount),
    comment,
    status
  };
}

function buildDocketWorkspaceRow(
  line: Record<string, unknown>,
  supplier: string,
  comment: string,
  status: string
): DocketWorkspaceRow {
  const lineNumber = Number(line.line_number);
  return {
    id: `docket-${lineNumber}`,
    lineNumber,
    supplier,
    productCode: asString(line.product_code),
    productName: asString(line.description),
    quantityDocket: asString(line.quantity_delivered),
    amountDocket: asString(line.extended_amount),
    comment,
    status
  };
}

function buildReconciliationWorkspace(
  reconciliationPayload: unknown,
  caseDetailPayload: unknown
): ReconciliationWorkspace | null {
  if (!isRecord(reconciliationPayload) || !isRecord(caseDetailPayload)) {
    return null;
  }

  const reconciliationRunId = asString(reconciliationPayload.id);
  const resultPayload = reconciliationPayload.result_payload;
  const invoicePayload = caseDetailPayload.invoice;
  const docketPayload = caseDetailPayload.delivery_docket;
  if (!reconciliationRunId || !isRecord(resultPayload) || !isRecord(invoicePayload) || !isRecord(docketPayload)) {
    return null;
  }

  const invoiceSupplier =
    (isRecord(invoicePayload.supplier) ? asString(invoicePayload.supplier.name) : "") ||
    (isRecord(invoicePayload.header) ? asString(invoicePayload.header.supplier_name) : "");
  const docketSupplier = asString(docketPayload.supplier_name);
  const invoiceLines = Array.isArray(invoicePayload.lines) ? invoicePayload.lines.filter(isRecord) : [];
  const docketLines = Array.isArray(docketPayload.lines) ? docketPayload.lines.filter(isRecord) : [];
  const reconciledLines = Array.isArray(resultPayload.reconciled_lines)
    ? resultPayload.reconciled_lines.filter(isRecord)
    : [];

  const invoiceLineLookup = new Map<number, Record<string, unknown>>();
  invoiceLines.forEach((line) => {
    const lineNumber = Number(line.line_number);
    if (!Number.isNaN(lineNumber)) {
      invoiceLineLookup.set(lineNumber, line);
    }
  });

  const docketLineLookup = new Map<number, Record<string, unknown>>();
  docketLines.forEach((line) => {
    const lineNumber = Number(line.line_number);
    if (!Number.isNaN(lineNumber)) {
      docketLineLookup.set(lineNumber, line);
    }
  });

  const mergedRows: MergedWorkspaceRow[] = [];
  const unmatchedInvoiceRows: InvoiceWorkspaceRow[] = [];
  const unmatchedDocketRows: DocketWorkspaceRow[] = [];

  reconciledLines.forEach((reconciledLine) => {
    const invoiceLineNumber = Number(reconciledLine.invoice_line_number);
    const docketLineNumber = Number(reconciledLine.docket_line_number);
    const invoiceLine = !Number.isNaN(invoiceLineNumber) ? invoiceLineLookup.get(invoiceLineNumber) : undefined;
    const docketLine = !Number.isNaN(docketLineNumber) ? docketLineLookup.get(docketLineNumber) : undefined;
    const commentOnMatch = commentOnMatchForLine(reconciledLine);
    const status = asString(reconciledLine.status) || "review_required";

    if (invoiceLine && docketLine) {
      const rawManualPairPosition = reconciledLine.manual_pair_position;
      mergedRows.push({
        id: `merged-${invoiceLineNumber}-${docketLineNumber}`,
        supplier: invoiceSupplier || docketSupplier,
        productCode: asString(invoiceLine.product_code) || asString(docketLine.product_code) || asString(reconciledLine.product_code),
        productName: asString(invoiceLine.description) || asString(docketLine.description) || asString(reconciledLine.description),
        quantityInvoice: asString(invoiceLine.quantity),
        preAmountInvoice: asString(invoiceLine.net_amount),
        vatInvoice: asString(invoiceLine.vat_amount),
        totalInvoice: asString(invoiceLine.gross_amount),
        quantityDocket: asString(docketLine.quantity_delivered) || asString(reconciledLine.delivered_quantity),
        amountDocket: asString(docketLine.extended_amount) || asString(reconciledLine.delivery_net_amount),
        commentOnMatch,
        status,
        matchOrigin: asString(reconciledLine.match_origin) === "manual" ? "manual" : "auto",
        manualPairPosition:
          rawManualPairPosition === null || rawManualPairPosition === undefined || rawManualPairPosition === ""
            ? null
            : Number(rawManualPairPosition),
        invoiceLineNumber,
        docketLineNumber
      });
      return;
    }

    if (invoiceLine) {
      unmatchedInvoiceRows.push(
        buildInvoiceWorkspaceRow(
          invoiceLine,
          invoiceSupplier,
          commentOnMatch || "Invoice line was not reconciled.",
          status
        )
      );
      return;
    }

    if (docketLine) {
      unmatchedDocketRows.push(
        buildDocketWorkspaceRow(
          docketLine,
          docketSupplier || invoiceSupplier,
          commentOnMatch || "Docket line was not reconciled.",
          status
        )
      );
    }
  });

  return {
    baseReconciliationRunId: reconciliationRunId,
    mergedRows,
    unmatchedInvoiceRows: sortInvoiceRows(unmatchedInvoiceRows),
    unmatchedDocketRows: sortDocketRows(unmatchedDocketRows)
  };
}

function buildReconciliationDisplayRows(
  workspace: ReconciliationWorkspace | null
): ReconciliationDisplayRow[] {
  if (!workspace) {
    return [];
  }

  const rows: ReconciliationDisplayRow[] = [];

  workspace.mergedRows.forEach((row, index) => {
    const statusLabel = "Match found";
    const matchedWith = `I ${row.invoiceLineNumber} / D ${row.docketLineNumber}`;

    rows.push({
      id: `${row.id}-invoice`,
      source: "invoice",
      supplier: row.supplier,
      productCode: row.productCode,
      productName: row.productName,
      quantityInvoice: row.quantityInvoice,
      preAmountInvoice: row.preAmountInvoice,
      vatInvoice: row.vatInvoice,
      totalInvoice: row.totalInvoice,
      quantityDocket: "",
      amountDocket: "",
      statusLabel,
      matchedWith,
      comment: row.commentOnMatch,
      dragItem: { kind: "merged", rowId: row.id },
      invoiceLineNumber: row.invoiceLineNumber,
      docketLineNumber: row.docketLineNumber,
      mergedRowId: row.id,
      mergedIndex: index,
      showReviewCells: true,
      reviewRowSpan: 2,
      isGroupStart: true,
      isGroupEnd: false,
      canUnpair: true
    });

    rows.push({
      id: `${row.id}-docket`,
      source: "docket",
      supplier: row.supplier,
      productCode: row.productCode,
      productName: row.productName,
      quantityInvoice: "",
      preAmountInvoice: "",
      vatInvoice: "",
      totalInvoice: "",
      quantityDocket: row.quantityDocket,
      amountDocket: row.amountDocket,
      statusLabel,
      matchedWith,
      comment: row.commentOnMatch,
      dragItem: { kind: "merged", rowId: row.id },
      invoiceLineNumber: row.invoiceLineNumber,
      docketLineNumber: row.docketLineNumber,
      mergedRowId: row.id,
      mergedIndex: index,
      showReviewCells: false,
      reviewRowSpan: 0,
      isGroupStart: false,
      isGroupEnd: true,
      canUnpair: false
    });
  });

  workspace.unmatchedInvoiceRows.forEach((row) => {
    rows.push({
      id: row.id,
      source: "invoice",
      supplier: row.supplier,
      productCode: row.productCode,
      productName: row.productName,
      quantityInvoice: row.quantityInvoice,
      preAmountInvoice: row.preAmountInvoice,
      vatInvoice: row.vatInvoice,
      totalInvoice: row.totalInvoice,
      quantityDocket: "",
      amountDocket: "",
      statusLabel: "Match not found",
      matchedWith: "-",
      comment: row.comment,
      dragItem: { kind: "invoice", lineNumber: row.lineNumber },
      invoiceLineNumber: row.lineNumber,
      docketLineNumber: null,
      mergedRowId: null,
      mergedIndex: null,
      showReviewCells: true,
      reviewRowSpan: 1,
      isGroupStart: true,
      isGroupEnd: true,
      canUnpair: false
    });
  });

  workspace.unmatchedDocketRows.forEach((row) => {
    rows.push({
      id: row.id,
      source: "docket",
      supplier: row.supplier,
      productCode: row.productCode,
      productName: row.productName,
      quantityInvoice: "",
      preAmountInvoice: "",
      vatInvoice: "",
      totalInvoice: "",
      quantityDocket: row.quantityDocket,
      amountDocket: row.amountDocket,
      statusLabel: "Match not found",
      matchedWith: "-",
      comment: row.comment,
      dragItem: { kind: "docket", lineNumber: row.lineNumber },
      invoiceLineNumber: null,
      docketLineNumber: row.lineNumber,
      mergedRowId: null,
      mergedIndex: null,
      showReviewCells: true,
      reviewRowSpan: 1,
      isGroupStart: true,
      isGroupEnd: true,
      canUnpair: false
    });
  });

  return rows;
}

function exportRowsFromPayload(responsePayload: unknown): ExportCardRow[] {
  if (!Array.isArray(responsePayload)) {
    return [];
  }

  return responsePayload
    .filter(isRecord)
    .map((item) => ({
      id: asString(item.id),
      exportFormat: asString(item.export_format),
      status: asString(item.status),
      rowCount: asString(item.row_count),
      createdAt: asString(item.created_at),
      contentType: asString(item.content_type)
    }));
}

function exportFormatLabel(value: string): string {
  const labels: Record<string, string> = {
    reco_excel: "Canonical Reconciliation Excel",
    reco_csv: "Canonical Reconciliation CSV",
    ocr_excel: "Raw OCR Audit Excel",
    pnl_csv: "Canonical P&L CSV",
    csv: "CSV Export",
    json: "JSON Export"
  };
  return labels[value] || value.replaceAll("_", " ");
}

function exportFormatHint(value: string): string {
  const hints: Record<string, string> = {
    reco_excel: "Structured workbook for reconciliation review.",
    reco_csv: "Flat reconciliation rows for quick downstream use.",
    ocr_excel: "Raw OCR audit workbook from the provider output.",
    pnl_csv: "Canonical accounting export for the P&L workflow.",
    csv: "Generic CSV export.",
    json: "Generic JSON export."
  };
  return hints[value] || "Generated case export.";
}

function formatExportCreatedAt(value: string): string {
  if (!value) {
    return "Unknown time";
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  return parsed.toLocaleString();
}

function readDragItem(event: DragEvent<HTMLElement>, fallback: DragItem | null): DragItem | null {
  const payload = event.dataTransfer.getData("text/plain");
  if (!payload) {
    return fallback;
  }

  try {
    const parsed = JSON.parse(payload) as Partial<DragItem>;
    if (parsed.kind === "invoice" && typeof parsed.lineNumber === "number") {
      return { kind: "invoice", lineNumber: parsed.lineNumber };
    }
    if (parsed.kind === "docket" && typeof parsed.lineNumber === "number") {
      return { kind: "docket", lineNumber: parsed.lineNumber };
    }
    if (parsed.kind === "merged" && typeof parsed.rowId === "string") {
      return { kind: "merged", rowId: parsed.rowId };
    }
  } catch {
    return fallback;
  }

  return fallback;
}

export function CaseSectionView({ caseId, section }: { caseId: string; section: Section }) {
  const [payload, setPayload] = useState<unknown>(null);
  const [caseDetailPayload, setCaseDetailPayload] = useState<unknown>(null);
  const [error, setError] = useState<string | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isRunningToleranceReconcile, setIsRunningToleranceReconcile] = useState(false);
  const [isToleranceDrawerOpen, setIsToleranceDrawerOpen] = useState(false);
  const [isApplyingManualReconciliation, setIsApplyingManualReconciliation] = useState(false);
  const [isResettingToAuto, setIsResettingToAuto] = useState(false);
  const [isReExtracting, setIsReExtracting] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [invoiceDraftRows, setInvoiceDraftRows] = useState<InvoiceTableRow[]>([]);
  const [docketDraftRows, setDocketDraftRows] = useState<DocketTableRow[]>([]);
  const [reconciliationWorkspace, setReconciliationWorkspace] = useState<ReconciliationWorkspace | null>(null);
  const [dragItem, setDragItem] = useState<DragItem | null>(null);
  const [toleranceConfig, setToleranceConfig] = useState<ReconciliationConfigInput>(
    DEFAULT_RECONCILIATION_CONFIG
  );

  useEffect(() => {
    let cancelled = false;

    setError(null);
    setSaveMessage(null);
    setIsEditing(false);

    const loadSection = async () => {
      if (section === "reconciliation") {
        const [reconciliationResponse, caseResponse] = await Promise.all([
          endpointMap[section](caseId),
          api.getCase(caseId)
        ]);
        return { sectionPayload: reconciliationResponse, casePayload: caseResponse };
      }
      const sectionPayload = await endpointMap[section](caseId);
      return { sectionPayload, casePayload: null };
    };

    loadSection()
      .then(({ sectionPayload, casePayload }) => {
        if (cancelled) {
          return;
        }
        setPayload(sectionPayload);
        setCaseDetailPayload(casePayload);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load section.");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [caseId, section]);

  useEffect(() => {
    if (section === "invoice" || section === "docket") {
      setToleranceConfig(loadReconciliationConfig(caseId));
    }
    if (section === "invoice") {
      setInvoiceDraftRows(invoiceRowsFromPayload(payload));
      return;
    }
    if (section === "docket") {
      setDocketDraftRows(docketRowsFromPayload(payload));
      return;
    }
    if (section === "reconciliation") {
      setReconciliationWorkspace(buildReconciliationWorkspace(payload, caseDetailPayload));
    }
  }, [caseId, payload, caseDetailPayload, section]);

  const meta = titles[section];
  const isInvoiceSection = section === "invoice";
  const isDocketSection = section === "docket";
  const isReconciliationSection = section === "reconciliation";
  const exportRows = section === "exports" ? exportRowsFromPayload(payload) : [];
  const invoiceRows = isInvoiceSection ? (isEditing ? invoiceDraftRows : invoiceRowsFromPayload(payload)) : [];
  const docketRows = isDocketSection ? (isEditing ? docketDraftRows : docketRowsFromPayload(payload)) : [];
  const reconciliationDisplayRows = isReconciliationSection
    ? buildReconciliationDisplayRows(reconciliationWorkspace)
    : [];

  const refreshReconciliationWorkspace = async (successMessage: string) => {
    const [reconciliationResponse, caseResponse] = await Promise.all([
      api.getReconciliation(caseId),
      api.getCase(caseId)
    ]);
    setPayload(reconciliationResponse);
    setCaseDetailPayload(caseResponse);
    setReconciliationWorkspace(buildReconciliationWorkspace(reconciliationResponse, caseResponse));
    setSaveMessage(successMessage);
  };

  const refreshCurrentSection = async (successMessage: string) => {
    const refreshedPayload = await endpointMap[section](caseId);
    setPayload(refreshedPayload);
    setSaveMessage(successMessage);
  };

  const beginEditing = () => {
    setError(null);
    setSaveMessage(null);
    if (isInvoiceSection) {
      setInvoiceDraftRows(invoiceRowsFromPayload(payload));
    }
    if (isDocketSection) {
      setDocketDraftRows(docketRowsFromPayload(payload));
    }
    setIsEditing(true);
  };

  const cancelEditing = () => {
    setError(null);
    setSaveMessage(null);
    if (isInvoiceSection) {
      setInvoiceDraftRows(invoiceRowsFromPayload(payload));
    }
    if (isDocketSection) {
      setDocketDraftRows(docketRowsFromPayload(payload));
    }
    setIsEditing(false);
  };

  const updateInvoiceRow = (rowIndex: number, field: keyof InvoiceTableRow, value: string) => {
    setInvoiceDraftRows((currentRows) =>
      currentRows.map((row, index) => {
        if (field === "supplier") {
          return { ...row, supplier: value };
        }
        if (index !== rowIndex) {
          return row;
        }
        return { ...row, [field]: value };
      })
    );
  };

  const updateDocketRow = (rowIndex: number, field: keyof DocketTableRow, value: string) => {
    setDocketDraftRows((currentRows) =>
      currentRows.map((row, index) => {
        if (field === "supplier") {
          return { ...row, supplier: value };
        }
        if (index !== rowIndex) {
          return row;
        }
        return { ...row, [field]: value };
      })
    );
  };

  const updateToleranceField = (field: keyof ReconciliationConfigInput, value: string) => {
    setToleranceConfig((current) => ({
      ...current,
      [field]: value
    }));
  };

  const saveToleranceSettings = () => {
    setError(null);
    saveReconciliationConfig(caseId, toleranceConfig);
    setSaveMessage("Tolerance settings saved for this case.");
  };

  const resetToleranceSettings = () => {
    setError(null);
    clearReconciliationConfig(caseId);
    setToleranceConfig(DEFAULT_RECONCILIATION_CONFIG);
    setSaveMessage("Tolerance settings reset to defaults.");
  };

  const runReconciliationWithTolerance = async () => {
    try {
      setError(null);
      setIsRunningToleranceReconcile(true);
      saveReconciliationConfig(caseId, toleranceConfig);
      await api.reconcileCase(caseId, toleranceConfig);
      setSaveMessage("Reconciliation ran with the current tolerance settings.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to run reconciliation.");
    } finally {
      setIsRunningToleranceReconcile(false);
    }
  };

  const reExtractWithCurrentTolerance = async () => {
    try {
      setError(null);
      setIsReExtracting(true);
      saveReconciliationConfig(caseId, toleranceConfig);
      await api.extractCase(caseId);
      await refreshCurrentSection("Extraction reran and the current document view was refreshed.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to re-extract the case.");
    } finally {
      setIsReExtracting(false);
    }
  };

  const saveEdits = async () => {
    try {
      setIsSaving(true);
      setError(null);
      setSaveMessage(null);

      if (isInvoiceSection) {
        const response = await api.updateInvoice(caseId, toInvoiceSaveRows(invoiceDraftRows));
        setPayload(response);
        setSaveMessage("Invoice edits saved.");
      } else if (isDocketSection) {
        const response = await api.updateDocket(caseId, toDocketSaveRows(docketDraftRows));
        setPayload(response);
        setSaveMessage("Delivery docket edits saved.");
      }

      setIsEditing(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save changes.");
    } finally {
      setIsSaving(false);
    }
  };

  const createManualPair = (invoiceLineNumber: number, docketLineNumber: number) => {
    setReconciliationWorkspace((current) => {
      if (!current) {
        return current;
      }

      const invoiceRow = current.unmatchedInvoiceRows.find((row) => row.lineNumber === invoiceLineNumber);
      const docketRow = current.unmatchedDocketRows.find((row) => row.lineNumber === docketLineNumber);
      if (!invoiceRow || !docketRow) {
        return current;
      }

      const mergedRow: MergedWorkspaceRow = {
        id: `merged-${invoiceLineNumber}-${docketLineNumber}`,
        supplier: invoiceRow.supplier || docketRow.supplier,
        productCode: invoiceRow.productCode || docketRow.productCode,
        productName: invoiceRow.productName || docketRow.productName,
        quantityInvoice: invoiceRow.quantityInvoice,
        preAmountInvoice: invoiceRow.preAmountInvoice,
        vatInvoice: invoiceRow.vatInvoice,
        totalInvoice: invoiceRow.totalInvoice,
        quantityDocket: docketRow.quantityDocket,
        amountDocket: docketRow.amountDocket,
        commentOnMatch: "Pending manual reconciliation.",
        status: "review_required",
        matchOrigin: "manual",
        manualPairPosition: current.mergedRows.length,
        invoiceLineNumber,
        docketLineNumber
      };

      return {
        ...current,
        mergedRows: [...current.mergedRows, mergedRow].map((row, index) => ({
          ...row,
          manualPairPosition: index
        })),
        unmatchedInvoiceRows: sortInvoiceRows(
          current.unmatchedInvoiceRows.filter((row) => row.lineNumber !== invoiceLineNumber)
        ),
        unmatchedDocketRows: sortDocketRows(
          current.unmatchedDocketRows.filter((row) => row.lineNumber !== docketLineNumber)
        )
      };
    });
  };

  const unpairMergedRow = (rowId: string) => {
    setReconciliationWorkspace((current) => {
      if (!current) {
        return current;
      }

      const mergedRow = current.mergedRows.find((row) => row.id === rowId);
      if (!mergedRow) {
        return current;
      }

      const invoiceRow: InvoiceWorkspaceRow = {
        id: `invoice-${mergedRow.invoiceLineNumber}`,
        lineNumber: mergedRow.invoiceLineNumber,
        supplier: mergedRow.supplier,
        productCode: mergedRow.productCode,
        productName: mergedRow.productName,
        quantityInvoice: mergedRow.quantityInvoice,
        preAmountInvoice: mergedRow.preAmountInvoice,
        vatInvoice: mergedRow.vatInvoice,
        totalInvoice: mergedRow.totalInvoice,
        comment: "Pending manual reconciliation.",
        status: "review_required"
      };
      const docketRow: DocketWorkspaceRow = {
        id: `docket-${mergedRow.docketLineNumber}`,
        lineNumber: mergedRow.docketLineNumber,
        supplier: mergedRow.supplier,
        productCode: mergedRow.productCode,
        productName: mergedRow.productName,
        quantityDocket: mergedRow.quantityDocket,
        amountDocket: mergedRow.amountDocket,
        comment: "Pending manual reconciliation.",
        status: "review_required"
      };

      return {
        ...current,
        mergedRows: current.mergedRows
          .filter((row) => row.id !== rowId)
          .map((row, index) => ({ ...row, manualPairPosition: index })),
        unmatchedInvoiceRows: sortInvoiceRows([...current.unmatchedInvoiceRows, invoiceRow]),
        unmatchedDocketRows: sortDocketRows([...current.unmatchedDocketRows, docketRow])
      };
    });
  };

  const moveMergedRow = (rowId: string, targetIndex: number) => {
    setReconciliationWorkspace((current) => {
      if (!current) {
        return current;
      }
      const sourceIndex = current.mergedRows.findIndex((row) => row.id === rowId);
      if (sourceIndex === -1 || sourceIndex === targetIndex) {
        return current;
      }

      const nextRows = [...current.mergedRows];
      const [movedRow] = nextRows.splice(sourceIndex, 1);
      nextRows.splice(targetIndex, 0, movedRow);
      return {
        ...current,
        mergedRows: nextRows.map((row, index) => ({
          ...row,
          manualPairPosition: index
        }))
      };
    });
  };

  const startDrag = (item: DragItem) => (event: DragEvent<HTMLElement>) => {
    setDragItem(item);
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", JSON.stringify(item));
  };

  const endDrag = () => {
    setDragItem(null);
  };

  const allowDrop = (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  };

  const dropInvoiceTarget = (invoiceLineNumber: number) => (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    const droppedItem = readDragItem(event, dragItem);
    if (droppedItem?.kind === "docket") {
      createManualPair(invoiceLineNumber, droppedItem.lineNumber);
    }
    setDragItem(null);
  };

  const dropDocketTarget = (docketLineNumber: number) => (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    const droppedItem = readDragItem(event, dragItem);
    if (droppedItem?.kind === "invoice") {
      createManualPair(droppedItem.lineNumber, docketLineNumber);
    }
    setDragItem(null);
  };

  const dropMergedSlot = (targetIndex: number) => (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    const droppedItem = readDragItem(event, dragItem);
    if (droppedItem?.kind === "merged") {
      moveMergedRow(droppedItem.rowId, targetIndex);
    }
    setDragItem(null);
  };

  const dropReconciliationRow =
    (row: ReconciliationDisplayRow) => (event: DragEvent<HTMLElement>) => {
      event.preventDefault();
      const droppedItem = readDragItem(event, dragItem);
      if (!droppedItem) {
        setDragItem(null);
        return;
      }

      if (droppedItem.kind === "merged" && row.mergedIndex !== null) {
        moveMergedRow(droppedItem.rowId, row.mergedIndex);
        setDragItem(null);
        return;
      }

      if (
        droppedItem.kind === "docket" &&
        row.source === "invoice" &&
        row.invoiceLineNumber !== null &&
        row.mergedRowId === null
      ) {
        createManualPair(row.invoiceLineNumber, droppedItem.lineNumber);
      }

      if (
        droppedItem.kind === "invoice" &&
        row.source === "docket" &&
        row.docketLineNumber !== null &&
        row.mergedRowId === null
      ) {
        createManualPair(droppedItem.lineNumber, row.docketLineNumber);
      }

      setDragItem(null);
    };

  const applyManualReconciliation = async () => {
    if (!reconciliationWorkspace) {
      setError("Reconciliation workspace is not ready yet.");
      return;
    }

    try {
      setError(null);
      setIsApplyingManualReconciliation(true);
      await api.applyManualReconciliation(caseId, {
        base_reconciliation_run_id: reconciliationWorkspace.baseReconciliationRunId,
        config: loadReconciliationConfig(caseId),
        pairs: reconciliationWorkspace.mergedRows.map((row, index) => ({
          invoice_line_number: row.invoiceLineNumber,
          docket_line_number: row.docketLineNumber,
          position: index
        }))
      });
      await refreshReconciliationWorkspace("Manual reconciliation saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to apply manual reconciliation.");
    } finally {
      setIsApplyingManualReconciliation(false);
    }
  };

  const resetToAuto = async () => {
    try {
      setError(null);
      setIsResettingToAuto(true);
      await api.reconcileCase(caseId, loadReconciliationConfig(caseId));
      await refreshReconciliationWorkspace("Auto reconciliation restored.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reset to auto reconciliation.");
    } finally {
      setIsResettingToAuto(false);
    }
  };

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
      {saveMessage ? <p className="success-banner">{saveMessage}</p> : null}
      {!payload && !error ? <p className="muted">Loading {section}...</p> : null}

      {isInvoiceSection || isDocketSection ? (
        <>
          <button
            className={`tolerance-tab ${isToleranceDrawerOpen ? "is-open" : ""}`}
            onClick={() => setIsToleranceDrawerOpen((current) => !current)}
            type="button"
          >
            {isToleranceDrawerOpen ? "Close Tolerance" : "Tolerance"}
          </button>

          <aside className={`tolerance-drawer ${isToleranceDrawerOpen ? "is-open" : ""}`}>
            <div className="tolerance-drawer-head">
              <div>
                <span className="eyebrow">{isInvoiceSection ? "Invoice Controls" : "Docket Controls"}</span>
                <h2>Column Match Settings</h2>
                <p className="muted">
                  These settings follow the columns you review in the invoice and docket tables.
                </p>
              </div>
              <button className="ghost-link" onClick={() => setIsToleranceDrawerOpen(false)} type="button">
                Close
              </button>
            </div>

            <div className="tolerance-grid">
              <label className="tolerance-field">
                <span>Supplier</span>
                <select
                  className="table-input"
                  onChange={(event) => updateToleranceField("supplier_match_rule", event.target.value)}
                  value={toleranceConfig.supplier_match_rule}
                >
                  <option value="exact">Exact match</option>
                  <option value="normalized">Normalized match</option>
                  <option value="contains">Contains match</option>
                </select>
              </label>
              <label className="tolerance-field">
                <span>Product Code</span>
                <select
                  className="table-input"
                  onChange={(event) => updateToleranceField("product_code_match_rule", event.target.value)}
                  value={toleranceConfig.product_code_match_rule}
                >
                  <option value="exact">Exact match</option>
                  <option value="normalized">Normalized match</option>
                  <option value="contains">Contains match</option>
                </select>
              </label>
              <label className="tolerance-field">
                <span>Product Name</span>
                <select
                  className="table-input"
                  onChange={(event) => updateToleranceField("product_name_match_rule", event.target.value)}
                  value={toleranceConfig.product_name_match_rule}
                >
                  <option value="exact">Exact match</option>
                  <option value="normalized">Normalized match</option>
                  <option value="contains">Contains match</option>
                </select>
              </label>
              <label className="tolerance-field">
                <span>Quantity - Invoice</span>
                <input
                  className="table-input table-input-numeric"
                  inputMode="decimal"
                  onChange={(event) => updateToleranceField("quantity_tolerance", event.target.value)}
                  value={toleranceConfig.quantity_tolerance}
                />
              </label>
              <label className="tolerance-field">
                <span>Pre Amount - Invoice</span>
                <input
                  className="table-input table-input-numeric"
                  inputMode="decimal"
                  onChange={(event) => updateToleranceField("pre_amount_tolerance", event.target.value)}
                  value={toleranceConfig.pre_amount_tolerance}
                />
              </label>
              <label className="tolerance-field">
                <span>VAT - Invoice</span>
                <input
                  className="table-input table-input-numeric"
                  inputMode="decimal"
                  onChange={(event) => updateToleranceField("vat_tolerance", event.target.value)}
                  value={toleranceConfig.vat_tolerance}
                />
              </label>
              <label className="tolerance-field">
                <span>Total - Invoice</span>
                <input
                  className="table-input table-input-numeric"
                  inputMode="decimal"
                  onChange={(event) => updateToleranceField("total_tolerance", event.target.value)}
                  value={toleranceConfig.total_tolerance}
                />
              </label>
            </div>

            <div className="tolerance-actions">
              <button className="secondary-button" onClick={resetToleranceSettings} type="button">
                Reset defaults
              </button>
              <button className="secondary-button" onClick={saveToleranceSettings} type="button">
                Save settings
              </button>
              <button
                className="primary-button"
                disabled={isRunningToleranceReconcile}
                onClick={runReconciliationWithTolerance}
                type="button"
              >
                {isRunningToleranceReconcile ? "Reconciling..." : "Run reconcile"}
              </button>
              <button
                className="secondary-button"
                disabled={isReExtracting}
                onClick={reExtractWithCurrentTolerance}
                type="button"
              >
                {isReExtracting ? "Re-extracting..." : "Re-extract"}
              </button>
            </div>
          </aside>
        </>
      ) : null}

      {section === "exports" && Array.isArray(payload) ? (
        <section className="panel">
          <div className="panel-head">
            <h2>Download exports</h2>
            <p className="muted">Each export is available here as a clean download card instead of raw payload JSON.</p>
          </div>
          {exportRows.length === 0 ? <p className="muted">No exports have been generated for this case yet.</p> : null}
          {exportRows.length > 0 ? (
            <div className="export-grid">
              {exportRows.map((item) => (
                <article className="export-card" key={item.id}>
                  <div className="export-card-top">
                    <div>
                      <span className="eyebrow">Ready File</span>
                      <h3>{exportFormatLabel(item.exportFormat)}</h3>
                      <p>{exportFormatHint(item.exportFormat)}</p>
                    </div>
                    <StatusPill value={item.status} />
                  </div>
                  <div className="export-meta">
                    <div className="export-meta-row">
                      <span>Rows</span>
                      <strong>{item.rowCount || "0"}</strong>
                    </div>
                    <div className="export-meta-row">
                      <span>Created</span>
                      <strong>{formatExportCreatedAt(item.createdAt)}</strong>
                    </div>
                    <div className="export-meta-row">
                      <span>Type</span>
                      <strong>{item.contentType || "Unknown"}</strong>
                    </div>
                  </div>
                  <button
                    className="primary-button export-download-button"
                    onClick={() =>
                      api.downloadExport(item.id).catch((err) =>
                        setError(err instanceof Error ? err.message : "Failed to download export")
                      )
                    }
                    type="button"
                  >
                    Download file
                  </button>
                </article>
              ))}
            </div>
          ) : null}
        </section>
      ) : null}

      {isInvoiceSection && !Array.isArray(payload) && payload ? (
        <section className="panel">
          <div className="panel-head panel-head-split">
            <div>
              <h2>Invoice lines</h2>
              <p className="muted">Edit values here to quickly correct the canonical invoice before reconciliation or export.</p>
            </div>
            <div className="panel-head-actions">
              {!isEditing ? (
                <button className="secondary-button" onClick={beginEditing} type="button">
                  Edit invoice lines
                </button>
              ) : (
                <>
                  <button className="secondary-button" onClick={cancelEditing} type="button">
                    Cancel
                  </button>
                  <button className="primary-button" disabled={isSaving} onClick={saveEdits} type="button">
                    {isSaving ? "Saving..." : "Save invoice edits"}
                  </button>
                </>
              )}
            </div>
          </div>
          {invoiceRows.length === 0 ? <p className="muted">No canonical invoice lines are available yet.</p> : null}
          {invoiceRows.length > 0 ? (
            <div className="table-shell">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Supplier</th>
                    <th>Product Code</th>
                    <th>Product Name</th>
                    <th>Quantity - Invoice</th>
                    <th>Pre Amount - Invoice</th>
                    <th>VAT - Invoice</th>
                    <th>Total - Invoice</th>
                  </tr>
                </thead>
                <tbody>
                  {invoiceRows.map((row, index) => (
                    <tr key={`${row.productCode}-${row.productName}-${index}`}>
                      <td>
                        {isEditing ? (
                          <input
                            className="table-input"
                            onChange={(event) => updateInvoiceRow(index, "supplier", event.target.value)}
                            value={row.supplier}
                          />
                        ) : (
                          row.supplier || "Unknown Supplier"
                        )}
                      </td>
                      <td>
                        {isEditing ? (
                          <input
                            className="table-input"
                            onChange={(event) => updateInvoiceRow(index, "productCode", event.target.value)}
                            value={row.productCode}
                          />
                        ) : (
                          row.productCode || "-"
                        )}
                      </td>
                      <td>
                        {isEditing ? (
                          <input
                            className="table-input"
                            onChange={(event) => updateInvoiceRow(index, "productName", event.target.value)}
                            value={row.productName}
                          />
                        ) : (
                          row.productName || "-"
                        )}
                      </td>
                      <td className="numeric-cell">
                        {isEditing ? (
                          <input
                            className="table-input table-input-numeric"
                            inputMode="decimal"
                            onChange={(event) => updateInvoiceRow(index, "quantityInvoice", event.target.value)}
                            value={row.quantityInvoice}
                          />
                        ) : (
                          row.quantityInvoice || "-"
                        )}
                      </td>
                      <td className="numeric-cell">
                        {isEditing ? (
                          <input
                            className="table-input table-input-numeric"
                            inputMode="decimal"
                            onChange={(event) => updateInvoiceRow(index, "preAmountInvoice", event.target.value)}
                            value={row.preAmountInvoice}
                          />
                        ) : (
                          row.preAmountInvoice || "-"
                        )}
                      </td>
                      <td className="numeric-cell">
                        {isEditing ? (
                          <input
                            className="table-input table-input-numeric"
                            inputMode="decimal"
                            onChange={(event) => updateInvoiceRow(index, "vatInvoice", event.target.value)}
                            value={row.vatInvoice}
                          />
                        ) : (
                          row.vatInvoice || "-"
                        )}
                      </td>
                      <td className="numeric-cell">
                        {isEditing ? (
                          <input
                            className="table-input table-input-numeric"
                            inputMode="decimal"
                            onChange={(event) => updateInvoiceRow(index, "totalInvoice", event.target.value)}
                            value={row.totalInvoice}
                          />
                        ) : (
                          row.totalInvoice || "-"
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </section>
      ) : null}

      {isDocketSection && !Array.isArray(payload) && payload ? (
        <section className="panel">
          <div className="panel-head panel-head-split">
            <div>
              <h2>Docket lines</h2>
              <p className="muted">Edit delivery-side values here to quickly correct the canonical docket before reconciliation or export.</p>
            </div>
            <div className="panel-head-actions">
              {!isEditing ? (
                <button className="secondary-button" onClick={beginEditing} type="button">
                  Edit docket lines
                </button>
              ) : (
                <>
                  <button className="secondary-button" onClick={cancelEditing} type="button">
                    Cancel
                  </button>
                  <button className="primary-button" disabled={isSaving} onClick={saveEdits} type="button">
                    {isSaving ? "Saving..." : "Save docket edits"}
                  </button>
                </>
              )}
            </div>
          </div>
          {docketRows.length === 0 ? <p className="muted">No canonical docket lines are available yet.</p> : null}
          {docketRows.length > 0 ? (
            <div className="table-shell">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Supplier</th>
                    <th>Product Code</th>
                    <th>Product Name</th>
                    <th>Quantity - Docket</th>
                    <th>Amount - Docket</th>
                  </tr>
                </thead>
                <tbody>
                  {docketRows.map((row, index) => (
                    <tr key={`${row.productCode}-${row.productName}-${index}`}>
                      <td>
                        {isEditing ? (
                          <input
                            className="table-input"
                            onChange={(event) => updateDocketRow(index, "supplier", event.target.value)}
                            value={row.supplier}
                          />
                        ) : (
                          row.supplier || "Unknown Supplier"
                        )}
                      </td>
                      <td>
                        {isEditing ? (
                          <input
                            className="table-input"
                            onChange={(event) => updateDocketRow(index, "productCode", event.target.value)}
                            value={row.productCode}
                          />
                        ) : (
                          row.productCode || "-"
                        )}
                      </td>
                      <td>
                        {isEditing ? (
                          <input
                            className="table-input"
                            onChange={(event) => updateDocketRow(index, "productName", event.target.value)}
                            value={row.productName}
                          />
                        ) : (
                          row.productName || "-"
                        )}
                      </td>
                      <td className="numeric-cell">
                        {isEditing ? (
                          <input
                            className="table-input table-input-numeric"
                            inputMode="decimal"
                            onChange={(event) => updateDocketRow(index, "quantityDocket", event.target.value)}
                            value={row.quantityDocket}
                          />
                        ) : (
                          row.quantityDocket || "-"
                        )}
                      </td>
                      <td className="numeric-cell">
                        {isEditing ? (
                          <input
                            className="table-input table-input-numeric"
                            inputMode="decimal"
                            onChange={(event) => updateDocketRow(index, "amountDocket", event.target.value)}
                            value={row.amountDocket}
                          />
                        ) : (
                          row.amountDocket || "-"
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </section>
      ) : null}

      {isReconciliationSection && !Array.isArray(payload) && payload ? (
        <section className="panel">
          <div className="panel-head panel-head-split">
            <div>
              <h2>Reconciliation lines</h2>
              <p className="muted">
                Drag rows using the subtle handle on the left. Matched invoice and docket rows stay visually attached, while the middle business columns can slide horizontally.
              </p>
            </div>
            <div className="panel-head-actions">
              <button className="secondary-button" disabled={isResettingToAuto} onClick={resetToAuto} type="button">
                {isResettingToAuto ? "Resetting..." : "Reset to auto"}
              </button>
              <button
                className="primary-button"
                disabled={isApplyingManualReconciliation || !reconciliationWorkspace}
                onClick={applyManualReconciliation}
                type="button"
              >
                {isApplyingManualReconciliation ? "Applying..." : "Apply manual reconciliation"}
              </button>
            </div>
          </div>

          {reconciliationWorkspace ? (
            reconciliationDisplayRows.length > 0 ? (
              <div className="table-shell reconciliation-table-shell">
                <table className="data-table reconciliation-table">
                  <thead>
                    <tr>
                      <th className="reconciliation-sticky-left reconciliation-col-handle"> </th>
                      <th className="reconciliation-sticky-left reconciliation-col-source">Src</th>
                      <th>Supplier</th>
                      <th>Product Code</th>
                      <th>Product Name</th>
                      <th>Quantity - Invoice</th>
                      <th>Pre Amount - Invoice</th>
                      <th>VAT - Invoice</th>
                      <th>Total - Invoice</th>
                      <th>Quantity - Docket</th>
                      <th>Amount - Docket</th>
                      <th className="reconciliation-sticky-right reconciliation-col-status">Status</th>
                      <th className="reconciliation-sticky-right reconciliation-col-matched">Matched With</th>
                      <th className="reconciliation-sticky-right reconciliation-col-comment">Comment</th>
                    </tr>
                  </thead>
                  <tbody>
                    {reconciliationDisplayRows.map((row) => (
                      <tr
                        key={row.id}
                        className={[
                          "reconciliation-table-row",
                          row.mergedRowId ? "is-paired-row" : "is-unmatched-row",
                          row.isGroupStart ? "is-group-start" : "",
                          row.isGroupEnd ? "is-group-end" : "",
                          row.source === "invoice" ? "is-invoice-row" : "is-docket-row"
                        ]
                          .filter(Boolean)
                          .join(" ")}
                        onDragOver={allowDrop}
                        onDrop={dropReconciliationRow(row)}
                      >
                        <td className="reconciliation-sticky-left reconciliation-col-handle">
                          <button
                            aria-label={`Drag ${row.source} row`}
                            className="drag-handle-button"
                            draggable
                            onDragEnd={endDrag}
                            onDragStart={startDrag(row.dragItem)}
                            type="button"
                          >
                            <span>⋮⋮</span>
                          </button>
                        </td>
                        <td className="reconciliation-sticky-left reconciliation-col-source">
                          <span className={`source-chip source-chip-${row.source}`}>
                            {row.source === "invoice" ? "I" : "D"}
                          </span>
                        </td>
                        <td>{row.supplier || "Unknown Supplier"}</td>
                        <td>{row.productCode || "-"}</td>
                        <td>{row.productName || "-"}</td>
                        <td className="numeric-cell">{row.quantityInvoice || "-"}</td>
                        <td className="numeric-cell">{row.preAmountInvoice || "-"}</td>
                        <td className="numeric-cell">{row.vatInvoice || "-"}</td>
                        <td className="numeric-cell">{row.totalInvoice || "-"}</td>
                        <td className="numeric-cell">{row.quantityDocket || "-"}</td>
                        <td className="numeric-cell">{row.amountDocket || "-"}</td>
                        {row.showReviewCells ? (
                          <>
                            <td
                              className="reconciliation-sticky-right reconciliation-col-status reconciliation-review-cell"
                              rowSpan={row.reviewRowSpan}
                            >
                              <span className={`reconciliation-status-pill ${row.statusLabel === "Match found" ? "is-found" : "is-missing"}`}>
                                {row.statusLabel}
                              </span>
                            </td>
                            <td
                              className="reconciliation-sticky-right reconciliation-col-matched reconciliation-review-cell"
                              rowSpan={row.reviewRowSpan}
                            >
                              {row.matchedWith}
                            </td>
                            <td
                              className="reconciliation-sticky-right reconciliation-col-comment reconciliation-review-cell"
                              rowSpan={row.reviewRowSpan}
                            >
                              <div className="reconciliation-comment-cell">
                                <span>{row.comment || "-"}</span>
                                {row.canUnpair && row.mergedRowId ? (
                                  <button className="ghost-link" onClick={() => unpairMergedRow(row.mergedRowId!)} type="button">
                                    Unpair
                                  </button>
                                ) : null}
                              </div>
                            </td>
                          </>
                        ) : null}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="muted">No reconciliation rows are available yet.</p>
            )
          ) : (
            <p className="muted">No reconciliation workspace is available yet.</p>
          )}
        </section>
      ) : null}
    </div>
  );
}
