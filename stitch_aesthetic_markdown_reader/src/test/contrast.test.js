import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

/** WCAG 2.1 relative contrast, computed from the shipped tokens.
 *
 *  Parsing tokens.css (instead of duplicating hex values here) means a palette
 *  edit that lowers a text/surface contrast fails this test. No dependency is
 *  added: the formula is six lines from the WCAG definition. */

const CSS = readFileSync(resolve(process.cwd(), "src/styles/tokens.css"), "utf8");

function declarations(selectorStart) {
  const selector = CSS.indexOf(selectorStart);
  expect(selector, `${selectorStart} must exist in tokens.css`).toBeGreaterThanOrEqual(0);
  const open = CSS.indexOf("{", selector);
  let depth = 0;
  let close = open;
  for (; close < CSS.length; close += 1) {
    if (CSS[close] === "{") depth += 1;
    if (CSS[close] === "}") {
      depth -= 1;
      if (depth === 0) break;
    }
  }
  const values = {};
  for (const [, name, value] of CSS.slice(open + 1, close).matchAll(/--([a-z0-9-]+):\s*([^;]+);/g)) {
    values[name] = value.trim();
  }
  return values;
}

const light = { ...declarations(":root {"), ...declarations(':root,\n[data-theme="light"] {') };
const dark = declarations('[data-theme="dark"] {');

function luminance(hex) {
  const clean = hex.replace("#", "");
  const full =
    clean.length === 3
      ? [...clean].map((character) => character + character).join("")
      : clean;
  const [r, g, b] = [0, 2, 4]
    .map((index) => Number.parseInt(full.slice(index, index + 2), 16) / 255)
    .map((channel) =>
      channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4,
    );
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(foreground, background) {
  const one = luminance(foreground);
  const two = luminance(background);
  return (Math.max(one, two) + 0.05) / (Math.min(one, two) + 0.05);
}

// Every pair below is text drawn on a surface in the app (chips, badges,
// buttons, body copy). WCAG AA for normal text is 4.5:1.
const PAIRS = [
  ["ink", "bg"],
  ["ink", "surface"],
  ["ink", "surface-2"],
  ["ink", "accent-weak"],
  ["muted", "bg"],
  ["muted", "surface"],
  ["muted", "surface-2"],
  ["muted", "surface-3"],
  ["accent", "accent-weak"],
  ["accent", "surface"],
  ["accent-ink", "accent"],
  ["ok", "ok-weak"],
  ["warn", "warn-weak"],
  ["err", "err-weak"],
  ["blocked", "blocked-weak"],
  ["queued", "queued-weak"],
];

describe.each([
  ["light", light],
  ["dark", dark],
])("%s theme contrast", (name, theme) => {
  it.each(PAIRS)("%s on %s reaches 4.5:1", (foreground, background) => {
    for (const token of [foreground, background]) {
      expect(theme[token], `${name} theme is missing --${token}`).toMatch(/^#[0-9a-f]{3,6}$/i);
    }
    const ratio = contrast(theme[foreground], theme[background]);
    expect(
      Number(ratio.toFixed(2)),
      `${name}: --${foreground} (${theme[foreground]}) on --${background} (${theme[background]})`,
    ).toBeGreaterThanOrEqual(4.5);
  });
});
