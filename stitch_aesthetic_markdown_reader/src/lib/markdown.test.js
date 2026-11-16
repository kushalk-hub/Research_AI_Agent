import { describe, expect, it } from "vitest";
import { parseMarkdown } from "./markdown.js";

/** The parser exists only for the Markdown the two brief writers emit
 *  (design §8 deviation 2). These tests pin the supported subset and, just as
 *  importantly, that everything else survives as literal text. */

describe("parseMarkdown blocks", () => {
  it("returns nothing for empty or whitespace-only input", () => {
    expect(parseMarkdown("")).toEqual([]);
    expect(parseMarkdown("\n \n\r\n")).toEqual([]);
  });

  it("parses ATX headings at every level the writer can emit", () => {
    const blocks = parseMarkdown("# One\n\n### Three\n\n###### Six");
    expect(blocks).toEqual([
      { type: "heading", level: 1, text: "One" },
      { type: "heading", level: 3, text: "Three" },
      { type: "heading", level: 6, text: "Six" },
    ]);
  });

  it("parses the RLA brief shape: heading, italic byline, rule, bold, list", () => {
    const source = [
      "# What are the challenges?",
      "",
      "*factual traversal*",
      "",
      "---",
      "",
      "**Subgraph used**",
      "",
      "- [P1] Paper 2024: name",
    ].join("\n");

    expect(parseMarkdown(source).map((block) => block.type)).toEqual([
      "heading",
      "paragraph",
      "rule",
      "paragraph",
      "list",
    ]);
  });

  it("treats --- and *** as rules but keeps - item as a list", () => {
    const blocks = parseMarkdown("***\n\n- item\n\n---");
    expect(blocks).toEqual([
      { type: "rule" },
      { type: "list", ordered: false, items: ["item"] },
      { type: "rule" },
    ]);
  });

  it("keeps fenced code verbatim, including rules and pipes inside it", () => {
    const source = ["```markdown", "# not a heading", "---", "| a | b |", "```"].join("\n");
    expect(parseMarkdown(source)).toEqual([
      {
        type: "code",
        language: "markdown",
        text: "# not a heading\n---\n| a | b |",
      },
    ]);
  });

  it("closes an unterminated fence at end of input instead of dropping it", () => {
    expect(parseMarkdown("```\nconst x = 1;")).toEqual([
      { type: "code", language: "", text: "const x = 1;" },
    ]);
  });

  it("joins multi-line blockquotes and keeps the quote marker out of the text", () => {
    expect(parseMarkdown("> Stripped 2 ids: [P9], [P8]\n> and more")).toEqual([
      { type: "quote", text: "Stripped 2 ids: [P9], [P8]\nand more" },
    ]);
  });

  it("parses unordered and ordered lists as separate blocks", () => {
    const source = ["- [P1] First", "- [P2] Second", "", "1. one", "2. two"].join("\n");
    expect(parseMarkdown(source)).toEqual([
      { type: "list", ordered: false, items: ["[P1] First", "[P2] Second"] },
      { type: "list", ordered: true, items: ["one", "two"] },
    ]);
  });

  it("parses a GFM table and strips the outer pipes", () => {
    const source = ["| Label | Value |", "| :--- | ---: |", "| [P1] | 2024 |"].join("\n");
    expect(parseMarkdown(source)).toEqual([
      {
        type: "table",
        header: ["Label", "Value"],
        rows: [["[P1]", "2024"]],
      },
    ]);
  });

  it("keeps a pipe row as a paragraph when there is no divider", () => {
    expect(parseMarkdown("a | b | c")).toEqual([
      { type: "paragraph", text: "a | b | c" },
    ]);
  });

  it("joins wrapped paragraph lines with a single space and normalises CRLF", () => {
    expect(parseMarkdown("first line\r\nsecond line\r\n\r\nnext")).toEqual([
      { type: "paragraph", text: "first line second line" },
      { type: "paragraph", text: "next" },
    ]);
  });

  it("never produces an HTML block: tags stay in the text", () => {
    const source = [
      "<script>alert(1)</script>",
      "",
      "<img src=x onerror=alert(2)>",
      "",
      "- <b>bold?</b>",
    ].join("\n");

    const blocks = parseMarkdown(source);
    expect(blocks.map((block) => block.type)).toEqual(["paragraph", "paragraph", "list"]);
    expect(blocks[0].text).toBe("<script>alert(1)</script>");
    expect(blocks[1].text).toBe("<img src=x onerror=alert(2)>");
    expect(blocks[2].items).toEqual(["<b>bold?</b>"]);
    expect(JSON.stringify(blocks)).not.toContain('"type":"html"');
  });

  it("parses the real demo brief shape without losing a line", () => {
    const source = [
      "# Evidence-backed brief: Deterministic demo",
      "",
      "**Question:** How does the scheduler work?",
      "",
      "Evidence-backed response to: How does the scheduler work?",
      "",
      "- Graph Transformers: This work studies graph transformers. [P1]",
      "- Graph Attention Networks: Masked self-attentional layers. [P2]",
      "",
      "## Sources",
      "",
      "- [P1] Graph Transformers - https://example.org/papers/1",
      "- [P2] Graph Attention Networks - https://example.org/papers/2",
    ].join("\n");

    const blocks = parseMarkdown(source);
    expect(blocks.map((block) => block.type)).toEqual([
      "heading",
      "paragraph",
      "paragraph",
      "list",
      "heading",
      "list",
    ]);
    expect(blocks[3].items).toHaveLength(2);
    expect(blocks[5].items[0]).toBe("[P1] Graph Transformers - https://example.org/papers/1");
  });
});
