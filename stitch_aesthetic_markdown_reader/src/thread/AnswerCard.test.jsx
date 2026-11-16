import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import AnswerCard from "./AnswerCard.jsx";

const { briefDocument } = vi.hoisted(() => ({ briefDocument: vi.fn() }));

vi.mock("../api/client.js", () => ({
  api: { briefDocument },
}));

function card(citation, overrides = {}) {
  return {
    citation,
    kind: citation.startsWith("C") ? "concept" : "paper",
    missing: false,
    title: `Card ${citation}`,
    year: 2024,
    authors: [],
    venue: "",
    abstract: "",
    doi: "",
    url: "",
    ...overrides,
  };
}

const ANSWER = {
  seq: 4,
  text: "The graph holds [P1].",
  questionType: "factual",
  citations: ["P1"],
  evidence: [card("P1")],
  stripped: [],
};

describe("AnswerCard brief wiring", () => {
  it("opens the saved brief for this run in a drawer, not a new tab", async () => {
    briefDocument.mockResolvedValue({ run_id: "0123456789ab", markdown: "# The brief" });
    render(<AnswerCard answer={ANSWER} runId="0123456789ab" />);

    fireEvent.click(screen.getByRole("button", { name: "Open brief" }));

    const dialog = await screen.findByRole("dialog", { name: "Research brief" });
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(briefDocument).toHaveBeenCalledWith("0123456789ab");
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "The brief" })).toBeTruthy(),
    );
  });

  it("returns focus to Open brief when the drawer closes", async () => {
    briefDocument.mockResolvedValue({ run_id: "0123456789ab", markdown: "# The brief" });
    render(<AnswerCard answer={ANSWER} runId="0123456789ab" />);

    const opener = screen.getByRole("button", { name: "Open brief" });
    opener.focus();
    fireEvent.click(opener);
    await screen.findByRole("dialog", { name: "Research brief" });

    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Research brief" })).toBeNull(),
    );
    expect(document.activeElement).toBe(opener);
    expect(document.body.classList.contains("overlay-open")).toBe(false);
  });

  it("still shows the evidence column while the brief is closed", () => {
    render(<AnswerCard answer={ANSWER} runId="0123456789ab" />);
    expect(screen.getByRole("region", { name: "Evidence (1)" })).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(briefDocument).not.toHaveBeenCalled();
  });
});
