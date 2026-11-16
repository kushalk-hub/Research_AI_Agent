import { statusLabel, statusTone } from "../lib/events.js";

/** A run's lifecycle state. The tone is only a visual hint; the text is the
 *  source of truth, so colour-blind users read the same status. */
export default function StatusChip({ status = "unknown", reason = "", prefix = "" }) {
  const label = statusLabel(status);
  return (
    <span
      className="chip"
      data-tone={statusTone(status)}
      title={reason || undefined}
      aria-label={prefix ? `${prefix}: ${label}` : `Status: ${label}`}
    >
      {label}
    </span>
  );
}
