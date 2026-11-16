/** A small parser for the Markdown the two brief writers emit.
 *
 *  Design §8 deviation 2: no `react-markdown` for a fixed, machine-generated
 *  subset. The parser never executes or interprets HTML; the renderer turns
 *  every block's text into React text nodes. Supported: ATX headings, fenced
 *  code, horizontal rules, blockquotes, ordered/unordered lists, GFM tables
 *  and paragraphs.
 */

function splitRow(line) {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function isRule(line) {
  return /^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line);
}

function isTableDivider(line) {
  if (!line.includes("|")) return false;
  return splitRow(line).every((cell) => /^:?-{3,}:?$/.test(cell));
}

function startsBlock(line) {
  if (!line.trim()) return true;
  if (/^\s*```/.test(line)) return true;
  if (/^#{1,6}\s+/.test(line)) return true;
  if (isRule(line)) return true;
  if (/^\s*>\s?/.test(line)) return true;
  if (/^\s*(?:[-*+]|\d+[.)])\s+/.test(line)) return true;
  return false;
}

export function parseMarkdown(source = "") {
  const lines = String(source).replace(/\r\n?/g, "\n").split("\n");
  const blocks = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }

    if (/^\s*```/.test(line)) {
      const language = line.trim().slice(3).trim();
      index += 1;
      const body = [];
      while (index < lines.length && !/^\s*```/.test(lines[index])) {
        body.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
      blocks.push({ type: "code", language, text: body.join("\n") });
      continue;
    }

    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      blocks.push({ type: "heading", level: heading[1].length, text: heading[2].trim() });
      index += 1;
      continue;
    }

    if (isRule(line)) {
      blocks.push({ type: "rule" });
      index += 1;
      continue;
    }

    if (/^\s*>\s?/.test(line)) {
      const body = [];
      while (index < lines.length && /^\s*>\s?/.test(lines[index])) {
        body.push(lines[index].replace(/^\s*>\s?/, ""));
        index += 1;
      }
      blocks.push({ type: "quote", text: body.join("\n") });
      continue;
    }

    if (/^\s*[-*+]\s+/.test(line) || /^\s*\d+[.)]\s+/.test(line)) {
      const ordered = /^\s*\d+[.)]\s+/.test(line);
      const items = [];
      while (index < lines.length) {
        const candidate = lines[index];
        const match = ordered
          ? /^\s*\d+[.)]\s+(.*)$/.exec(candidate)
          : /^\s*[-*+]\s+(.*)$/.exec(candidate);
        if (!match) break;
        items.push(match[1]);
        index += 1;
      }
      blocks.push({ type: "list", ordered, items });
      continue;
    }

    if (line.includes("|") && index + 1 < lines.length && isTableDivider(lines[index + 1])) {
      const header = splitRow(line);
      index += 2;
      const rows = [];
      while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
        rows.push(splitRow(lines[index]));
        index += 1;
      }
      blocks.push({ type: "table", header, rows });
      continue;
    }

    const paragraph = [line.trim()];
    index += 1;
    while (index < lines.length && !startsBlock(lines[index])) {
      paragraph.push(lines[index].trim());
      index += 1;
    }
    blocks.push({ type: "paragraph", text: paragraph.join(" ") });
  }

  return blocks;
}
