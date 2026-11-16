/** Small formatting helpers. No locale-dependent output: tests and screenshots
 *  must be stable regardless of the machine's settings. */

/** Accepts epoch seconds (runtime events) or epoch milliseconds (JS dates). */
export function toMillis(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) return 0;
  return number > 1e12 ? number : number * 1000;
}

/** "just now" / "4m ago" / "2h ago" / "3d ago" — coarse on purpose. */
export function relativeTime(value, now = Date.now()) {
  const millis = toMillis(value);
  if (!millis) return "";
  const seconds = Math.max(0, Math.round((now - millis) / 1000));
  if (seconds < 45) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

/** "840 ms" / "2.1 s" / "2m 14s". */
export function formatDuration(millis) {
  if (millis === null || millis === undefined || millis === "") return "";
  const value = Number(millis);
  if (!Number.isFinite(value) || value < 0) return "";
  if (value < 1000) return `${Math.round(value)} ms`;
  const seconds = value / 1000;
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} s`;
  const whole = Math.round(seconds);
  const minutes = Math.floor(whole / 60);
  const rest = whole % 60;
  if (minutes < 60) return rest ? `${minutes}m ${rest}s` : `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

export function shorten(text, max = 90) {
  const value = String(text ?? "").replace(/\s+/g, " ").trim();
  if (value.length <= max) return value;
  return `${value.slice(0, Math.max(0, max - 1)).trimEnd()}…`;
}

export function shortId(id) {
  const value = String(id ?? "");
  return value.length > 12 ? value.slice(0, 12) : value;
}

/** Defence in depth for the UI's one-line summaries.
 *
 *  The server sanitises paths at the serve layer (slice 3b), but the 82 logs
 *  already on disk were recorded before that and still contain absolute paths.
 *  A summary rendered from an old log must not leak the machine layout, and a
 *  secret-looking token must never be displayed.
 */
const PATH_PATTERN = /(?:[A-Za-z]:\\[^\s"'<>|]+|\/(?:home|Users|var|tmp|opt|private)\/[^\s"'<>|]+)/g;
const SECRET_PATTERN = /\b(?:sk-[A-Za-z0-9_-]{8,}|AIza[0-9A-Za-z_-]{10,})\b/g;

export function redactText(value) {
  return String(value ?? "")
    .replace(PATH_PATTERN, "[path]")
    .replace(SECRET_PATTERN, "[secret]");
}

