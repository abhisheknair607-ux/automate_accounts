type StatusPillProps = {
  value?: string | null;
};

export function StatusPill({ value }: StatusPillProps) {
  const label = value || "unknown";
  return <span className={`status-pill status-${label.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}`}>{label}</span>;
}
