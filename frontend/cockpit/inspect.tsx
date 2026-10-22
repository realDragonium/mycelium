// inspect.jsx — statement & entity detail. Provenance + traversal target.
const { useState: useStateI } = React;

function WhenCond({ when }) {
  const router = useRouter();
  if (!when) return null;
  const ids = when.all || when.any || [];
  const op = when.any ? 'any' : 'all';
  return (
    <span className="when-chip" title={`gated: ${op} of these must hold`}>
      ⟂ when {ids.map((id, i) => (
        <span key={id}>
          {i > 0 && <span style={{ opacity: 0.6 }}> {op === 'any' ? 'or' : '&'} </span>}
          <span style={{ cursor: 'pointer', textDecoration: 'underline dotted' }} onClick={(e) => { e.stopPropagation(); router.go({ view: 'statement', id }); }}>{id}</span>
        </span>
      ))}
    </span>
  );
}

function LinkLine({ link, dir, idx }) {
  const router = useRouter();
  const tid = dir === 'out' ? link.to : link.from;
  const t = idx.byId[tid];
  if (!t) return null;
  return (
    <div className="linkline" onClick={() => router.go({ view: 'statement', id: tid })}>
      <span className="ll-dir">{dir === 'out' ? '→' : '←'}</span>
      <LinkTag type={link.type} hasWhen={!!link.when} />
      <span className="ll-target">{t.title || t.text}</span>
      <span className="ll-tid">{link.when ? <WhenCond when={link.when} /> : tid}</span>
    </div>
  );
}

// Add a mention by growing the vocabulary, not by asserting a link: attach an
// alias to an existing entity, or create a new entity. Either way the server
// enqueues a recompute scan, so the deterministic matcher derives the mention on
// existing statements whose text contains the new name. The new link therefore
// shows up after a reload, not instantly — hence the explicit Reload affordance.
const AM_INPUT = {
  width: '100%', padding: '7px 9px', borderRadius: 6,
  border: '1px solid var(--line)', background: 'var(--bg-1, transparent)',
  color: 'var(--ink-1)', fontFamily: 'var(--mono)', fontSize: 'var(--fs-xs)',
};

function AddMention() {
  const idx = window.MYCELIUM_INDEX;
  const [open, setOpen] = useStateI(false);
  const [mode, setMode] = useStateI('existing'); // existing | new
  const [query, setQuery] = useStateI('');
  const [entityId, setEntityId] = useStateI(null);
  const [alias, setAlias] = useStateI('');
  const [name, setName] = useStateI('');
  const [desc, setDesc] = useStateI('');
  const [busy, setBusy] = useStateI(false);
  const [err, setErr] = useStateI(null);
  const [done, setDone] = useStateI(null);

  const entities = React.useMemo(
    () => Object.values(idx.byId).filter((r) => r._kind === 'entity'),
    [idx]
  );
  const q = query.trim().toLowerCase();
  const matches = !q ? [] : entities.filter((e) => {
    if ((e.name || '').toLowerCase().includes(q)) return true;
    return (idx.namesByEntity[e.id] || []).some((n) => (n.text || '').toLowerCase().includes(q));
  }).slice(0, 8);
  const selected = entityId ? idx.byId[entityId] : null;
  const canSubmit = mode === 'existing'
    ? !!(entityId && alias.trim())
    : !!name.trim();

  const reset = () => { setQuery(''); setEntityId(null); setAlias(''); setName(''); setDesc(''); setErr(null); };

  const submit = () => {
    if (!canSubmit) return;
    setBusy(true); setErr(null);
    const label = mode === 'existing' ? alias.trim() : name.trim();
    const call = mode === 'existing'
      ? window.Myc.upsertName(alias.trim(), entityId)
      : window.Myc.upsertEntity(name.trim(), desc.trim());
    call
      .then(() => { reset(); setOpen(false); setDone(label); })
      .catch((e) => setErr((e && e.message) || 'Could not add that.'))
      .finally(() => setBusy(false));
  };

  if (done) {
    return (
      <div className="draft-banner" style={{ marginTop: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
        <span className="dbi"><I.check width="15" height="15" /></span>
        <span>Added <b>“{done}”</b>. The matcher will link it to every statement that contains it on its next scan.</span>
        <span style={{ flex: 1 }} />
        <button className="btn" onClick={() => window.location.reload()}>Reload to see it</button>
        <button className="btn ghost" onClick={() => { setDone(null); setOpen(true); }}>Add another</button>
      </div>
    );
  }

  if (!open) {
    return (
      <button className="btn ghost" style={{ marginTop: 12 }} onClick={() => { reset(); setOpen(true); }}>+ add mention</button>
    );
  }

  return (
    <div style={{ marginTop: 12, border: '1px solid var(--line)', borderRadius: 8, padding: 12 }}>
      <div className="draft-filters" style={{ marginBottom: 10 }}>
        <span className="dfl">map to</span>
        <button className={`fchip${mode === 'existing' ? ' on' : ''}`} onClick={() => setMode('existing')}>existing entity</button>
        <button className={`fchip${mode === 'new' ? ' on' : ''}`} onClick={() => setMode('new')}>new entity</button>
        <span style={{ flex: 1 }} />
        <button className="btn ghost" onClick={() => { setOpen(false); reset(); }}>cancel</button>
      </div>

      {mode === 'existing' ? (
        !selected ? (
          <>
            <input style={AM_INPUT} autoFocus value={query} placeholder="search entities by name or alias…"
              spellCheck={false} onChange={(e) => setQuery(e.target.value)} />
            {q && (
              <div className="ops" style={{ marginTop: 8 }}>
                {matches.length === 0
                  ? <div className="rail-empty" style={{ padding: '8px 2px', fontFamily: 'var(--mono)', fontSize: 'var(--fs-2xs)', color: 'var(--ink-4)' }}>// no entity matches — switch to “new entity” to create one</div>
                  : matches.map((e) => (
                    <div key={e.id} className="linkline" onClick={() => { setEntityId(e.id); setQuery(''); }}>
                      <b>{e.name}</b>{e.description ? <span style={{ color: 'var(--ink-4)', marginLeft: 8 }}>{e.description}</span> : null}
                    </div>
                  ))}
              </div>
            )}
          </>
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span className="dfl">alias for</span>
            <EntityChip entity={selected} />
            <button className="btn ghost" onClick={() => setEntityId(null)}>change</button>
            <input style={{ ...AM_INPUT, flex: 1, minWidth: 180, width: 'auto' }} autoFocus value={alias}
              placeholder="word as it appears in the text" spellCheck={false}
              onChange={(e) => setAlias(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') submit(); }} />
            <button className="btn submit" disabled={!canSubmit || busy} onClick={submit}>add alias</button>
          </div>
        )
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <input style={AM_INPUT} autoFocus value={name} spellCheck={false}
            placeholder="entity name — a word in this statement → it gets linked"
            onChange={(e) => setName(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') submit(); }} />
          <input style={AM_INPUT} value={desc} spellCheck={false} placeholder="short description (optional)"
            onChange={(e) => setDesc(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') submit(); }} />
          <div><button className="btn submit" disabled={!canSubmit || busy} onClick={submit}>create entity</button></div>
        </div>
      )}

      {err && <div className="draft-banner" style={{ borderColor: 'var(--bad, #e0533d)', marginTop: 10 }}><span className="dbi"><I.warn width="15" height="15" /></span><span>{err}</span></div>}
    </div>
  );
}

function StatementDetail({ id }) {
  const router = useRouter();
  const idx = window.MYCELIUM_INDEX;
  const data = window.MYCELIUM_DATA;
  const [, bumpVer] = useStateI(0); // re-render after an edit patches the cache
  const s = idx.byId[id];
  if (!s || s._kind !== 'statement') return <main className="page narrow"><EmptyState title="Statement not found" blurb={`No record with id ${id}.`} /></main>;

  const out = idx.outgoing[id] || [];
  const inc = idx.incoming[id] || [];
  const mentions = (s.mentions || []).map(eid => idx.byId[eid]).filter(Boolean);
  const def = data.statementKinds.find(k => k.name === s.kind);

  return (
    <main className="page">
      <div className="crumbs">
        <a onClick={() => router.go({ view: 'landing' })}>~</a><span className="sep">/</span>
        <span>statement</span><span className="sep">/</span><span className="here">{s.id}</span>
      </div>

      <div className="inspect-grid">
        <div>
          <header className="stmt-head">
            <div className="stmt-meta">
              <KindTag kind={s.kind} />
              <span className="sm-id">{s.id}</span>
              <span className="sm-spacer" />
              <button className="btn" style={{ padding: '6px 12px' }} onClick={() => router.go({ view: 'ask', query: `Explain ${s.title}` })}>
                <I.ask width="14" height="14" />Ask about this
              </button>
            </div>
            <EditableStatementText statement={s} idx={idx} className="stmt-text" onSaved={() => bumpVer(v => v + 1)} />
          </header>

          <section className="sec">
            <div className="sec-head"><span className="sh-title">mentions · entities</span><span className="sh-count">{mentions.length}</span></div>
            {mentions.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 7, marginTop: 12 }}>
                {mentions.map(e => <EntityChip key={e.id} entity={e} />)}
              </div>
            )}
            <AddMention />
          </section>

          <section className="sec">
            <div className="sec-head"><span className="sh-title">→ outgoing links</span><span className="sh-count">{out.length}</span></div>
            {out.length === 0 ? <div className="rail-empty" style={{ padding: '14px 2px', fontFamily: 'var(--mono)', fontSize: 'var(--fs-xs)', color: 'var(--ink-4)' }}>// none — leaf node</div>
              : out.map((l, i) => <LinkLine key={i} link={l} dir="out" idx={idx} />)}
          </section>

          <section className="sec">
            <div className="sec-head"><span className="sh-title">← incoming links</span><span className="sh-count">{inc.length}</span></div>
            {inc.length === 0 ? <div className="rail-empty" style={{ padding: '14px 2px', fontFamily: 'var(--mono)', fontSize: 'var(--fs-xs)', color: 'var(--ink-4)' }}>// none — entry point</div>
              : inc.map((l, i) => <LinkLine key={i} link={l} dir="in" idx={idx} />)}
          </section>
        </div>

        <aside className="rail">
          <div className="rail-sec">
            <div className="rs-label">record</div>
            <div className="rail-kv"><span className="k">kind</span><span className="v">{s.kind}</span></div>
            <div className="rail-kv"><span className="k">layer</span><span className="v">{def ? def.layer : '—'}</span></div>
            <div className="rail-kv"><span className="k">id</span><span className="v">{s.id}</span></div>
          </div>
          <div className="rail-sec">
            <div className="rs-label">degree</div>
            <div className="rail-kv"><span className="k">outgoing</span><span className="v">{out.length}</span></div>
            <div className="rail-kv"><span className="k">incoming</span><span className="v">{inc.length}</span></div>
            <div className="rail-kv"><span className="k">mentions</span><span className="v">{mentions.length}</span></div>
            <div className="rail-kv"><span className="k">gated edges</span><span className="v">{[...out, ...inc].filter(l => l.when).length}</span></div>
          </div>
          {def && (
            <div className="rail-sec">
              <div className="rs-label">about this kind</div>
              <div style={{ fontSize: 'var(--fs-sm)', color: 'var(--ink-3)', lineHeight: 1.5 }}>
                <b style={{ color: 'var(--ink-2)', fontFamily: 'var(--mono)', fontSize: 'var(--fs-xs)' }}>{def.name}</b> — {def.gloss}. A <b style={{ color: 'var(--ink-2)' }}>{def.layer}</b> kind.
              </div>
            </div>
          )}
        </aside>
      </div>
    </main>
  );
}

function EntityDetail({ id }) {
  const router = useRouter();
  const idx = window.MYCELIUM_INDEX;
  const e = idx.byId[id];
  if (!e || e._kind !== 'entity') return <main className="page narrow"><EmptyState title="Entity not found" blurb={`No record with id ${id}.`} /></main>;

  const aliases = idx.namesByEntity[id] || [];
  const mentionedBy = idx.mentionsByEntity[id] || [];

  return (
    <main className="page">
      <div className="crumbs">
        <a onClick={() => router.go({ view: 'landing' })}>~</a><span className="sep">/</span>
        <span>entity</span><span className="sep">/</span><span className="here">{e.id}</span>
      </div>

      <div className="inspect-grid">
        <div>
          <header className="stmt-head">
            <div className="stmt-meta">
              <span className="echip" style={{ cursor: 'default' }}>{e.name}</span>
              <span className="sm-id">{e.id}</span>
              <span className="sm-spacer" />
              <button className="btn" style={{ padding: '6px 12px' }} onClick={() => router.go({ view: 'find', query: e.name, mode: 'semantic' })}>
                <I.find width="13" height="13" />Find mentions
              </button>
            </div>
            <h1 className="entity-name">{e.name}</h1>
            <p className="entity-desc">{e.description}</p>
            {aliases.length > 0 && (
              <div className="alias-row">
                {aliases.map(n => <span key={n.id} className="alias">{n.text}</span>)}
              </div>
            )}
          </header>

          <section className="sec">
            <div className="sec-head"><span className="sh-title">← mentioned by · statements</span><span className="sh-count">{mentionedBy.length}</span></div>
            {mentionedBy.length === 0 ? <div className="rail-empty" style={{ padding: '14px 2px', fontFamily: 'var(--mono)', fontSize: 'var(--fs-xs)', color: 'var(--ink-4)' }}>// not mentioned by any statement</div>
              : mentionedBy.map(s => (
                <div key={s.id} className="linkline" onClick={() => router.go({ view: 'statement', id: s.id })}>
                  <span className="ll-dir">←</span>
                  <KindTag kind={s.kind} />
                  <span className="ll-target">{s.title || s.text}</span>
                  <span className="ll-tid">{s.id}</span>
                </div>
              ))}
          </section>
        </div>

        <aside className="rail">
          <div className="rail-sec">
            <div className="rs-label">record</div>
            <div className="rail-kv"><span className="k">kind</span><span className="v">entity</span></div>
            <div className="rail-kv"><span className="k">id</span><span className="v">{e.id}</span></div>
          </div>
          <div className="rail-sec">
            <div className="rs-label">reach</div>
            <div className="rail-kv"><span className="k">aliases</span><span className="v">{aliases.length}</span></div>
            <div className="rail-kv"><span className="k">mentioned by</span><span className="v">{mentionedBy.length}</span></div>
          </div>
          <div className="rail-sec">
            <div className="rs-label">names · resolve to this entity</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
              {aliases.length ? aliases.map(n => <span key={n.id} className="lt">{n.text}</span>) : <span style={{ fontFamily: 'var(--mono)', fontSize: 'var(--fs-xs)', color: 'var(--ink-4)' }}>// none</span>}
            </div>
          </div>
        </aside>
      </div>
    </main>
  );
}

Object.assign(window, { StatementDetail, EntityDetail });
