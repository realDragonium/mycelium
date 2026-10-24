// AI usage: the tokens each action and model used over a period and the
// largest recent runs. Mycelium keeps no prices and sets no budget; spend and
// spend limits are on each provider's billing dashboard.
import { useCallback, useState, type ReactNode } from 'react';
import { Card, LoadError, Loading, Notice, useMe } from './lib';
import { Link } from './router';
import { getJSON } from './api';
import { useAsync } from './use-async';

interface TokenCounts { calls: number; input_tokens: number; cached_tokens: number; output_tokens: number; tokens: number }
interface Totals extends TokenCounts { failed_calls: number }
interface Day { day: string; calls: number; tokens: number }
interface ActionUsage extends TokenCounts { action: string }
interface ModelUsage extends TokenCounts { provider: string; model: string }
interface RunUsage { action: string; run_id: string | null; draft_id: string | null; calls: number; tokens: number; last_at: string }
interface UsageView { days: number; report: { since: string; totals: Totals; days: Day[]; actions: ActionUsage[]; models: ModelUsage[]; runs: RunUsage[] } }

const PERIODS = [7, 30, 90] as const;
export const ACTION_LABELS: Record<string, string> = {
  ask: 'Questions (Ask)', ingest: 'Ingestion', docgen: 'Document generation', documentation_planning: 'Documentation planning',
  draft_review: 'Draft review', alias_discovery: 'Alias discovery', audience_labelling: 'Audience labelling', connect: 'Connect pass',
  embedding: 'Embeddings',
  other: 'Other',
};
const actionLabel = (action: string) => ACTION_LABELS[action] || action;

export const tokens = (count: number) => count >= 1_000_000 ? `${(count / 1_000_000).toFixed(1)}M` : count >= 1000 ? `${(count / 1000).toFixed(1)}k` : String(count);

function RunLink({ run }: { run: RunUsage }) {
  const id = run.run_id || run.draft_id || '';
  if (run.draft_id) return <Link to={{ view: 'draft', id: run.draft_id }} className="mono">{run.draft_id}</Link>;
  if (id.startsWith('drn_')) return <a className="mono" href={`#/documentation?run=${encodeURIComponent(id)}`}>{id}</a>;
  if (id.startsWith('dpl_')) return <a className="mono" href="#/documentation?tab=plan">{id}</a>;
  return <span className="mono">{id}</span>;
}

function DailyTokens({ days, since, period }: { days: Day[]; since: string; period: number }) {
  const byDay = new Map(days.map(d => [d.day, d]));
  const start = new Date(since);
  const series = Array.from({ length: period }, (_, i) => {
    const day = new Date(start.getTime() + i * 86_400_000).toISOString().slice(0, 10);
    return byDay.get(day) || { day, calls: 0, tokens: 0 };
  });
  const max = Math.max(...series.map(d => d.tokens), 0);
  if (max === 0) return <p className="muted">No tokens used in this period.</p>;
  return (
    <div className="usage-bars" role="img" aria-label="Tokens per day">
      {series.map(d => (
        <div key={d.day} className="usage-bar" title={`${d.day}: ${tokens(d.tokens)} tokens · ${d.calls} calls`}>
          <span style={{ height: `${Math.max(d.tokens / max * 100, d.tokens > 0 ? 2 : 0)}%` }} />
        </div>
      ))}
      <div className="usage-axis"><span>{series[0].day}</span><span>{series[series.length - 1].day} (UTC)</span></div>
    </div>
  );
}

export function AIUsage() {
  const me = useMe();
  const [period, setPeriod] = useState<number>(30);
  const isAdmin = me?.role === 'admin';
  const load = useCallback(() => getJSON<UsageView>(`/api/ai-usage?days=${period}`), [period]);
  const { state, reload } = useAsync(load);
  if (!me) return <Loading what="your account" />;
  if (!isAdmin) return <Notice>Only administrators can see what AI actions use.</Notice>;

  return (
    <Card title="Token usage" actions={<>
      <select className="input" value={period} aria-label="Period" onChange={e => setPeriod(Number(e.target.value))}>
        {PERIODS.map(p => <option key={p} value={p}>Last {p} days</option>)}
      </select>
      <button type="button" className="btn ghost sm" onClick={reload}>Reload</button>
    </>}>
      {state.status === 'loading' && <Loading what="AI usage" />}
      {state.status === 'error' && <LoadError error={state.error} what="AI usage" onRetry={reload} />}
      {state.status === 'ready' && <UsageReport view={state.data} />}
    </Card>
  );
}

function UsageReport({ view }: { view: UsageView }) {
  const { report } = view;
  const t = report.totals;
  return <>
    <dl className="kv-grid">
      <dt>Tokens</dt><dd><strong>{tokens(t.tokens)}</strong> · {tokens(t.input_tokens)} input · {tokens(t.cached_tokens)} cached · {tokens(t.output_tokens)} output</dd>
      <dt>Model calls</dt><dd>{t.calls}{t.failed_calls > 0 && <span className="muted"> · {t.failed_calls} failed or truncated (counted, since they used tokens)</span>}</dd>
    </dl>
    <h3 className="section-label">Per day</h3>
    <DailyTokens days={report.days} since={report.since} period={view.days} />
    <h3 className="section-label">Per action</h3>
    <TokenTable rows={report.actions.map(a => ({ key: a.action, label: actionLabel(a.action), ...a }))} />
    <h3 className="section-label">Per model</h3>
    <TokenTable rows={report.models.map(m => ({ key: `${m.provider}/${m.model}`, label: <>{m.provider} / <span className="mono">{m.model}</span></>, ...m }))} />
    <h3 className="section-label">Largest runs</h3>
    {report.runs.length === 0 ? <p className="muted">No documentation runs, plans, draft reviews or connect passes made model calls in this period.</p> : (
      <table className="tbl compact">
        <thead><tr><th>Run</th><th>Action</th><th className="num">Calls</th><th className="num">Tokens</th><th className="num">Last call</th></tr></thead>
        <tbody>{report.runs.map(r => (
          <tr key={`${r.action}:${r.run_id || r.draft_id}`}>
            <td><RunLink run={r} /></td><td>{actionLabel(r.action)}</td><td className="num">{r.calls}</td>
            <td className="num">{tokens(r.tokens)}</td><td className="num">{new Date(r.last_at).toLocaleString()}</td>
          </tr>
        ))}</tbody>
      </table>
    )}
    <p className="hint">Input counts uncached input and cache writes; cached counts cache reads. For what this cost, and to set spend limits, see each provider's billing dashboard. Days are UTC.</p>
  </>;
}

function TokenTable({ rows }: { rows: (TokenCounts & { key: string; label: ReactNode })[] }) {
  if (!rows.length) return <p className="muted">No model calls in this period.</p>;
  return (
    <table className="tbl compact">
      <thead><tr><th>Name</th><th className="num">Calls</th><th className="num">Input</th><th className="num">Cached</th><th className="num">Output</th><th className="num">Total</th></tr></thead>
      <tbody>{rows.map(r => (
        <tr key={r.key}><td>{r.label}</td><td className="num">{r.calls}</td><td className="num">{tokens(r.input_tokens)}</td><td className="num">{tokens(r.cached_tokens)}</td><td className="num">{tokens(r.output_tokens)}</td><td className="num">{tokens(r.tokens)}</td></tr>
      ))}</tbody>
    </table>
  );
}
