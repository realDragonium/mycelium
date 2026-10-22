// Appearance preferences: per browser, stored in localStorage, applied as
// data attributes on <html> that the stylesheets key off.
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';

export interface Prefs {
  theme: 'dark' | 'light';
  density: 'compact' | 'comfortable' | 'roomy';
  answerVoice: 'serif' | 'sans';
}

const DEFAULTS: Prefs = { theme: 'dark', density: 'comfortable', answerVoice: 'serif' };
const KEY = 'mycelium.prefs';
const CHOICES: { [K in keyof Prefs]: readonly Prefs[K][] } = {
  theme: ['dark', 'light'],
  density: ['compact', 'comfortable', 'roomy'],
  answerVoice: ['serif', 'sans'],
};

function pick<K extends keyof Prefs>(key: K, value: unknown): Prefs[K] {
  return (CHOICES[key] as readonly unknown[]).includes(value) ? value as Prefs[K] : DEFAULTS[key];
}

function readPrefs(): Prefs {
  let stored: Record<string, unknown> = {};
  try { stored = JSON.parse(localStorage.getItem(KEY) || '{}') as Record<string, unknown>; } catch { /* corrupt or blocked storage */ }
  return { theme: pick('theme', stored.theme), density: pick('density', stored.density), answerVoice: pick('answerVoice', stored.answerVoice) };
}

interface PrefsValue { prefs: Prefs; setPref: <K extends keyof Prefs>(key: K, value: Prefs[K]) => void }
const PrefsCtx = createContext<PrefsValue>({ prefs: DEFAULTS, setPref: () => {} });
export const usePrefs = () => useContext(PrefsCtx);
export { CHOICES as PREF_CHOICES };

export function PrefsProvider({ children }: { children: ReactNode }) {
  const [prefs, setPrefs] = useState(readPrefs);
  useEffect(() => {
    const root = document.documentElement.dataset;
    root.theme = prefs.theme;
    root.density = prefs.density;
    root.answerVoice = prefs.answerVoice;
    try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch { /* storage blocked: keep in memory */ }
  }, [prefs]);
  const setPref = <K extends keyof Prefs>(key: K, value: Prefs[K]) => setPrefs(p => ({ ...p, [key]: value }));
  return <PrefsCtx.Provider value={{ prefs, setPref }}>{children}</PrefsCtx.Provider>;
}
