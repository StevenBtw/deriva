import { useCallback, useEffect, useState } from "react";

export type ThemeChoice = "light" | "dark" | "system";
export type EffectiveTheme = "light" | "dark";

const KEY = "deriva.theme";
const ORDER: ThemeChoice[] = ["system", "light", "dark"];

export function getTheme(): ThemeChoice {
  try {
    const stored = localStorage.getItem(KEY);
    return stored === "light" || stored === "dark" ? stored : "system";
  } catch {
    return "system";
  }
}

export function applyTheme(choice: ThemeChoice): void {
  if (choice === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = choice;
}

export function setTheme(choice: ThemeChoice): void {
  try {
    if (choice === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, choice);
  } catch {
    // storage blocked: the choice still applies for this page
  }
  applyTheme(choice);
}

export function effectiveTheme(choice: ThemeChoice = getTheme()): EffectiveTheme {
  if (choice !== "system") return choice;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function nextTheme(choice: ThemeChoice): ThemeChoice {
  return ORDER[(ORDER.indexOf(choice) + 1) % ORDER.length];
}

/** Current choice, a setter, and the theme actually shown (follows the system for "system"). */
export function useTheme(): [ThemeChoice, (choice: ThemeChoice) => void, EffectiveTheme] {
  const [choice, setChoice] = useState<ThemeChoice>(getTheme);
  const [shown, setShown] = useState<EffectiveTheme>(() => effectiveTheme(getTheme()));

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => setShown(effectiveTheme(choice));
    media.addEventListener?.("change", update);
    return () => media.removeEventListener?.("change", update);
  }, [choice]);

  const change = useCallback((next: ThemeChoice) => {
    setTheme(next);
    setChoice(next);
    setShown(effectiveTheme(next));
  }, []);

  return [choice, change, shown];
}
