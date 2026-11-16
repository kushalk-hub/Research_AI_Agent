import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { act } from "react";
import { describe, expect, it, vi } from "vitest";
import BriefOverlay from "./BriefOverlay.jsx";

const { briefDocument } = vi.hoisted(() => ({ briefDocument: vi.fn() }));

vi.mock("../api/client.js", () => ({
  api: { briefDocument },
}));

function failure(message, code) {
  return Object.assign(new Error(message), { code });
}

function documentWith(markdown) {
  return { run_id: "0123456789ab", markdown, citations: [], sources: [] };
}

function renderOverlay(overrides = {}) {
  const onClose = vi.fn();
  const result = render(
    <BriefOverlay runId="0123456789ab" onClose={onClose} {...overrides} />,
  );
  return { onClose, ...result };
}

function stubScrollIntoView() {
  const calls = [];
  Element.prototype.scrollIntoView = vi.fn(function record(options) {
    calls.push({ node: this, options });
  });
  return calls;
}

describe("BriefOverlay", () => {
  it("shows a loading note, then the saved brief as a modal drawer", async () => {
    let resolve;
    briefDocument.mockReturnValue(new Promise((done) => (resolve = done)));
    renderOverlay();

    const dialog = screen.getByRole("dialog", { name: "Research brief" });
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(screen.getByRole("status").textContent).toMatch(/Reading the saved brief/);

    await act(async () => {
      resolve(documentWith("# Saved brief\n\nThe graph holds. [P1]"));
    });

    expect(screen.getByRole("heading", { name: "Saved brief" })).toBeTruthy();
    expect(screen.getByText(/The graph holds\./)).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /Select evidence for \[P1\]/ }).length).toBe(1);
  });

  it("asks for the JSON document and never a raw Markdown tab", async () => {
    const open = vi.spyOn(window, "open");
    briefDocument.mockResolvedValue(documentWith("# Brief"));
    renderOverlay();
    await waitFor(() => expect(screen.getByRole("heading", { name: "Brief" })).toBeTruthy());

    expect(briefDocument).toHaveBeenCalledWith("0123456789ab");
    const download = screen.getByRole("link", { name: /Download \.md/i });
    expect(download.getAttribute("href")).toBe("/api/runs/0123456789ab/brief?download=1");
    expect(download.hasAttribute("download")).toBe(true);
    expect(download.getAttribute("target")).toBeNull();
    expect(open).not.toHaveBeenCalled();
  });

  it("states when the run has no saved brief", async () => {
    briefDocument.mockRejectedValue(failure("no saved brief", "brief_not_found"));
    renderOverlay();

    const note = await screen.findByText(/No saved brief for this run/);
    expect(note.getAttribute("role")).toBe("status");
    expect(document.querySelector(".brief-markdown")).toBeNull();
  });

  it("shows the recorded failure message instead of an empty drawer", async () => {
    briefDocument.mockRejectedValue(
      failure("the saved brief is larger than the 2 MiB limit", "brief_too_large"),
    );
    renderOverlay();

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/2 MiB limit/);
  });

  it("renders file content as text, never as elements", async () => {
    briefDocument.mockResolvedValue(
      documentWith(
        [
          "# Safe heading <script>alert('h')</script>",
          "",
          "<script>alert(1)</script>",
          "",
          "<img src=x onerror=\"alert(2)\">",
          "",
          "[click](javascript:alert(3))",
          "",
          "- [P1] <b>evidence</b> https://example.org/paper",
        ].join("\n"),
      ),
    );
    renderOverlay();
    const heading = await screen.findByRole("heading", { level: 1 });

    expect(heading.textContent).toContain("<script>alert('h')</script>");
    expect(document.querySelector("script")).toBeNull();
    expect(document.querySelector("img")).toBeNull();
    expect(screen.getByText("<script>alert(1)</script>")).toBeTruthy();
    expect(screen.getByText('<img src=x onerror="alert(2)">')).toBeTruthy();
    expect(screen.getByText("[click](javascript:alert(3))")).toBeTruthy();
    expect(document.querySelector('a[href^="javascript:"]')).toBeNull();

    const safe = document.querySelector('a[href="https://example.org/paper"]');
    expect(safe.getAttribute("rel")).toBe("noreferrer noopener");
  });

  it("closes on Escape and on the backdrop, and returns focus to the opener", async () => {
    briefDocument.mockResolvedValue(documentWith("# Brief"));
    const opener = document.createElement("button");
    opener.textContent = "Open brief";
    document.body.appendChild(opener);
    opener.focus();

    const { onClose, unmount } = renderOverlay();
    await screen.findByRole("heading", { name: "Brief" });
    expect(document.body.classList.contains("overlay-open")).toBe(true);

    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);

    unmount();
    expect(document.body.classList.contains("overlay-open")).toBe(false);
    expect(document.activeElement).toBe(opener);
    opener.remove();
  });

  it("traps Tab inside the dialog", async () => {
    briefDocument.mockResolvedValue(documentWith("# Brief"));
    renderOverlay();
    await screen.findByRole("heading", { name: "Brief" });

    const closeButton = screen.getByRole("button", { name: "Close" });
    const copyButton = screen.getByRole("button", { name: "Copy" });
    // Mount focus lands on Close, the last focusable control.
    expect(document.activeElement).toBe(closeButton);

    fireEvent.keyDown(document, { key: "Tab" });
    expect(document.activeElement).toBe(copyButton);

    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(closeButton);
  });

  it("only says Copied after the clipboard write resolves", async () => {
    briefDocument.mockResolvedValue(documentWith("# Brief\n\nbody text"));
    let resolve;
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn(() => new Promise((done) => (resolve = done))) },
    });

    try {
      renderOverlay();
      await screen.findByRole("heading", { name: "Brief" });
      fireEvent.click(screen.getByRole("button", { name: "Copy" }));

      expect(navigator.clipboard.writeText).toHaveBeenCalledWith("# Brief\n\nbody text");
      expect(screen.getByRole("button", { name: "Copy" })).toBeTruthy();

      await act(async () => resolve());
      expect(screen.getByRole("button", { name: "Copied" })).toBeTruthy();
    } finally {
      delete navigator.clipboard;
    }
  });

  it("reports a failed copy rather than claiming success", async () => {
    briefDocument.mockResolvedValue(documentWith("# Brief"));
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
    });

    try {
      renderOverlay();
      await screen.findByRole("heading", { name: "Brief" });
      fireEvent.click(screen.getByRole("button", { name: "Copy" }));
      expect(await screen.findByRole("button", { name: "Copy failed" })).toBeTruthy();
    } finally {
      delete navigator.clipboard;
    }
  });

  it("highlights and scrolls the matching source row for a citation chip", async () => {
    const calls = stubScrollIntoView();
    briefDocument.mockResolvedValue(
      documentWith(
        ["# Brief", "", "Holds [P2].", "", "## Sources", "", "- [P1] First", "- [P2] Second"].join(
          "\n",
        ),
      ),
    );

    try {
      renderOverlay();
      await screen.findByRole("heading", { name: "Brief" });

      const dialog = document.querySelector(".brief-dialog");
      const chip = dialog.querySelector('.brief-markdown .cite-chip[data-citation="P2"]');
      fireEvent.click(chip);

      const row = dialog.querySelector('.brief-list li[data-source="P2"]');
      expect(row.getAttribute("data-active")).toBe("true");
      expect(
        dialog.querySelector('.brief-list li[data-source="P1"]').getAttribute("data-active"),
      ).toBeNull();
      expect(calls.at(-1).node).toBe(row);
      expect(calls.at(-1).options).toEqual({ block: "nearest", behavior: "smooth" });
    } finally {
      delete Element.prototype.scrollIntoView;
    }
  });
});
