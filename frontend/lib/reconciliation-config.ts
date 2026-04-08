export type TextMatchRule = "exact" | "normalized" | "contains";

export type ReconciliationConfigInput = {
  supplier_match_rule: TextMatchRule;
  product_code_match_rule: TextMatchRule;
  product_name_match_rule: TextMatchRule;
  quantity_tolerance: string;
  pre_amount_tolerance: string;
  vat_tolerance: string;
  total_tolerance: string;
  low_confidence_threshold: string;
};

type LegacyReconciliationConfigInput = Partial<
  ReconciliationConfigInput & {
    line_amount_tolerance: string;
    tax_tolerance: string;
  }
>;

export const DEFAULT_RECONCILIATION_CONFIG: ReconciliationConfigInput = {
  supplier_match_rule: "contains",
  product_code_match_rule: "normalized",
  product_name_match_rule: "contains",
  quantity_tolerance: "0.00",
  pre_amount_tolerance: "0.50",
  vat_tolerance: "0.50",
  total_tolerance: "0.50",
  low_confidence_threshold: "0.85"
};

function storageKey(caseId: string): string {
  return `reconciliation-config:${caseId}`;
}

function migrateConfig(parsed: LegacyReconciliationConfigInput): ReconciliationConfigInput {
  return {
    supplier_match_rule: parsed.supplier_match_rule ?? DEFAULT_RECONCILIATION_CONFIG.supplier_match_rule,
    product_code_match_rule:
      parsed.product_code_match_rule ?? DEFAULT_RECONCILIATION_CONFIG.product_code_match_rule,
    product_name_match_rule:
      parsed.product_name_match_rule ?? DEFAULT_RECONCILIATION_CONFIG.product_name_match_rule,
    quantity_tolerance: parsed.quantity_tolerance ?? DEFAULT_RECONCILIATION_CONFIG.quantity_tolerance,
    pre_amount_tolerance:
      parsed.pre_amount_tolerance ??
      parsed.line_amount_tolerance ??
      DEFAULT_RECONCILIATION_CONFIG.pre_amount_tolerance,
    vat_tolerance:
      parsed.vat_tolerance ?? parsed.tax_tolerance ?? DEFAULT_RECONCILIATION_CONFIG.vat_tolerance,
    total_tolerance: parsed.total_tolerance ?? DEFAULT_RECONCILIATION_CONFIG.total_tolerance,
    low_confidence_threshold:
      parsed.low_confidence_threshold ?? DEFAULT_RECONCILIATION_CONFIG.low_confidence_threshold
  };
}

export function loadReconciliationConfig(caseId: string): ReconciliationConfigInput {
  if (typeof window === "undefined") {
    return DEFAULT_RECONCILIATION_CONFIG;
  }

  try {
    const stored = window.localStorage.getItem(storageKey(caseId));
    if (!stored) {
      return DEFAULT_RECONCILIATION_CONFIG;
    }

    const parsed = JSON.parse(stored) as LegacyReconciliationConfigInput;
    return migrateConfig(parsed);
  } catch {
    return DEFAULT_RECONCILIATION_CONFIG;
  }
}

export function saveReconciliationConfig(caseId: string, config: ReconciliationConfigInput): void {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.setItem(storageKey(caseId), JSON.stringify(config));
}

export function clearReconciliationConfig(caseId: string): void {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.removeItem(storageKey(caseId));
}
