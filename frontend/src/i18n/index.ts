import { useSyncExternalStore } from "react";

import { en, type Messages } from "./en";
import { pl } from "./pl";

export type Language = "en" | "pl";
export type { Messages };

export const LANGUAGES: readonly { code: Language; name: string }[] = [
  // Each name in its own language, so it can be read by those looking for it.
  { code: "en", name: "English" },
  { code: "pl", name: "Polski" },
];

const CATALOGS: Record<Language, Messages> = { en, pl };
// Dates and numbers follow the language of the sentences around them. Mixing
// them gives a Polish visitor "wtorek" in the middle of an English sentence.
const LOCALES: Record<Language, string> = { en: "en-GB", pl: "pl-PL" };
const STORAGE_KEY = "tutor-calendar-language";

function remembered(): Language | null {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    return stored === "en" || stored === "pl" ? stored : null;
  } catch {
    // Storage can be blocked. The choice then lasts for this visit only.
    return null;
  }
}

function preferred(): Language {
  const wanted = navigator.languages?.length ? navigator.languages : [navigator.language];
  for (const tag of wanted) {
    const code = tag.toLowerCase().split("-")[0];
    if (code === "pl" || code === "en") return code;
  }
  return "en";
}

let language: Language = remembered() ?? preferred();
const listeners = new Set<() => void>();
document.documentElement.lang = language;

export function getLanguage(): Language {
  return language;
}

export function setLanguage(next: Language): void {
  if (next === language) return;
  language = next;
  // Screen readers pick their pronunciation from this attribute.
  document.documentElement.lang = next;
  try {
    window.localStorage.setItem(STORAGE_KEY, next);
  } catch {
    // See `remembered`.
  }
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The language in use. Components that call this re-render when it changes. */
export function useLanguage(): Language {
  return useSyncExternalStore(subscribe, getLanguage);
}

/** The interface's sentences in the language in use. */
export function useT(): Messages {
  return CATALOGS[useLanguage()];
}

/**
 * The locale for formatting dates and numbers. Read when formatting, by helpers
 * that are called from components already subscribed through `useT`.
 */
export function currentLocale(): string {
  return LOCALES[language];
}
