const { useState: useStateDoc, useEffect: useEffectDoc, useRef: useRefDoc } = React;

const documentationActive = run => run.status === 'queued' || run.status === 'running';
const documentationStatus = {
  queued: 'Queued', running: 'Generating and reviewing', document_written: 'Document ready',
  document_superseded: 'Document updated by a later run', nothing_written: 'No document saved', failed: 'Failed',
};

function documentationModel(run) {
  const provider = run.provider === 'claude' ? 'Claude' : run.provider === 'openai' ? 'GPT' : null;
  return [provider, run.model].filter(Boolean).join(' · ') || 'Model not recorded';
}

function DocumentationResult({ runId, refresh }) {
  const [result, setResult] = useStateDoc(null);
  const [error, setError] = useStateDoc(null);
  const [retry, setRetry] = useStateDoc(0);

  useEffectDoc(() => {
    let cancelled = false;
    let timer;
    const controller = new AbortController();
    setError(null);
    const load = async () => {
      try {
        const run = await Myc.documentation.get(runId, controller.signal);
        const document = run.document_id ? await Myc.documentation.document(run.document_id, controller.signal) : null;
        if (cancelled) return;
        setResult({ run, document });
        setError(null);
        if (documentationActive(run)) timer = setTimeout(load, 2500);
      } catch (e) {
        if (cancelled) return;
        setError(e.message || 'Could not load this run.');
        if (![401, 403, 404].includes(e.status)) timer = setTimeout(load, 2500);
      }
    };
    load();
    return () => { cancelled = true; clearTimeout(timer); controller.abort(); };
  }, [runId, refresh, retry]);

  if (error) return <div className="doc-result"><p role="alert" className="stmt-edit-err">{error}</p><button className="btn ghost" onClick={() => setRetry(n => n + 1)}>Retry loading run</button></div>;
  if (!result) return <p role="status">Loading run…</p>;
  const { run, document } = result;
  const body = document ? document.body : run.draft_body;
  const reference = document && document.delivery_reference;
  const safeReference = typeof reference === 'string' && /^https?:\/\//i.test(reference) ? reference : null;
  const superseded = run.document_superseded || (document && document.last_run_id && document.last_run_id !== run.id);
  return <section className="doc-result" aria-label="Selected documentation run">
    <div className="doc-result-head"><h2>{document ? document.title : run.draft_title || 'Run details'}</h2><span className="st-badge" data-doc-status={run.status}>{documentationStatus[run.status] || run.status}</span></div>
    <p className="doc-meta">{documentationModel(run)}</p>
    <p className="doc-request">{run.prompt}</p>
    {documentationActive(run) && <p role="status">The document is being generated and reviewed. You can leave this screen and return to the run.</p>}
    {run.error && <p className="stmt-edit-err">{run.error}</p>}
    {superseded && <p className="stmt-edit-warn">This run’s document has been updated. The body below is the current version.</p>}
    {!document && run.draft_body && <p className="stmt-edit-warn">This draft was not saved as a generated document.</p>}
    {document && <p className="doc-meta">{document.guideline_set}{document.document_type ? ' · ' + document.document_type : ''}</p>}
    {safeReference && <a className="doc-delivery" href={safeReference} target="_blank" rel="noopener noreferrer">Open delivery reference ↗</a>}
    {body && <><h3>{document ? 'Document' : 'Unsaved draft'} · Markdown</h3><pre className="doc-body">{body}</pre></>}
  </section>;
}

function DocumentationSurface({ runId }) {
  const router = useRouter();
  const [options, setOptions] = useStateDoc(null);
  const [optionsError, setOptionsError] = useStateDoc(null);
  const [optionsRetry, setOptionsRetry] = useStateDoc(0);
  const [provider, setProvider] = useStateDoc('claude');
  const [prompt, setPrompt] = useStateDoc('');
  const [guidelineSet, setGuidelineSet] = useStateDoc('');
  const [documentType, setDocumentType] = useStateDoc('');
  const [runs, setRuns] = useStateDoc([]);
  const [runsError, setRunsError] = useStateDoc(null);
  const [loadingRuns, setLoadingRuns] = useStateDoc(true);
  const [refresh, setRefresh] = useStateDoc(0);
  const [busy, setBusy] = useStateDoc(false);
  const [submitError, setSubmitError] = useStateDoc(null);
  const submitting = useRefDoc(false);
  const alive = useRefDoc(true);

  useEffectDoc(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);

  useEffectDoc(() => {
    let cancelled = false;
    setOptionsError(null);
    Myc.documentation.options().then(value => {
      if (cancelled) return;
      setOptions(value);
      setProvider(value.default_provider);
    }).catch(e => { if (!cancelled) setOptionsError(e.message || 'Could not load model options.'); });
    return () => { cancelled = true; };
  }, [optionsRetry]);

  useEffectDoc(() => {
    let cancelled = false;
    let timer;
    const controller = new AbortController();
    const load = async () => {
      try {
        const value = await Myc.documentation.list(controller.signal);
        if (cancelled) return;
        setRuns(value);
        setRunsError(null);
        if (value.some(documentationActive)) timer = setTimeout(load, 2500);
      } catch (e) {
        if (cancelled) return;
        setRunsError(e.message || 'Could not load documentation runs.');
        if (![401, 403].includes(e.status)) timer = setTimeout(load, 2500);
      } finally {
        if (!cancelled) setLoadingRuns(false);
      }
    };
    load();
    return () => { cancelled = true; clearTimeout(timer); controller.abort(); };
  }, [refresh]);

  const selected = options && options.models.find(model => model.provider === provider);
  const canGenerate = !!(options && options.can_generate && selected && selected.available);
  const templates = options && guidelineSet ? options.guideline_sets[guidelineSet] || [] : [];
  const start = async e => {
    e.preventDefault();
    if (submitting.current || !canGenerate || !prompt.trim()) return;
    submitting.current = true;
    setBusy(true);
    setSubmitError(null);
    try {
      const run = await Myc.documentation.start({
        prompt: prompt.trim(), provider,
        guideline_set: guidelineSet || null, document_type: documentType || null,
      });
      if (!alive.current) return;
      setRefresh(n => n + 1);
      router.go({ view: 'documentation', id: run.id });
    } catch (e) {
      if (alive.current) setSubmitError(e.status === 403 ? 'Writer or admin access is required to generate documents.' : e.message || 'Could not start generation.');
    } finally {
      submitting.current = false;
      if (alive.current) setBusy(false);
    }
  };

  return <main className="page narrow"><div className="ingest-stage documentation-stage">
    <div className="crumbs"><a href="#/">~</a><span className="sep">/</span><span>documentation</span></div>
    <h1 className="ingest-title">Generate a document</h1>
    <p className="ingest-sub">Describe what to document and who it is for. The selected model writes and reviews it against the knowledge in Mycelium.</p>
    <p className="doc-meta"><a href="#/settings">Configure AI defaults</a>. The model selected below applies only to this document.</p>
    {optionsError ? <div><p role="alert" className="stmt-edit-err">{optionsError}</p><button className="btn ghost" onClick={() => setOptionsRetry(n => n + 1)}>Retry loading models</button></div> : !options && <p role="status">Loading model options…</p>}
    {options && <form onSubmit={start}>
      <fieldset className="doc-models" disabled={busy}>
        <legend>Model for this document</legend>
        <div className="doc-model-grid">{options.models.map(model => <label key={model.provider} className={`doc-model${provider === model.provider ? ' selected' : ''}${!model.available ? ' unavailable' : ''}`}>
          <span className="doc-model-label"><input type="radio" name="documentation-model" value={model.provider} checked={provider === model.provider} disabled={!model.available} onChange={() => setProvider(model.provider)} />{model.label}</span>
          <span className="doc-model-id">{model.model || 'No model configured'}</span>
          {!model.available && <span className="doc-model-reason">{model.reason || 'Unavailable'}</span>}
        </label>)}</div>
      </fieldset>
      <div className="doc-guidance">
        <label>Writing guidance<select value={guidelineSet} disabled={busy} onChange={e => { setGuidelineSet(e.target.value); setDocumentType(''); }}><option value="">Choose automatically</option>{Object.keys(options.guideline_sets).map(name => <option key={name} value={name}>{name}</option>)}</select></label>
        <label>Document template<select value={documentType} disabled={busy || !guidelineSet} onChange={e => setDocumentType(e.target.value)}><option value="">Choose automatically</option>{templates.map(name => <option key={name} value={name}>{name}</option>)}</select></label>
      </div>
      <label className="doc-prompt-label" htmlFor="documentation-prompt">What should be documented?</label>
      <div className="ingest-field">
        <textarea id="documentation-prompt" value={prompt} disabled={busy} maxLength={options.max_prompt_chars} onChange={e => setPrompt(e.target.value)} placeholder="For example: Explain how invitation reminders work for administrators, with setup steps and examples." required />
        <div className="ingest-foot"><span className="if-meta">{prompt.length} / {options.max_prompt_chars} characters</span><span className="if-spacer" /><button type="submit" className="btn extract" disabled={!canGenerate || !prompt.trim() || busy}>{busy ? 'Starting…' : 'Generate document'}</button></div>
      </div>
      {!options.can_generate && <p className="doc-meta">Writer or admin access is required to generate documents. You can view existing runs below.</p>}
      {submitError && <p role="alert" className="stmt-edit-err">{submitError}</p>}
    </form>}
    <div className="doc-runs-head"><h2>Documentation runs</h2><button className="btn ghost" onClick={() => setRefresh(n => n + 1)}>Refresh runs</button></div>
    {runsError && <p role="alert" className="stmt-edit-err">{runsError} Use Refresh runs to try again.</p>}
    {loadingRuns ? <p role="status">Loading runs…</p> : runs.length === 0 && !runsError ? <p className="doc-meta">No documentation runs yet.</p> : <div className="doc-runs">{runs.map(run => <button key={run.id} className={`doc-run${runId === run.id ? ' selected' : ''}`} onClick={() => router.go({ view: 'documentation', id: run.id })}>
      <span className="doc-run-prompt">{run.prompt}</span>
      <span className="doc-meta">{documentationModel(run)} · {new Date(run.created_at).toLocaleString()}</span>
      <span className="doc-run-status" data-doc-status={run.status}>{documentationStatus[run.status] || run.status}</span>
    </button>)}</div>}
    {runId && <DocumentationResult key={runId} runId={runId} refresh={refresh} />}
  </div></main>;
}

Object.assign(window, { DocumentationSurface });
