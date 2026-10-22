// The app shell: sidebar navigation, the Ask | Find command bar, and the
// screen for the current route.
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ActivityScreen } from './activity';
import { AskSurface } from './ask';
import { BrowseScreen } from './browse';
import { DocumentationWorkspace } from './documentation-workspace';
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
import { NamesWorkspace } from './names-workspace';
import { ResearchSurface } from './research';
import { SettingsScreen } from './settings';
import { DataCtx, ErrorBoundary, GoIngestCtx, I, MeCtx, type IconName } from './lib';
import { Link, RouterCtx, routeToHash, useHashRouter, useRouter, type Route, type View } from './router';
import { getJSON, getMe, type KnowledgeGap, type Me } from './api';
import { loadSubstrate } from './data';
import { usePrefs } from './prefs';
import { useAsync } from './use-async';

/* ---------------- Sidebar ---------------- */
interface NavItem { label: string; icon: IconName; to: Route; views: View[]; badge?: number; badgeTone?: 'warn' }

function useNavGroups(activeDrafts: number, openGaps: number): { title: string | null; items: NavItem[] }[] {
  return [
    { title: null, items: [{ label: 'Home', icon: 'home', to: { view: 'home' }, views: ['home'] }] },
    { title: 'Explore', items: [
      { label: 'Browse', icon: 'table', to: { view: 'browse' }, views: ['browse', 'statement', 'entity'] },
      { label: 'Statement graph', icon: 'graph', to: { view: 'graph', focus: null }, views: ['graph'] },
      { label: 'Entity map', icon: 'hub', to: { view: 'entities', focus: null }, views: ['entities'] },
      { label: 'Documents', icon: 'doc', to: { view: 'documentation' }, views: ['documentation'] },
    ] },
    { title: 'Add knowledge', items: [
      { label: 'Ingest text', icon: 'ingest', to: { view: 'ingest' }, views: ['ingest'] },
      { label: 'Research', icon: 'research', to: { view: 'research', topic: '' }, views: ['research'] },
    ] },
    { title: 'Curate', items: [
      { label: 'Drafts', icon: 'prov', to: { view: 'drafts' }, views: ['drafts', 'draft'], badge: activeDrafts },
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
]).then(([d, g]) => ({
  drafts: d.drafts.filter(x => x.status === 'open' || x.status === 'submitted').length,
  gaps: g.gaps.length,
}));

function Sidebar({ me, open, onClose }: { me: Me | null; open: boolean; onClose: () => void }) {
  const { route } = useRouter();
  const { prefs, setPref } = usePrefs();
  // Recount on every navigation: cheap, and it keeps the badges honest
  // after a screen submits a draft or resolves a gap.
  const { state: counts, reload } = useAsync(loadCounts);
  useEffect(() => {
    window.addEventListener('hashchange', reload);
    return () => window.removeEventListener('hashchange', reload);
  }, [reload]);
  const groups = useNavGroups(counts.status === 'ready' ? counts.data.drafts : 0, counts.status === 'ready' ? counts.data.gaps : 0);
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
    case 'research': return <ResearchSurface key={route.topic} topic={route.topic} />;
    case 'drafts': return <DraftsList />;
    case 'draft': return <DraftReview id={route.id} />;
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
