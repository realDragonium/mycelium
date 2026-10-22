// The Ask | Find command bar: the hero on Home, compact in the top bar
// everywhere else. ⌘K focuses it.
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { FindLanes } from './find';
import { I } from './lib';
import { routeToHash, useRouter } from './router';
import type { FindMode } from './api';

export function CommandBar({ hero = false }: { hero?: boolean }) {
  const { route, go } = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const routeIntent = route.view === 'find' ? 'find' : 'ask';
  const routeQuery = route.view === 'find' || route.view === 'ask' ? route.query : '';
  const routeMode: FindMode = route.view === 'find' ? route.mode : 'semantic';
  const [intent, setIntent] = useState<'ask' | 'find'>(routeIntent);
  const [value, setValue] = useState(routeQuery);
  const [findMode, setFindMode] = useState<FindMode>(routeMode);
  // Follow the route when it changes underneath the bar (a link, back button).
  const [synced, setSynced] = useState(routeToHash(route));
  if (synced !== routeToHash(route)) {
    setSynced(routeToHash(route));
    setIntent(routeIntent);
    if (route.view === 'find' || route.view === 'ask') setValue(routeQuery);
    if (route.view === 'find') setFindMode(routeMode);
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); inputRef.current?.focus(); inputRef.current?.select(); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!value.trim()) return;
    go(intent === 'ask' ? { view: 'ask', query: value } : { view: 'find', query: value, mode: findMode });
  };

  return (
    <div className={`cmd-wrap${hero ? ' hero' : ' compact'}`}>
      <form className="cmd" data-intent={intent} onSubmit={submit} role="search">
        <div className="cmd-toggle" role="group" aria-label="Read mode">
          <button type="button" className={`cmd-mode${intent === 'ask' ? ' on' : ''}`} data-tier="ask" aria-pressed={intent === 'ask'} onClick={() => setIntent('ask')}>
            <span className="m-name">Ask</span>{hero && <span className="m-sub">agentic</span>}
          </button>
          <button type="button" className={`cmd-mode${intent === 'find' ? ' on' : ''}`} data-tier="find" aria-pressed={intent === 'find'} onClick={() => setIntent('find')}>
            <span className="m-name">Find</span>{hero && <span className="m-sub">deterministic</span>}
          </button>
        </div>
        <label className="cmd-field">
          <span className="lead">{intent === 'ask' ? <I.ask width="18" height="18" /> : <I.find width="16" height="16" />}</span>
          <input ref={inputRef} value={value} onChange={e => setValue(e.target.value)} spellCheck={false} autoFocus={hero}
            aria-label={intent === 'ask' ? 'Question' : 'Find query'}
            placeholder={intent === 'ask' ? 'Ask the knowledge base a question…' : 'Find statements by meaning, text, or breadth…'} />
          {!hero && <span className="kbd" aria-hidden>⌘K</span>}
        </label>
        <button type="submit" className="cmd-go">{intent === 'ask' ? 'Ask' : 'Find'}{hero && <span className="kbd">↵</span>}</button>
      </form>
      {hero && intent === 'find' && <FindLanes mode={findMode} onMode={setFindMode} />}
    </div>
  );
}

