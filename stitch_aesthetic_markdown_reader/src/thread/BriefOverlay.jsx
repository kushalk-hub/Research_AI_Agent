import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../api/client.js";
import BriefMarkdown from "./BriefMarkdown.jsx";

function reducedMotion() {
  return Boolean(
    typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
}

/** The saved brief, rendered in place (UI-10).
 *
 *  Never a new tab. The endpoint is read as JSON so the overlay can show the
 *  run id, citations and sources; `?download=1` stays the only download path.
 *  Markdown is rendered as React nodes (slice 6), so file content cannot
 *  create elements. Esc closes, Tab is trapped, and focus returns to whatever
 *  opened the drawer. */
export default function BriefOverlay({ runId, onClose }) {
  const [status, setStatus] = useState({ state: "loading" });
  const [copyState, setCopyState] = useState("");
  const [selected, setSelected] = useState("");
  const dialogRef = useRef(null);
  const closeRef = useRef(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  const close = useCallback(() => onCloseRef.current?.(), []);

  useEffect(() => {
    let alive = true;
    setStatus({ state: "loading" });
    api
      .briefDocument(runId)
      .then((document) => {
        if (alive) setStatus({ state: "ready", document });
      })
      .catch((reason) => {
        if (!alive) return;
        if (reason?.code === "brief_not_found") {
          setStatus({ state: "missing" });
        } else {
          setStatus({
            state: "error",
            message: reason?.message || "The saved brief could not be read.",
          });
        }
      });
    return () => {
      alive = false;
    };
  }, [runId]);

  useEffect(() => {
    const opener = typeof document !== "undefined" ? document.activeElement : null;
    document.body.classList.add("overlay-open");
    closeRef.current?.focus();

    function onKeyDown(event) {
      if (event.key === "Escape") {
        event.preventDefault();
        close();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = [
        ...dialogRef.current.querySelectorAll(
          'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      ].filter(
        (node) =>
          node.getAttribute("aria-hidden") !== "true" &&
          !node.hidden &&
          !node.closest("[hidden]") &&
          !node.closest('[aria-hidden="true"]'),
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.classList.remove("overlay-open");
      opener?.focus?.();
    };
  }, [close]);

  useEffect(() => {
    if (!selected || !dialogRef.current) return;
    const row = dialogRef.current.querySelector(`[data-source="${selected}"]`);
    if (!row || typeof row.scrollIntoView !== "function") return;
    row.scrollIntoView({
      block: "nearest",
      behavior: reducedMotion() ? "auto" : "smooth",
    });
  }, [selected, status.state]);

  async function copyBrief() {
    if (status.state !== "ready") return;
    try {
      if (!navigator.clipboard?.writeText) throw new Error("clipboard unavailable");
      await navigator.clipboard.writeText(status.document.markdown);
      setCopyState("Copied");
    } catch {
      setCopyState("Copy failed");
    }
  }

  if (typeof document === "undefined") return null;

  return createPortal(
    <div
      className="overlay-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) close();
      }}
    >
      <div
        className="brief-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="brief-dialog-title"
        ref={dialogRef}
      >
        <header className="brief-head">
          <h2 id="brief-dialog-title" className="brief-dialog-title">
            Research brief
          </h2>
          <div className="brief-actions">
            <button
              type="button"
              className="btn btn--sm"
              onClick={copyBrief}
              disabled={status.state !== "ready"}
            >
              {copyState || "Copy"}
            </button>
            <a
              className="btn btn--sm"
              href={`/api/runs/${runId}/brief?download=1`}
              download={`${runId}.md`}
            >
              Download .md
            </a>
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              onClick={close}
              ref={closeRef}
            >
              Close
            </button>
          </div>
        </header>

        <div className="brief-body">
          {status.state === "loading" && (
            <p className="brief-note" role="status">
              Reading the saved brief…
            </p>
          )}

          {status.state === "missing" && (
            <p className="brief-note" role="status">
              No saved brief for this run. A brief is written only when citation
              validation and the evidence check both pass.
            </p>
          )}

          {status.state === "error" && (
            <p className="banner-error" role="alert">
              {status.message}
            </p>
          )}

          {status.state === "ready" && (
            <BriefMarkdown
              markdown={status.document.markdown}
              onCitation={(label) =>
                setSelected((current) => (current === label ? "" : label))
              }
              selected={selected}
              active={selected}
            />
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
