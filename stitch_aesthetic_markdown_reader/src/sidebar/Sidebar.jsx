import { Plus, RotateCw } from "lucide-react";
import { ROUTES } from "../app/routes.js";
import { modeShort, statusLabel, statusTone } from "../lib/events.js";
import { relativeTime, toMillis } from "../lib/format.js";
import ThemeToggle from "../ui/ThemeToggle.jsx";

function absoluteTime(value) {
  const millis = toMillis(value);
  return millis ? new Date(millis).toISOString() : "";
}

export default function Sidebar({
  page,
  onNavigate,
  onNew,
  onOpenRecent,
  onRefreshHistory,
  recents = [],
  connection = "connecting",
}) {
  const ready = connection === "ready";

  return (
    <aside className="sidebar" aria-label="Workspace">
      <a
        className="sidebar-brand"
        href="#research"
        onClick={(event) => {
          event.preventDefault();
          onNavigate("research");
        }}
      >
        <span className="brand-mark" aria-hidden="true">
          F
        </span>
        <span className="brand-text">
          <strong>FODS</strong>
          <span>Research Studio</span>
        </span>
      </a>

      <button type="button" className="sidebar-new" onClick={onNew} title="New investigation (N)">
        <Plus size={16} aria-hidden="true" />
        <span>New investigation</span>
        <kbd>N</kbd>
      </button>

      <nav className="nav" aria-label="Primary">
        {ROUTES.map((route) => {
          const Icon = route.icon;
          return (
            <button
              key={route.key}
              type="button"
              className="nav-link"
              aria-current={page === route.key ? "page" : undefined}
              onClick={() => onNavigate(route.key)}
            >
              <Icon size={17} aria-hidden="true" />
              <span>{route.label}</span>
            </button>
          );
        })}
      </nav>

      <div className="recents">
        <div className="section-label">
          <span>Recent runs</span>
          <button
            type="button"
            className="icon-btn"
            aria-label="Refresh recent runs"
            title="Refresh recent runs"
            onClick={onRefreshHistory}
          >
            <RotateCw size={13} aria-hidden="true" />
          </button>
        </div>

        <div className="recent-list">
          {recents.slice(0, 12).map((item) => (
            <button
              key={item.run_id}
              type="button"
              className="recent"
              aria-current={item.live ? "true" : undefined}
              onClick={() => onOpenRecent(item)}
              title={`${item.topic || "Untitled investigation"} — ${modeShort(item.mode)} · ${statusLabel(item.status)}${item.at ? ` · ${absoluteTime(item.at)}` : ""}`}
            >
              <span className="recent-title">{item.topic || "Untitled investigation"}</span>
              <span className="recent-meta">
                <i
                  className="recent-dot"
                  data-tone={statusTone(item.status)}
                  aria-hidden="true"
                />
                <span className="visually-hidden">{statusLabel(item.status)}</span>
                {item.mode === "replay" && <span className="badge recent-badge">Replay</span>}
                {item.at ? (
                  <time
                    className="recent-time"
                    dateTime={absoluteTime(item.at)}
                    title={absoluteTime(item.at)}
                  >
                    {relativeTime(item.at)}
                  </time>
                ) : null}
                <code>{item.run_id}</code>
              </span>
            </button>
          ))}
          {recents.length === 0 && <p className="recent-empty">No runs recorded yet.</p>}
        </div>
      </div>

      <div className="sidebar-foot">
        <span
          className="conn"
          data-state={ready ? "ready" : connection === "down" ? "down" : "connecting"}
        >
          <i aria-hidden="true" />
          <span className="conn-label">
            {ready
              ? "Local runtime ready"
              : connection === "down"
                ? "Runtime unreachable"
                : "Connecting…"}
          </span>
        </span>
        <ThemeToggle compact />
      </div>
    </aside>
  );
}
