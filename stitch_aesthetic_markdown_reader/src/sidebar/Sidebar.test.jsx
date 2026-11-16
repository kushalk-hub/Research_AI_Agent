import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import Sidebar from "./Sidebar.jsx";
import { StoreProvider } from "../store/store.jsx";

const now = Date.now();

function renderSidebar(props = {}) {
  return render(
    <StoreProvider>
      <Sidebar
        page="research"
        connection="ready"
        recents={[]}
        onNavigate={() => {}}
        onNew={() => {}}
        onOpenRecent={() => {}}
        onRefreshHistory={() => {}}
        {...props}
      />
    </StoreProvider>,
  );
}

describe("Sidebar recents", () => {
  it("distinguishes identical demo runs with a status dot, a relative time and an id", () => {
    renderSidebar({
      recents: [
        {
          run_id: "0123456789ab",
          topic: "Deterministic demo",
          mode: "simulate",
          status: "completed",
          at: now - 120_000,
        },
        {
          run_id: "ba9876543210",
          topic: "Deterministic demo",
          mode: "simulate",
          status: "failed",
          at: now - 7_200_000,
        },
      ],
    });

    const rows = screen.getAllByRole("button", { name: /deterministic demo/i });
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText("2m ago")).toBeTruthy();
    expect(within(rows[1]).getByText("2h ago")).toBeTruthy();
    expect(within(rows[0]).getByText("Completed")).toBeTruthy();
    expect(within(rows[1]).getByText("Failed")).toBeTruthy();
    expect(rows[0].querySelector(".recent-dot").dataset.tone).toBe("ok");
    expect(rows[1].querySelector(".recent-dot").dataset.tone).toBe("err");
    expect(within(rows[0]).getByText("0123456789ab")).toBeTruthy();
  });

  it("marks a replay with a badge", () => {
    renderSidebar({
      recents: [
        {
          run_id: "0123456789ab",
          topic: "Replayed run",
          mode: "replay",
          status: "completed",
          at: now - 60_000,
        },
      ],
    });
    expect(screen.getByText("Replay", { selector: ".recent-badge" })).toBeTruthy();
  });

  it("omits a time when the record has no timestamp", () => {
    renderSidebar({
      recents: [
        { run_id: "0123456789ab", topic: "Untimed run", mode: "live", status: "completed" },
      ],
    });
    expect(screen.queryByText(/ago|just now/)).toBeNull();
  });
});

describe("Sidebar footer", () => {
  it("reports the runtime state and keeps the theme control compact", () => {
    renderSidebar();
    expect(screen.getByText("Local runtime ready")).toBeTruthy();
    const toggle = screen.getByRole("button", { name: /system theme/i });
    expect(toggle.className).toContain("theme-toggle--compact");
    expect(toggle.title).toMatch(/system theme/i);
  });

  it("reports an unreachable runtime", () => {
    renderSidebar({ connection: "down" });
    expect(screen.getByText("Runtime unreachable")).toBeTruthy();
  });
});
