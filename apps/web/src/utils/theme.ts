const STORAGE_KEY = "zhixiao-theme";

export type ThemeMode = "light" | "dark";

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
