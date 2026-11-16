import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import LibraryView from "./LibraryView.jsx";

const history = [
  {
    run_id: "0123456789ab",
    topic: "Graph stores",
    mode: "simulate",
    status: "completed",
    event_count: 114,
    elapsed_ms: 2100,
  },
  {
    run_id: "ba9876543210",
    topic: "Citation drift",
    mode: "replay",
    status: "partial",
    event_count: 55,
    elapsed_ms: null,
  },
];

describe("LibraryView", () => {
  it("lists recorded runs with their measured fields and honest gaps", () => {
    render(<LibraryView history={history} onReplay={() => {}} />);
    expect(screen.getByText("2 recorded runs")).toBeTruthy();
    expect(screen.getByText("Graph stores")).toBeTruthy();
    expect(screen.getByText("2.1 s")).toBeTruthy();
    expect(screen.getByText("not recorded")).toBeTruthy();
    expect(screen.getByText(/does not re-execute providers or models/)).toBeTruthy();
  });

  it("filters by topic, id, mode or status", () => {
    render(<LibraryView history={history} onReplay={() => {}} />);
    fireEvent.change(screen.getByLabelText(/filter runs/i), { target: { value: "drift" } });
    expect(screen.getByText("Citation drift")).toBeTruthy();
    expect(screen.queryByText("Graph stores")).toBeNull();
    expect(screen.getByText("1 of 2 recorded runs")).toBeTruthy();
  });

  it("replays the exact run id and disables replay while another run is live", () => {
    const onReplay = vi.fn();
    const { rerender } = render(<LibraryView history={history} onReplay={onReplay} />);
    const row = screen.getByText("Graph stores").closest("tr");
    fireEvent.click(within(row).getByRole("button", { name: /replay/i }));
    expect(onReplay).toHaveBeenCalledWith("0123456789ab");

    rerender(<LibraryView history={history} onReplay={onReplay} liveActive />);
    expect(within(row).getByRole("button", { name: /replay/i }).disabled).toBe(true);
  });

  it("says so when there is nothing recorded", () => {
    render(<LibraryView history={[]} onReplay={() => {}} />);
    expect(screen.getByText("No runs recorded yet.")).toBeTruthy();
  });
});
