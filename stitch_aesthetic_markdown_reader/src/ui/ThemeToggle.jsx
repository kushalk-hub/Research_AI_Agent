import { Monitor, Moon, Sun } from "lucide-react";
import { useDispatch, useStore } from "../store/store.jsx";

const NEXT = { system: "light", light: "dark", dark: "system" };
const LABEL = { system: "System theme", light: "Light theme", dark: "Dark theme" };
const ICON = { system: Monitor, light: Sun, dark: Moon };

/** Cycles system → light → dark. Writes `data-theme` on <html>; never an inline
 *  style attribute, because the served build blocks inline styles. */
export default function ThemeToggle() {
  const { theme } = useStore();
  const dispatch = useDispatch();
  const next = NEXT[theme] || "system";
  const Icon = ICON[theme] || Monitor;

  return (
    <button
      type="button"
      className="btn btn--ghost btn--sm"
      aria-label={`${LABEL[theme]}. Switch to ${LABEL[next].toLowerCase()}.`}
      title={`${LABEL[theme]} — click for ${LABEL[next].toLowerCase()}`}
      onClick={() => dispatch({ type: "ui/theme", theme: next })}
    >
      <Icon size={16} aria-hidden="true" />
      <span>{LABEL[theme]}</span>
    </button>
  );
}
