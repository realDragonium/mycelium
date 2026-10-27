// "Propose as draft": a writer or admin switches it on to stage their
// knowledge edits on their own draft instead of writing live (see
// `setProposing` in api.ts). Per browser, like the appearance preferences.
import { useCallback, useEffect, useState } from 'react';
import { getMyDraft, PROPOSAL_CHANGED, setProposing, type Me } from './api';
import { I } from './lib';
import { Link } from './router';
import { dataOf, useAsync } from './use-async';

const KEY = 'mycelium.proposeAsDraft';
const mayPropose = (me: Me) => me.role === 'writer' || me.role === 'admin';

function readStored(): boolean {
  try { return localStorage.getItem(KEY) === 'on'; } catch { return false; }
}

// Set during render, not in an effect, so the first requests a screen makes
// already carry the marker.
export function useProposeMode(me: Me): [boolean, (on: boolean) => void] {
  const [stored, setStored] = useState(readStored);
  const on = stored && mayPropose(me);
  setProposing(on);
  const set = useCallback((next: boolean) => {
    try { localStorage.setItem(KEY, next ? 'on' : 'off'); } catch { /* storage blocked: keep in memory */ }
    setStored(next);
  }, []);
  return [on, set];
}

export function ProposeToggle({ me, on, onChange }: { me: Me; on: boolean; onChange: (on: boolean) => void }) {
  if (!mayPropose(me)) return null;
  return (
    <button className={`propose-btn btn sm${on ? ' write' : ' ghost'}`} aria-pressed={on} onClick={() => onChange(!on)}
      title={on ? 'Your edits stage on your draft. Click to write live again.' : 'Stage your edits on a draft for review instead of writing live.'}>
      <I.edit width="14" height="14" />Propose as draft
    </button>
  );
}

// Reloads after each proposed write or change to a draft (submitting it
// included) and on every route change.
export function ProposalBanner({ routeKey, onTurnOff }: { routeKey: string; onTurnOff: () => void }) {
  const { state, reload } = useAsync(getMyDraft);
  useEffect(() => {
    window.addEventListener(PROPOSAL_CHANGED, reload);
    return () => window.removeEventListener(PROPOSAL_CHANGED, reload);
  }, [reload]);
  useEffect(reload, [routeKey, reload]);
  const draft = dataOf(state);
  const count = draft?.op_count ?? 0;
  return (
    <div className="restore-banner notice warn" role="status">
      <I.edit width="16" height="16" />
      <span>
        <strong>Proposing as a draft.</strong> Your edits to statements, links, concepts and names wait in your draft for review; nothing changes live.{' '}
        {draft
          ? <Link to={{ view: 'draft', id: draft.id }}>{count} change{count === 1 ? '' : 's'} in your draft</Link>
          : 'Your draft opens with your first edit.'}
      </span>
      <span className="spacer" />
      <button className="btn sm ghost" onClick={onTurnOff}>Write live</button>
    </div>
  );
}
