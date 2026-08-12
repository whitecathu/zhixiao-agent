import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  applyTheme,
  designTokens,
  getPreferredTheme,
  getSurfaceTokens,
  isDarkTheme,
  surfaceTokens,
} from "./theme";

describe("theme", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.classList.remove("dark");
  });

  afterEach(() => {
    localStorage.clear();
    document.documentElement.classList.remove("dark");
  });

  it("applies dark theme and persists choice", () => {
    applyTheme("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(localStorage.getItem("zhixiao-theme")).toBe("dark");
    expect(isDarkTheme()).toBe(true);
  });

  it("applies light theme and clears dark class", () => {
    applyTheme("dark");
    applyTheme("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(getPreferredTheme()).toBe("light");
  });

  it("restores stored preference over system default", () => {
    localStorage.setItem("zhixiao-theme", "dark");
    expect(getPreferredTheme()).toBe("dark");
  });

  it("exposes green brand and status design tokens", () => {
    expect(designTokens.brand.DEFAULT).toBe("#287d3c");
    expect(designTokens.status.running).toMatch(/^#/);
    expect(designTokens.spacing[4]).toBe(16);
    expect(designTokens.font.sans).toContain("Segoe UI");
  });

  it("returns coherent surface tokens for light and dark", () => {
    expect(getSurfaceTokens("light").surface).toBe(surfaceTokens.light.surface);
    applyTheme("dark");
    expect(getSurfaceTokens().mainBg).toBe(surfaceTokens.dark.mainBg);
  });
});
