import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

if (!globalThis.matchMedia) {
  globalThis.matchMedia = (query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener() {},
    removeListener() {},
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent() {
      return false;
    },
  });
}

if (!globalThis.requestAnimationFrame) {
  globalThis.requestAnimationFrame = (callback) => setTimeout(() => callback(Date.now()), 0);
  globalThis.cancelAnimationFrame = (id) => clearTimeout(id);
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  delete document.documentElement.dataset.theme;
  delete document.documentElement.dataset.themeSwitching;
  try {
    globalThis.localStorage?.clear();
  } catch {
    /* storage is optional in jsdom configurations */
  }
  try {
    globalThis.sessionStorage?.clear();
  } catch {
    /* storage is optional in jsdom configurations */
  }
});
