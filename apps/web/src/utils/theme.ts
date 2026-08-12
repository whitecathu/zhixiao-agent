const STORAGE_KEY = "zhixiao-theme";

export type ThemeMode = "light" | "dark";

/** Shared design tokens for programmatic use (charts, canvas, inline styles). */
export const designTokens = {
  brand: {
    DEFAULT: "#287d3c",
    hover: "#226b33",
    active: "#1c582a",
    soft: "#edf8ef",
    accent: "#9eef6b",
    onDark: "#7fda83",
  },
  spacing: {
    1: 4,
    2: 8,
    3: 12,
    4: 16,
    5: 20,
    6: 24,
    7: 32,
    8: 40,
    9: 48,
    10: 64,
  },
  type: {
    xs: 11,
    sm: 12,
    base: 14,
    md: 15,
    lg: 17,
    xl: 21,
    "2xl": 27,
    "3xl": 34,
    "4xl": 42,
  },
  status: {
    success: "#17a768",
    warning: "#c47d0e",
    danger: "#d9534f",
    info: "#2d7a9c",
    running: "#2d8a72",
    idle: "#88919d",
  },
  font: {
    sans: '"Segoe UI Variable", "Segoe UI", "PingFang SC", "Noto Sans SC", "Microsoft YaHei", sans-serif',
    mono: '"Cascadia Code", "SFMono-Regular", Consolas, "Liberation Mono", monospace',
  },
} as const;

export const surfaceTokens = {
  light: {
    mainBg: "#f2f3ef",
    surface: "#ffffff",
    surfaceRaised: "#ffffff",
    surfaceSoft: "#f7f8f5",
    surfaceSunken: "#eceee9",
    asideBg: "#101612",
    border: "#dfe3dc",
    borderStrong: "#c5cec4",
    text: "#182019",
    textMuted: "#69736b",
  },
  dark: {
    mainBg: "#111512",
    surface: "#171d18",
    surfaceRaised: "#1c241e",
    surfaceSoft: "#1d241f",
    surfaceSunken: "#141a15",
    asideBg: "#0d110e",
    border: "#303a32",
    borderStrong: "#3d4a40",
    text: "#e7eee8",
    textMuted: "#8c998f",
  },
} as const;

export function getPreferredTheme(): ThemeMode {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyTheme(mode: ThemeMode): void {
  document.documentElement.classList.toggle("dark", mode === "dark");
  localStorage.setItem(STORAGE_KEY, mode);
}

export function isDarkTheme(): boolean {
  return document.documentElement.classList.contains("dark");
}

export function getSurfaceTokens(mode: ThemeMode = isDarkTheme() ? "dark" : "light") {
  return surfaceTokens[mode];
}
