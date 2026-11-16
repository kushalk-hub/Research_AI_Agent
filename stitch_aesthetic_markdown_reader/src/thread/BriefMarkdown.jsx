import { Fragment } from "react";
import { parseCitations, safeHttpUrl } from "../lib/citations.js";
import { parseMarkdown } from "../lib/markdown.js";
import { CitationChip } from "./Citations.jsx";

const INLINE =
  /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\n]+\*|\[[^\]]+\]\(https?:\/\/[^)\s]+\)|https?:\/\/[^\s<>()]+)/g;

function trailingPunctuation(value) {
  const match = /[.,;:!?]+$/.exec(value);
  return match ? match[0] : "";
}

function formatInline(text) {
  return text
    .split(INLINE)
    .filter((part) => part !== "")
    .map((part, index) => {
      if (/^\*\*[^*]+\*\*$/.test(part)) {
        return <strong key={index}>{part.slice(2, -2)}</strong>;
      }
      if (/^`[^`]+`$/.test(part)) {
        return <code key={index}>{part.slice(1, -1)}</code>;
      }
      if (/^\*[^*\n]+\*$/.test(part)) {
        return <em key={index}>{part.slice(1, -1)}</em>;
      }
      const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(part);
      if (link) {
        const url = safeHttpUrl(link[2]);
        if (!url) return <Fragment key={index}>{part}</Fragment>;
        return (
          <a key={index} href={url} target="_blank" rel="noreferrer noopener">
            {link[1]}
          </a>
        );
      }
      if (part.startsWith("http://") || part.startsWith("https://")) {
        const trailing = trailingPunctuation(part);
        const body = trailing ? part.slice(0, -trailing.length) : part;
        const url = safeHttpUrl(body);
        if (!url) return <Fragment key={index}>{part}</Fragment>;
        return (
          <Fragment key={index}>
            <a href={url} target="_blank" rel="noreferrer noopener">
              {body}
            </a>
            {trailing}
          </Fragment>
        );
      }
      return <Fragment key={index}>{part}</Fragment>;
    });
}

function Inline({ text, onCitation, selected, active }) {
  return parseCitations(text).map((segment, index) =>
    segment.type === "text" ? (
      <Fragment key={`t-${index}`}>{formatInline(segment.text)}</Fragment>
    ) : (
      <Fragment key={`c-${index}`}>
        {segment.labels.map((label, position) => (
          <CitationChip
            key={`${label}-${position}`}
            label={label}
            selected={selected === label}
            active={active === label}
            onSelect={onCitation}
          />
        ))}
      </Fragment>
    ),
  );
}

/** Render parsed blocks as React nodes. No HTML string is ever injected. */
export default function BriefMarkdown({ markdown, onCitation, selected = "", active = "" }) {
  const blocks = parseMarkdown(markdown);
  return (
    <div className="brief-markdown">
      {blocks.map((block, index) => {
        const inline = (text) => (
          <Inline
            text={text}
            onCitation={onCitation}
            selected={selected}
            active={active}
          />
        );
        switch (block.type) {
          case "heading": {
            const Tag = `h${Math.min(block.level, 4)}`;
            return <Tag key={index}>{inline(block.text)}</Tag>;
          }
          case "rule":
            return (
              <hr key={index} className="brief-rule" aria-hidden="true" />
            );
          case "quote":
            return <blockquote key={index}>{inline(block.text)}</blockquote>;
          case "code":
            return (
              <pre key={index} className="brief-code">
                <code>{block.text}</code>
              </pre>
            );
          case "list": {
            const Tag = block.ordered ? "ol" : "ul";
            return (
              <Tag key={index} className="brief-list">
                {block.items.map((item, itemIndex) => {
                  const source = /^\s*\[([PC]\d+)\]/.exec(item)?.[1] || "";
                  return (
                    <li
                      key={itemIndex}
                      data-source={source || undefined}
                      data-active={
                        source && selected === source ? "true" : undefined
                      }
                    >
                      {inline(item)}
                    </li>
                  );
                })}
              </Tag>
            );
          }
          case "table":
            return (
              <div key={index} className="brief-table-wrap">
                <table className="brief-table">
                  <thead>
                    <tr>
                      {block.header.map((cell, cellIndex) => (
                        <th key={cellIndex} scope="col">
                          {inline(cell)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {block.rows.map((row, rowIndex) => (
                      <tr key={rowIndex}>
                        {row.map((cell, cellIndex) => (
                          <td key={cellIndex}>{inline(cell)}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          default:
            return <p key={index}>{inline(block.text)}</p>;
        }
      })}
    </div>
  );
}
