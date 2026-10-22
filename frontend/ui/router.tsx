// Hash routes for the one app. Each screen has one canonical hash; older
// hashes from the former /ui and /cockpit apps still resolve (see ALIASES in
// parseHash) and are rewritten to the canonical one, so bookmarks survive.
import { createContext, useContext, useEffect, useState, type CSSProperties, type MouseEvent, type ReactNode } from 'react';
import { isFindMode, type FindMode } from './api';

export const SETTINGS_SECTIONS = [
  'account', 'appearance', 'members', 'models', 'prompts', 'review', 'limits', 'research', 'documentation',
] as const;
export type SettingsSection = typeof SETTINGS_SECTIONS[number];
const isSettingsSection = (value: string): value is SettingsSection => (SETTINGS_SECTIONS as readonly string[]).includes(value);

export interface ActivityParams { page: number; selected: string | null; ops: string; kinds: string; q: string }

export type Route =
  | { view: 'home' }
  | { view: 'ask'; query: string }
  | { view: 'find'; query: string; mode: FindMode }
  | { view: 'browse' }
  | { view: 'graph'; focus: string | null }
  | { view: 'entities'; focus: string | null }
  | { view: 'statement'; id: string }
  | { view: 'entity'; id: string }
  | { view: 'documentation' }
  | { view: 'ingest' }
  | { view: 'research'; topic: string }
  | { view: 'drafts' }
  | { view: 'draft'; id: string }
  | { view: 'gaps' }
  | { view: 'names' }
  | { view: 'glossary' }
  | ({ view: 'activity' } & ActivityParams)
  | { view: 'settings'; section: SettingsSection };

export type View = Route['view'];

export function parseHash(hash: string): Route {
  const h = hash.replace(/^#/, '');
  const [path, qs] = h.split('?');
  const parts = path.split('/').filter(Boolean).map(decodeURIComponent);
  const p = new URLSearchParams(qs || '');
  const param = (key: string) => p.get(key) || '';
  const [head, arg] = parts;
  switch (head) {
    case undefined: return { view: 'home' };
    case 'ask': return { view: 'ask', query: param('q') };
    case 'find': {
      const mode = param('mode');
      return { view: 'find', query: param('q'), mode: isFindMode(mode) ? mode : 'semantic' };
    }
    // The former /ui search was a literal match over records.
    case 'search': return { view: 'find', query: param('q'), mode: 'grep' };
    case 'browse': return { view: 'browse' };
    case 'graph': return { view: 'graph', focus: p.get('focus') };
    case 'entities': return { view: 'entities', focus: p.get('focus') };
    case 's': case 'b': return arg ? { view: 'statement', id: arg } : { view: 'browse' };
    case 'e': return arg ? { view: 'entity', id: arg } : { view: 'browse' };
    case 'documentation': {
      // Documentation settings moved into Settings; GitHub's install flow
      // still returns to the old tab.
      const tab = p.get('tab');
      return tab === 'settings' || tab === 'profiles' ? { view: 'settings', section: 'documentation' } : { view: 'documentation' };
    }
    case 'ingest': return { view: 'ingest' };
    case 'research': return { view: 'research', topic: param('topic') };
    case 'drafts': case 'draft': return arg ? { view: 'draft', id: arg } : { view: 'drafts' };
    case 'gaps': case 'coverage': return { view: 'gaps' };
    case 'names': case 'mentions': case 'pending': return { view: 'names' };
    case 'glossary': return { view: 'glossary' };
    case 'activity': return {
      view: 'activity',
      page: Math.max(1, parseInt(param('page') || '1', 10) || 1),
      selected: p.get('sel'), ops: param('ops'), kinds: param('kinds'), q: param('q'),
    };
    case 'settings': return { view: 'settings', section: arg && isSettingsSection(arg) ? arg : 'account' };
    default: return { view: 'home' };
  }
}

function query(params: Record<string, string | number | null | undefined>): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== null && v !== undefined && v !== '') qs.set(k, String(v));
  const s = qs.toString();
  return s ? `?${s}` : '';
}

export function routeToHash(route: Route): string {
  const e = encodeURIComponent;
  switch (route.view) {
    case 'home': return '#/';
    case 'ask': return `#/ask${query({ q: route.query })}`;
    case 'find': return `#/find${query({ q: route.query, mode: route.mode })}`;
    case 'browse': return '#/browse';
    case 'graph': return `#/graph${query({ focus: route.focus })}`;
    case 'entities': return `#/entities${query({ focus: route.focus })}`;
    case 'statement': return `#/s/${e(route.id)}`;
    case 'entity': return `#/e/${e(route.id)}`;
    case 'documentation': return '#/documentation';
    case 'ingest': return '#/ingest';
    case 'research': return `#/research${query({ topic: route.topic })}`;
    case 'drafts': return '#/drafts';
    case 'draft': return `#/drafts/${e(route.id)}`;
    case 'gaps': return '#/gaps';
    case 'names': return '#/names';
    case 'glossary': return '#/glossary';
    case 'activity': return `#/activity${query({ page: route.page === 1 ? null : route.page, sel: route.selected, ops: route.ops, kinds: route.kinds, q: route.q })}`;
    case 'settings': return `#/settings/${route.section}`;
  }
}

// The canonical form of the current hash. Documentation keeps its own query
// (tab, document, run) and Settings keeps GitHub's `?github=` return state,
// so those pass their query through.
function canonicalHash(hash: string, route: Route): string {
  const base = routeToHash(route);
  const qs = hash.split('?')[1];
  if (!qs) return base;
  if (route.view === 'documentation') return `${base}?${qs}`;
  if (route.view === 'settings') {
    const github = new URLSearchParams(qs).get('github');
    return github ? `${base}?github=${encodeURIComponent(github)}` : base;
  }
  return base;
}

export interface Router { route: Route; go: (next: Route) => void }

// Parses the current hash and rewrites an alias to its canonical form in
// place, without adding a history entry.
function readLocation(): Route {
  const hash = window.location.hash || '#/';
  const route = parseHash(hash);
  const canonical = canonicalHash(hash, route);
  if (canonical !== hash) window.history.replaceState(null, '', canonical);
  return route;
}

export function useHashRouter(): Router {
  const [route, setRoute] = useState(readLocation);
  useEffect(() => {
    const onHash = () => setRoute(readLocation());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);
  const go = (next: Route) => {
    const hash = routeToHash(next);
    if (hash === window.location.hash) setRoute(next);
    else window.location.hash = hash;
    window.scrollTo({ top: 0, behavior: 'instant' });
  };
  return { route, go };
}

export const RouterCtx = createContext<Router | null>(null);
export function useRouter(): Router {
  const router = useContext(RouterCtx);
  if (!router) throw new Error('useRouter needs a RouterCtx provider');
  return router;
}

// An anchor to a route: a real link (new tab, copy address) that navigates
// in place on a plain click.
export function Link({ to, className, title, style, children, onNavigate }: {
  to: Route; className?: string; title?: string; style?: CSSProperties; children: ReactNode; onNavigate?: () => void;
}) {
  const { go } = useRouter();
  const click = (e: MouseEvent<HTMLAnchorElement>) => {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    onNavigate?.();
    go(to);
  };
  return <a href={routeToHash(to)} className={className} title={title} style={style} onClick={click}>{children}</a>;
}
