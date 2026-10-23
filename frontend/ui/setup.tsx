// The setup checklist: what an admin still has to configure, each step
// linking to the settings screen that completes it.
import { useCallback, useState } from 'react';
import { Card, I, LoadError, Loading, Notice, useMe } from './lib';
import { Link, type SettingsSection } from './router';
import { enc, errorMessage, getJSON, putJSON } from './api';
import { dataOf, useAsync, useOnSettingsSaved } from './use-async';

type StepId = 'credentials' | 'models' | 'audiences' | 'profile' | 'github' | 'review' | 'budget';
interface SetupStep {
  id: StepId; title: string; status: 'done' | 'todo' | 'dismissed'; detail: string;
  section: SettingsSection; optional: boolean;
}
export interface SetupView { steps: SetupStep[]; complete: boolean; blocked: { worker: string; reason: string }[]; quarantine: boolean }

export function useSetup() {
  const setup = useAsync(useCallback((signal: AbortSignal) => getJSON<SetupView>('/api/setup', signal), []));
  useOnSettingsSaved(setup.reload);
  return setup;
}

function Checklist({ view, onSaved, all }: { view: SetupView; onSaved: (view: SetupView) => void; all: boolean }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dismiss = async (step: StepId, dismissed: boolean) => {
    setBusy(true); setError(null);
    try { onSaved(await putJSON<SetupView>(`/api/setup/steps/${enc(step)}`, { dismissed })); }
    catch (e) { setError(errorMessage(e, 'The checklist could not be saved.')); }
    finally { setBusy(false); }
  };
  const steps = all ? view.steps : view.steps.filter(s => s.status === 'todo');
  return <>
    {error && <Notice tone="error">{error}</Notice>}
    <ul className="setup-steps">
      {steps.map(step => (
        <li key={step.id} className={`setup-step ${step.status}`}>
          <span className="ss-mark" aria-hidden>{step.status === 'done' ? <I.check width="15" height="15" /> : step.status === 'dismissed' ? <I.empty width="15" height="15" /> : <I.warn width="15" height="15" />}</span>
          <div className="grow">
            <div className="ss-title">
              <Link to={{ view: 'settings', section: step.section }}>{step.title}</Link>
              {step.optional && <span className="tag">optional</span>}
              <span className="muted small">{step.status === 'done' ? 'done' : step.status === 'dismissed' ? 'dismissed' : 'to do'}</span>
            </div>
            <div className="hint">{step.detail}</div>
          </div>
          {step.status === 'todo' && <button className="btn ghost xs" disabled={busy} onClick={() => void dismiss(step.id, true)}>Dismiss</button>}
          {step.status === 'dismissed' && <button className="btn ghost xs" disabled={busy} onClick={() => void dismiss(step.id, false)}>Restore</button>}
        </li>
      ))}
    </ul>
  </>;
}

const remaining = (view: SetupView) => view.steps.filter(s => s.status === 'todo').length;

// Home, admins only, until every step is done or dismissed.
export function HomeSetup() {
  const me = useMe();
  if (me?.role !== 'admin') return null;
  return <HomeSetupCard />;
}

function HomeSetupCard() {
  const { state, update } = useSetup();
  const view = dataOf(state);
  if (!view || view.complete) return null;
  const n = remaining(view);
  return (
    <section className="home-section" aria-label="Set up Mycelium">
      <Card title="Set up Mycelium" actions={<Link to={{ view: 'settings', section: 'setup' }} className="btn ghost sm">Full checklist</Link>}>
        <p className="muted">{n} step{n === 1 ? '' : 's'} left. Dismiss a step you do not need; it stays on the full checklist under Settings.</p>
        <Checklist view={view} onSaved={value => update(() => value)} all={false} />
      </Card>
    </section>
  );
}

export function SetupSection() {
  const me = useMe();
  if (!me) return <Loading what="your account" />;
  if (me.role !== 'admin') return <Notice>Only administrators set up this instance. You are signed in as a {me.role}.</Notice>;
  return <SetupCard />;
}

function SetupCard() {
  const { state, reload, update } = useSetup();
  const view = dataOf(state);
  if (!view) return state.status === 'error' ? <LoadError error={state.error} what="the setup checklist" onRetry={reload} /> : <Loading what="the setup checklist" />;
  const n = remaining(view);
  return (
    <Card title="Checklist">
      <p className="muted">{view.complete ? 'Every step is done or dismissed.' : `${n} step${n === 1 ? '' : 's'} left.`} Statuses come from the saved settings; credentials are checked for presence only, without calling a provider.</p>
      <Checklist view={view} onSaved={value => update(() => value)} all />
    </Card>
  );
}
