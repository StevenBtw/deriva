import { useCallback, useEffect, useState } from "react";

/** Studio opens in dark; light is an explicit choice, remembered per browser. */
export type ThemeChoice = "light" | "dark";
export type EffectiveTheme = ThemeChoice;

const KEY = "deriva.theme";
const ORDER: ThemeChoice[] = ["dark", "light"];
// Every useTheme hears a change made anywhere on the page (the top bar's toggle, the graphs that follow it)
const CHANGED = "deriva:theme";

export function getTheme(): ThemeChoice {
  try {
    return localStorage.getItem(KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

export function applyTheme(choice: ThemeChoice): void {
  document.documentElement.dataset.theme = choice;
}

export function setTheme(choice: ThemeChoice): void {
  try {
    localStorage.setItem(KEY, choice);
  } catch {
    // storage blocked: the choice still applies for this page
  }
  applyTheme(choice);
  window.dispatchEvent(new CustomEvent<ThemeChoice>(CHANGED, { detail: choice }));
}

export function effectiveTheme(choice: ThemeChoice = getTheme()): EffectiveTheme {
  return choice;
}

export function nextTheme(choice: ThemeChoice): ThemeChoice {
  return ORDER[(ORDER.indexOf(choice) + 1) % ORDER.length];
}

/** Current choice, a setter, and the theme actually shown (the same, now that there is no system mode). */
export function useTheme(): [ThemeChoice, (choice: ThemeChoice) => void, EffectiveTheme] {
  const [choice, setChoice] = useState<ThemeChoice>(getTheme);

  useEffect(() => {
    const changed = (event: Event) => setChoice((event as CustomEvent<ThemeChoice>).detail);
    window.addEventListener(CHANGED, changed);
    return () => window.removeEventListener(CHANGED, changed);
  }, []);

  const change = useCallback((next: ThemeChoice) => setTheme(next), []);

  return [choice, change, choice];
}
