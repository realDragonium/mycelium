// Mycelium app — router + tweaks panel + screen mounting.

const { useState: useStateA, useEffect: useEffectA, useMemo: useMemoA } = React;

function useHashRoute() {
  const parse = () => {
    const h = window.location.hash.replace(/^#/, '');
    if (!h) return { view: 'landing' };
    const [path, qs] = h.split('?');
    const parts = path.split('/').filter(Boolean);
    const params = Object.fromEntries(new URLSearchParams(qs || ''));
    if (parts[0] === 'b' && parts[1]) return { view: 'statement', id: parts[1] };
    if (parts[0] === 'e' && parts[1]) return { view: 'entity', id: parts[1] };
    if (parts[0] === 'search') return { view: 'search', query: params.q || '' };
    if (parts[0] === 'graph') return { view: 'graph', focus: params.focus || null };
    if (parts[0] === 'entities') return { view: 'entities', focus: params.focus || null };
    if (parts[0] === 'browse') return { view: 'browse' };
    if (parts[0] === 'glossary') return { view: 'glossary' };
    if (parts[0] === 'settings') return { view: 'settings' };
    if (parts[0] === 'gaps') return { view: 'gaps' };
    if (parts[0] === 'pending') return { view: 'pending' };
    if (parts[0] === 'drafts') return {
      view: 'drafts',
      selected: parts[1] || null,
    };
    if (parts[0] === 'activity') return {
      view: 'activity',
      page: parseInt(params.page || '1', 10) || 1,
      selected: params.sel || null,
      ops: params.ops || '',
      kinds: params.kinds || '',
      q: params.q || '',
    };
    return { view: 'landing' };
  };

  const [route, setRoute] = useStateA(parse);
  useEffectA(() => {
    const onHash = () => setRoute(parse());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  const go = (next) => {
    let h = '#';
    if (next.view === 'statement') h = `#/b/${next.id}`;
    else if (next.view === 'entity') h = `#/e/${next.id}`;
    else if (next.view === 'search') h = `#/search?q=${encodeURIComponent(next.query || '')}`;
    else if (next.view === 'graph') h = next.focus ? `#/graph?focus=${next.focus}` : `#/graph`;
    else if (next.view === 'entities') h = next.focus ? `#/entities?focus=${next.focus}` : `#/entities`;
    else if (next.view === 'browse') h = `#/browse`;
    else if (next.view === 'glossary') h = `#/glossary`;
    else if (next.view === 'settings') h = `#/settings`;
    else if (next.view === 'gaps') h = `#/gaps`;
    else if (next.view === 'pending') h = `#/pending`;
    else if (next.view === 'drafts') h = next.selected ? `#/drafts/${next.selected}` : `#/drafts`;
    else if (next.view === 'activity') {
      const qs = new URLSearchParams();
      if (next.page && next.page !== 1) qs.set('page', String(next.page));
      if (next.selected) qs.set('sel', next.selected);
      if (next.ops) qs.set('ops', next.ops);
      if (next.kinds) qs.set('kinds', next.kinds);
      if (next.q) qs.set('q', next.q);
      const s = qs.toString();
      h = s ? `#/activity?${s}` : `#/activity`;
    }
    else h = '#';
    if (h === window.location.hash || (h === '#' && !window.location.hash)) {
      // force re-render anyway
      setRoute(next);
    }
    window.location.hash = h;
    // scroll to top on nav
    window.scrollTo({ top: 0, statement: 'instant' });
  };

  return { ...route, go };
}

function App() {
  const router = useHashRoute();

  // Data version — bumped after a successful UI mutation (`refresh()`
  // refetches /api/data and replaces window.MYCELIUM_DATA, then
  // increments this counter so dependent memos re-run). Reading
  // `window.MYCELIUM_DATA` straight remains the convention for child
  // components; the version is the trigger that makes their memos
  // notice the swap.
  const [dataVersion, setDataVersion] = React.useState(0);
  const refresh = React.useCallback(async () => {
    await window.MyceliumLoadData();
    setDataVersion(v => v + 1);
  }, []);
  const data = window.MYCELIUM_DATA;

  // Rebuild the in-memory adjacency index whenever data changes.
  useMemoA(() => { window.MYCELIUM_INDEX = buildIndex(data); }, [data, dataVersion]);

  const dataCtxValue = useMemoA(() => ({ version: dataVersion, refresh }), [dataVersion, refresh]);

  // Tweaks
  const defaults = window.MYC_TWEAKS_DEFAULTS;
  const [tweaks, setTweak] = useTweaks(defaults);

  // Apply theme + density to <html> for CSS vars
  useEffectA(() => {
    document.documentElement.dataset.theme = tweaks.theme || 'light';
    document.documentElement.dataset.density = tweaks.density || 'comfortable';
  }, [tweaks.theme, tweaks.density]);

  // System dark preference once at first load — only if user hasn't set
  useEffectA(() => {
    if (defaults.theme !== 'light') return;
    // honor whatever is already set; do nothing
  }, []);

  const tweaksValue = useMemoA(() => ({ tweaks, setTweak }), [tweaks, setTweak]);

  let screen;
  switch (router.view) {
    case 'statement': screen = <StatementDetail id={router.id} />; break;
    case 'entity': screen = <EntityDetail id={router.id} />; break;
    case 'search': screen = <SearchResults query={router.query} />; break;
    case 'graph': screen = <GraphView focusId={router.focus} />; break;
    case 'entities': screen = <EntitiesGraph focusId={router.focus} />; break;
    case 'browse': screen = <BrowseIndex />; break;
    case 'glossary': screen = <GlossaryScreen />; break;
    case 'settings': screen = <SettingsScreen />; break;
    case 'gaps': screen = <GapsScreen />; break;
    case 'pending': screen = <PendingMentionsScreen />; break;
    case 'drafts': screen = <DraftsScreen selected={router.selected} />; break;
    case 'activity': screen = <ActivityScreen page={router.page} selected={router.selected} ops={router.ops} kinds={router.kinds} q={router.q} />; break;
    case 'landing':
    default: screen = <Landing />;
  }

  return (
    <RouterCtx.Provider value={router}>
      <TweaksCtx.Provider value={tweaksValue}>
       <DataCtx.Provider value={dataCtxValue}>
        <div className="shell">
          <TopBar small={true} />
          {screen}
          <Footer />
        </div>

        <TweaksPanel title="Tweaks">
          <TweakSection label="Appearance" />
          <TweakRadio
            label="Theme"
            value={tweaks.theme}
            onChange={(v) => setTweak('theme', v)}
            options={[
              { value: 'light', label: 'Light' },
              { value: 'dark', label: 'Dark' },
            ]}
          />
          <TweakRadio
            label="Density"
            value={tweaks.density}
            onChange={(v) => setTweak('density', v)}
            options={[
              { value: 'compact', label: 'Compact' },
              { value: 'comfortable', label: 'Default' },
              { value: 'roomy', label: 'Roomy' },
            ]}
          />

          <TweakSection label="Future" />
          <TweakToggle
            label="Show edit affordances"
            value={!!tweaks.showEditAffordances}
            onChange={(v) => setTweak('showEditAffordances', v)}
          />

          <div style={{padding:'14px 16px 4px', fontFamily:'var(--mono)', fontSize:10.5, color:'var(--ink-4)', letterSpacing:'0.06em', borderTop:'1px solid var(--rule)'}}>
            Browser · v0.1
          </div>
        </TweaksPanel>
       </DataCtx.Provider>
      </TweaksCtx.Provider>
    </RouterCtx.Provider>
  );
}

// Defer rendering until the substrate dump has loaded. Show a quick
// failure message in #root if the fetch fails.
window.MyceliumLoadData().then(() => {
  ReactDOM.createRoot(document.getElementById('root')).render(<App />);
}).catch((err) => {
  const root = document.getElementById('root');
  root.textContent = '';
  const wrap = document.createElement('div');
  wrap.style.cssText = 'padding:32px;font-family:var(--mono,monospace);color:var(--ink-3,#71717a);font-size:13px;';
  const msg = document.createElement('div');
  msg.textContent = 'failed to load /api/data — is the server running?';
  const code = document.createElement('code');
  code.style.cssText = 'display:block;margin-top:14px;color:var(--ink,#fafafa);';
  code.textContent = (err && err.message) || String(err);
  wrap.append(msg, code);
  root.append(wrap);
  console.error(err);
});
