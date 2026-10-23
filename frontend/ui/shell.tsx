// The app shell: sidebar navigation, the Ask | Find command bar, and the
// screen for the current route.
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ActivityScreen } from './activity';
import { AskSurface } from './ask';
import { BrowseScreen } from './browse';
import { DocumentationWorkspace, loadDocumentUpdates, UPDATES_SEEN_EVENT } from './documentation-workspace';
import { DraftReview, DraftsList } from './draft-review';
import { EntitiesGraph } from './entities-graph';
import { EntityDetail, StatementDetail } from './inspect';
import { FindResults } from './find';
import { CommandBar } from './command-bar';
import { GlossaryScreen } from './glossary';
import { GraphView } from './graph';
import { HomeScreen } from './home';
import { IngestSurface } from './ingest';
import { KnowledgeGapsScreen } from './knowledge-gaps';
import { KnowledgeHealthScreen } from './knowledge-health';
import { NamesWorkspace } from './names-workspace';
import { SettingsScreen } from './settings';
import { usd, type Budget } from './ai-usage';
import { DataCtx, ErrorBoundary, GoIngestCtx, I, MeCtx, type IconName } from './lib';
import { Link, RouterCtx, routeToHash, useHashRouter, useRouter, type Route, type View } from './router';
import { getJSON, getMe, getServerInfo, type KnowledgeGap, type Me } from './api';
import { loadSubstrate } from './data';
import { usePrefs } from './prefs';
import { useAsync } from './use-async';

/* ---------------- Sidebar ---------------- */
interface NavItem { label: string; icon: IconName; to: Route; views: View[]; badge?: number; badgeTone?: 'warn' }

function useNavGroups(activeDrafts: number, openGaps: number, documentUpdates: number): { title: string | null; items: NavItem[] }[] {
  return [
    { title: null, items: [{ label: 'Home', icon: 'home', to: { view: 'home' }, views: ['home'] }] },
    { title: 'Explore', items: [
      { label: 'Browse', icon: 'table', to: { view: 'browse' }, views: ['browse', 'statement', 'entity'] },
      { label: 'Statement graph', icon: 'graph', to: { view: 'graph', focus: null }, views: ['graph'] },
      { label: 'Entity map', icon: 'hub', to: { view: 'entities', focus: null }, views: ['entities'] },
      { label: 'Documents', icon: 'doc', to: { view: 'documentation' }, views: ['documentation'], badge: documentUpdates },
    ] },
    { title: 'Add knowledge', items: [
      { label: 'Ingest text', icon: 'ingest', to: { view: 'ingest' }, views: ['ingest'] },
    ] },
    { title: 'Curate', items: [
      { label: 'Drafts', icon: 'prov', to: { view: 'drafts' }, views: ['drafts', 'draft'], badge: activeDrafts },
      { label: 'Knowledge health', icon: 'check', to: { view: 'health', list: null }, views: ['health'] },
      { label: 'Knowledge gaps', icon: 'gap', to: { view: 'gaps' }, views: ['gaps'], badge: openGaps, badgeTone: 'warn' },
      { label: 'Names & aliases', icon: 'tag', to: { view: 'names' }, views: ['names'] },
      { label: 'Glossary', icon: 'book', to: { view: 'glossary' }, views: ['glossary'] },
      { label: 'Activity', icon: 'clock', to: { view: 'activity', page: 1, selected: null, ops: '', kinds: '', q: '' }, views: ['activity'] },
    ] },
  ];
}

const loadCounts = () => Promise.all([
  getJSON<{ drafts: { status: string }[] }>('/api/drafts?status=all'),
  getJSON<{ gaps: KnowledgeGap[] }>('/api/knowledge-gaps?status=open'),
  loadDocumentUpdates(),
]).then(([d, g, documentUpdates]) => ({
  drafts: d.drafts.filter(x => x.status === 'open' || x.status === 'submitted').length,
  gaps: g.gaps.length,
  documentUpdates,
}));

function Sidebar({ me, open, onClose }: { me: Me | null; open: boolean; onClose: () => void }) {
  const { route } = useRouter();
  const { prefs, setPref } = usePrefs();
  // Recount on every navigation: cheap, and it keeps the badges honest
  // after a screen submits a draft or resolves a gap.
  const { state: counts, reload } = useAsync(loadCounts);
  useEffect(() => {
    window.addEventListener('hashchange', reload);
    window.addEventListener(UPDATES_SEEN_EVENT, reload);
    return () => { window.removeEventListener('hashchange', reload); window.removeEventListener(UPDATES_SEEN_EVENT, reload); };
  }, [reload]);
  const ready = counts.status === 'ready' ? counts.data : null;
  const groups = useNavGroups(ready?.drafts ?? 0, ready?.gaps ?? 0, ready?.documentUpdates ?? 0);
  const item = (it: NavItem) => (
    <li key={it.label}>
      <Link to={it.to} className={`side-link${it.views.includes(route.view) ? ' on' : ''}`} onNavigate={onClose}>
        {I[it.icon]({ className: 'side-icon', width: 16, height: 16 })}
        <span>{it.label}</span>
        {!!it.badge && <span className={`side-badge${it.badgeTone ? ` ${it.badgeTone}` : ''}`} aria-label={`${it.badge} need attention`}>{it.badge}</span>}
      </Link>
    </li>
  );
  return (
    <nav className={`sidebar${open ? ' open' : ''}`} aria-label="Main">
      <Link to={{ view: 'home' }} className="brand" onNavigate={onClose}>
        <I.brand className="brand-mark" /><span className="brand-name">Mycelium</span>
      </Link>
      <div className="side-groups">
        {groups.map(g => (
          <div key={g.title || 'top'} className="side-group">
            {g.title && <div className="side-title">{g.title}</div>}
            <ul>{g.items.map(item)}</ul>
          </div>
        ))}
      </div>
      <div className="side-foot">
        <ul>
          {item({ label: 'Settings', icon: 'gear', to: { view: 'settings', section: 'account' }, views: ['settings'] })}
          <li><a className="side-link" href="/connect"><I.plug className="side-icon" /><span>Connect a client</span></a></li>
        </ul>
        <div className="side-user">
          {me && <Link to={{ view: 'settings', section: 'account' }} className="side-me" onNavigate={onClose} title="Account and tokens">
            <span className="me-name">{me.name}</span><span className={`role-badge ${me.role}`}>{me.role}</span>
          </Link>}
          <button className="icon-btn" onClick={() => setPref('theme', prefs.theme === 'dark' ? 'light' : 'dark')}
            title={`Switch to ${prefs.theme === 'dark' ? 'light' : 'dark'} theme`} aria-label="Toggle theme">
            {prefs.theme === 'dark' ? <I.sun /> : <I.moon />}
          </button>
        </div>
      </div>
    </nav>
  );
}

/* ---------------- Partial restore ---------------- */
const LOST_WITH: Record<string, string> = {
  'mycelium-auth.db': 'users and tokens',
  'mycelium-drafts.db': 'drafts and generated documents',
  'mycelium-prompts.db': 'prompt texts and settings',
  'mycelium-history.db': 'audit history',
};

// Not dismissible: the condition lasts until the files are restored and the
// server restarts, and an operator should not have to read logs to find it.
function PartialRestoreBanner() {
  const info = useAsync(getServerInfo).state;
  const missing = info.status === 'ready' ? info.data.partial_restore : [];
  if (!missing.length) return null;
  const lost = missing.map(name => LOST_WITH[name] ?? name).join(', ');
  return (
    <div className="restore-banner notice error" role="alert">
      <I.warn width="16" height="16" />
      <span>
        <strong>Partial restore.</strong> This server started without {missing.map((name, i) => <span key={name}>{i ? ', ' : ''}<code>{name}</code></span>)} beside
        a knowledge base that should have {missing.length === 1 ? 'it' : 'them'}, and recreated {missing.length === 1 ? 'it' : 'them'} empty.
        The {lost} kept there are missing from this instance. Restore every file <code>mycelium databases</code> lists, then restart the server.
      </span>
    </div>
  );
}

/* ---------------- AI budget ---------------- */
// Admins only: the endpoint answers null for everyone else. Checked once per
// page load; spend moves slowly enough that a stale banner costs nothing.
function BudgetBanner() {
  const state = useAsync(useCallback(() => getJSON<Budget | null>('/api/ai-usage/budget'), [])).state;
  const budget = state.status === 'ready' ? state.data : null;
  if (!budget || !budget.warning) return null;
  return (
    <div className={`restore-banner notice ${budget.paused ? 'error' : 'warn'}`} role="status">
      <I.warn width="16" height="16" />
      <span>
        <strong>AI budget.</strong> Estimated spend this month is {usd(budget.spent_usd)}, {budget.percent}% of the {usd(budget.limit_usd)} budget.
        {budget.paused ? ' Background actions are paused.' : ''} <Link to={{ view: 'settings', section: 'usage' }}>See AI usage</Link>
      </span>
    </div>
  );
}

/* ---------------- Screen for a route ---------------- */
function Screen({ route, ingestNonce, refresh }: { route: Route; ingestNonce: number; refresh: () => Promise<void> }) {
  switch (route.view) {
    case 'home': return <HomeScreen />;
    case 'ask': return <AskSurface key={route.query} query={route.query} />;
    case 'find': return <FindResults query={route.query} mode={route.mode} />;
    case 'browse': return <BrowseScreen />;
    case 'graph': return <GraphView focusId={route.focus} />;
    case 'entities': return <EntitiesGraph focusId={route.focus} />;
    case 'statement': return <StatementDetail id={route.id} />;
    case 'entity': return <EntityDetail id={route.id} />;
    case 'documentation': return <DocumentationWorkspace />;
    case 'ingest': return <IngestSurface key={ingestNonce} />;
    case 'drafts': return <DraftsList />;
    case 'draft': return <DraftReview id={route.id} />;
    case 'health': return <KnowledgeHealthScreen list={route.list} />;
    case 'gaps': return <KnowledgeGapsScreen />;
    case 'names': return <NamesWorkspace onDataChanged={refresh} />;
    case 'glossary': return <GlossaryScreen />;
    case 'activity': return <ActivityScreen page={route.page} selected={route.selected} ops={route.ops} kinds={route.kinds} q={route.q} />;
    case 'settings': return <SettingsScreen section={route.section} />;
  }
}

// Screens that need the full width (canvases) or manage their own layout.
const FULL_BLEED: View[] = ['graph', 'entities'];

export function App() {
  const router = useHashRouter();
  const { route } = router;
  const [version, setVersion] = useState(0);
  const refresh = useCallback(async () => { await loadSubstrate(); setVersion(v => v + 1); }, []);
  const dataCtx = useMemo(() => ({ version, refresh }), [version, refresh]);
  const [ingestNonce, setIngestNonce] = useState(0);
  const goIngest = useCallback(() => { setIngestNonce(n => n + 1); router.go({ view: 'ingest' }); }, [router]);
  const me = useAsync(getMe).state;
  const [navOpen, setNavOpen] = useState(false);

  return (
    <RouterCtx.Provider value={router}>
      <MeCtx.Provider value={me.status === 'ready' ? me.data : null}>
        <DataCtx.Provider value={dataCtx}>
          <GoIngestCtx.Provider value={goIngest}>
            <div className={`shell${FULL_BLEED.includes(route.view) ? ' full-bleed' : ''}`}>
              <Sidebar me={me.status === 'ready' ? me.data : null} open={navOpen} onClose={() => setNavOpen(false)} />
              {navOpen && <div className="side-scrim" onClick={() => setNavOpen(false)} />}
              <div className="main-col">
                <PartialRestoreBanner />
                {me.status === 'ready' && me.data.role === 'admin' && <BudgetBanner />}
                <header className="topbar">
                  <button className="icon-btn menu-btn" onClick={() => setNavOpen(true)} aria-label="Open navigation"><I.menu /></button>
                  {route.view !== 'home' ? <CommandBar /> : <div className="topbar-spacer" />}
                  <button className="ingest-btn" onClick={goIngest}><I.ingest width="15" height="15" />Ingest</button>
                </header>
                <ErrorBoundary key={routeToHash(route)}>
                  <Screen route={route} ingestNonce={ingestNonce} refresh={refresh} />
                </ErrorBoundary>
              </div>
            </div>
          </GoIngestCtx.Provider>
        </DataCtx.Provider>
      </MeCtx.Provider>
    </RouterCtx.Provider>
  );
}
