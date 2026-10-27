// The app shell: sidebar navigation, the Ask | Find command bar, and the
// screen for the current route.
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
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
import { FocusedStatementGraph, GraphPicker, GraphScope } from './graph-scope';
import { GraphView } from './graph';
import { HomeScreen } from './home';
import { IngestSurface } from './ingest';
import { KnowledgeGapsScreen } from './knowledge-gaps';
import { KnowledgeHealthScreen } from './knowledge-health';
import { MediaLibrary } from './media';
import { NamesWorkspace } from './names-workspace';
import { SettingsScreen } from './settings';
import { DataCtx, ErrorBoundary, GoIngestCtx, I, LoadError, Loading, MeCtx, type IconName } from './lib';
import { Link, RouterCtx, routeToHash, useHashRouter, useRouter, type Route, type View } from './router';
import { getJSON, getServerInfo, type KnowledgeGap, type Me } from './api';
import { ensureSubstrate, loadSubstrate, substrate, substrateLoaded } from './data';
import { usePrefs } from './prefs';
import { ProposalBanner, ProposeToggle, useProposeMode } from './propose';
import { dataOf, useAsync, useRefreshWhileVisible } from './use-async';
import { useSetup } from './setup';

/* ---------------- Sidebar ---------------- */
interface NavItem { label: string; icon: IconName; to: Route; views: View[]; badge?: number; badgeTone?: 'warn' }

function navGroups(activeDrafts: number, openGaps: number, documentUpdates: number): { title: string | null; items: NavItem[] }[] {
  return [
    { title: null, items: [{ label: 'Home', icon: 'home', to: { view: 'home' }, views: ['home'] }] },
    { title: 'Explore', items: [
      { label: 'Browse', icon: 'table', to: { view: 'browse' }, views: ['browse', 'statement', 'entity'] },
      { label: 'Statement graph', icon: 'graph', to: { view: 'graph', focus: null, all: false }, views: ['graph'] },
      { label: 'Entity map', icon: 'hub', to: { view: 'entities', focus: null, all: false }, views: ['entities'] },
      { label: 'Documents', icon: 'doc', to: { view: 'documentation' }, views: ['documentation'], badge: documentUpdates },
    ] },
    { title: 'Add knowledge', items: [
      { label: 'Ingest text', icon: 'ingest', to: { view: 'ingest' }, views: ['ingest'] },
    ] },
    { title: 'Curate', items: [
      { label: 'Drafts', icon: 'prov', to: { view: 'drafts' }, views: ['drafts', 'draft'], badge: activeDrafts },
      { label: 'Knowledge health', icon: 'check', to: { view: 'health', list: null }, views: ['health'] },
      { label: 'Media', icon: 'doc', to: { view: 'media', show: 'all' }, views: ['media'] },
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
  const groups = navGroups(ready?.drafts ?? 0, ready?.gaps ?? 0, ready?.documentUpdates ?? 0);
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
// Rechecked because an open tab outlives the server process it first asked;
// the last answer stays up while a recheck is in flight or fails.
function ServerBanners() {
  const { state, reload } = useAsync(getServerInfo);
  useRefreshWhileVisible(reload, 60_000);
  const info = dataOf(state);
  if (info?.state !== 'ready') return null;
  return <>
    {info.quarantine && <div className="restore-banner notice warn" role="status">
      <I.warn width="16" height="16" />
      <span>
        <strong>Quarantine.</strong> This server was started with <code>--quarantine</code>: background AI work, draft review and publishing to GitHub are off.
        Restart it without the flag once this copy is safe to act on.
      </span>
    </div>}
    <PartialRestoreBanner missing={info.partial_restore} />
  </>;
}

function PartialRestoreBanner({ missing }: { missing: string[] }) {
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

/* ---------------- Blocked background work ---------------- */
// Admins only. One line per switched-on worker that lacks provider
// credentials; the workers themselves wait quietly instead of failing.
function BlockedWorkBanner() {
  const state = useSetup().state;
  const blocked = state.status === 'ready' ? state.data.blocked : [];
  if (!blocked.length) return null;
  return (
    <div className="restore-banner notice warn" role="status">
      <I.warn width="16" height="16" />
      <span>
        <strong>Background AI work is waiting.</strong>{' '}
        {blocked.map(b => <span key={b.worker}>{b.worker}: {b.reason} </span>)}
        <Link to={{ view: 'settings', section: 'models' }}>Check the models</Link>
      </span>
    </div>
  );
}

/* ---------------- Screen for a route ---------------- */
type ScreenProps = { route: Route; ingestNonce: number; refresh: () => Promise<void> };

// Home and a graph's picker or neighbourhood read only their own
// endpoints; any other screen may read the dump.
function Screen(props: ScreenProps) {
  const { route } = props;
  const screen = <RouteScreen {...props} />;
  const ownData = route.view === 'home'
    || (route.view === 'graph' && !route.all)
    || (route.view === 'entities' && !route.all && !route.focus);
  return ownData ? screen : <NeedsSubstrate>{screen}</NeedsSubstrate>;
}

function NeedsSubstrate({ children }: { children: ReactNode }) {
  const { state, reload } = useAsync(ensureSubstrate);
  if (substrateLoaded()) return <>{children}</>;
  if (state.status === 'error') return <main className="page"><LoadError error={state.error} what="the knowledge base" onRetry={reload} /></main>;
  return <main className="page"><Loading what="the knowledge base" /></main>;
}

function RouteScreen({ route, ingestNonce, refresh }: ScreenProps) {
  switch (route.view) {
    case 'home': return <HomeScreen />;
    case 'ask': return <AskSurface key={route.query} query={route.query} />;
    case 'find': return <FindResults query={route.query} mode={route.mode} />;
    case 'browse': return <BrowseScreen />;
    case 'graph':
      if (route.all) return <GraphView focusId={route.focus} scope={<GraphScope view="graph" label={null} />} />;
      return route.focus ? <FocusedStatementGraph focus={route.focus} /> : <GraphPicker view="graph" />;
    case 'entities':
      if (!route.all && !route.focus) return <GraphPicker view="entities" />;
      return <EntitiesGraph focusId={route.focus} scope={<GraphScope view="entities" label={route.all ? null : `Around ${substrate.index.entities[route.focus ?? '']?.name ?? route.focus}`} />} />;
    case 'statement': return <StatementDetail id={route.id} />;
    case 'entity': return <EntityDetail id={route.id} />;
    case 'documentation': return <DocumentationWorkspace />;
    case 'ingest': return <IngestSurface key={ingestNonce} />;
    case 'drafts': return <DraftsList />;
    case 'draft': return <DraftReview id={route.id} />;
    case 'health': return <KnowledgeHealthScreen list={route.list} />;
    case 'media': return <MediaLibrary show={route.show} />;
    case 'gaps': return <KnowledgeGapsScreen />;
    case 'names': return <NamesWorkspace onDataChanged={refresh} />;
    case 'glossary': return <GlossaryScreen />;
    case 'activity': return <ActivityScreen page={route.page} selected={route.selected} ops={route.ops} kinds={route.kinds} q={route.q} />;
    case 'settings': return <SettingsScreen section={route.section} />;
  }
}

// Screens that need the full width (canvases) or manage their own layout;
// a graph's concept picker is an ordinary page.
const FULL_BLEED: View[] = ['graph', 'entities'];
const fullBleed = (route: Route) => FULL_BLEED.includes(route.view)
  && !((route.view === 'graph' || route.view === 'entities') && !route.all && !route.focus);

export function App({ me }: { me: Me }) {
  const router = useHashRouter();
  const { route } = router;
  const [version, setVersion] = useState(0);
  const refresh = useCallback(async () => { await loadSubstrate(); setVersion(v => v + 1); }, []);
  const dataCtx = useMemo(() => ({ version, refresh }), [version, refresh]);
  const [ingestNonce, setIngestNonce] = useState(0);
  const goIngest = useCallback(() => { setIngestNonce(n => n + 1); router.go({ view: 'ingest' }); }, [router]);
  const [navOpen, setNavOpen] = useState(false);
  const [proposing, setProposing] = useProposeMode(me);

  return (
    <RouterCtx.Provider value={router}>
      <MeCtx.Provider value={me}>
        <DataCtx.Provider value={dataCtx}>
          <GoIngestCtx.Provider value={goIngest}>
            <div className={`shell${fullBleed(route) ? ' full-bleed' : ''}`}>
              <Sidebar me={me} open={navOpen} onClose={() => setNavOpen(false)} />
              {navOpen && <div className="side-scrim" onClick={() => setNavOpen(false)} />}
              <div className="main-col">
                <ServerBanners />
                {me.role === 'admin' && <BlockedWorkBanner />}
                {proposing && <ProposalBanner routeKey={routeToHash(route)} onTurnOff={() => setProposing(false)} />}
                <header className="topbar">
                  <button className="icon-btn menu-btn" onClick={() => setNavOpen(true)} aria-label="Open navigation"><I.menu /></button>
                  {route.view !== 'home' ? <CommandBar /> : <div className="topbar-spacer" />}
                  <ProposeToggle me={me} on={proposing} onChange={setProposing} />
                  <button className="ingest-btn" onClick={goIngest}><I.ingest width="15" height="15" />Ingest</button>
                </header>
                <ErrorBoundary key={`${routeToHash(route)}:${proposing}`}>
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
