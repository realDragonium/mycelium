// AI usage: what each action and model cost over a period, the costliest
// recent runs, and the optional monthly budget. Costs are list-price
// estimates, never a bill.
import { useCallback, useState, type ReactNode } from 'react';
import { Card, LoadError, Loading, Notice, useMe } from './lib';
import { Link } from './router';
import { getJSON } from './api';
import { ProductSettings } from './product-settings';
import { useAsync } from './use-async';

interface Totals { calls: number; failed_calls: number; unpriced_calls: number; input_tokens: number; cached_tokens: number; output_tokens: number; cost_usd: number }
interface Day { day: string; calls: number; cost_usd: number }
interface ActionSpend { action: string; calls: number; input_tokens: number; output_tokens: number; cost_usd: number }
interface ModelSpend extends ActionSpend { provider: string; model: string; priced: boolean }
interface RunSpend { action: string; run_id: string | null; draft_id: string | null; calls: number; cost_usd: number; last_at: string }
export interface Budget { limit_usd: number; spent_usd: number; percent: number; warn_percent: number; warning: boolean; paused: boolean; month_start: string }
interface UsageView { days: number; report: { since: string; totals: Totals; days: Day[]; actions: ActionSpend[]; models: ModelSpend[]; runs: RunSpend[] }; budget: Budget | null }

const PERIODS = [7, 30, 90] as const;
export const ACTION_LABELS: Record<string, string> = {
  ask: 'Questions (Ask)', ingest: 'Ingestion', docgen: 'Document generation', documentation_planning: 'Documentation planning',
  draft_review: 'Draft review', alias_discovery: 'Alias discovery', audience_labelling: 'Audience labelling', connect: 'Connect pass',
  embedding: 'Embeddings',
  other: 'Other',
};
const actionLabel = (action: string) => ACTION_LABELS[action] || action;

export const usd = (value: number) => `$${value.toFixed(value >= 100 ? 0 : value >= 1 ? 2 : 4)}`;
const tokens = (count: number) => count >= 1_000_000 ? `${(count / 1_000_000).toFixed(1)}M` : count >= 1000 ? `${(count / 1000).toFixed(1)}k` : String(count);

function RunLink({ run }: { run: RunSpend }) {
  const id = run.run_id || run.draft_id || '';
  if (run.draft_id) return <Link to={{ view: 'draft', id: run.draft_id }} className="mono">{run.draft_id}</Link>;
  if (id.startsWith('drn_')) return <a className="mono" href={`#/documentation?run=${encodeURIComponent(id)}`}>{id}</a>;
  if (id.startsWith('dpl_')) return <a className="mono" href="#/documentation?tab=plan">{id}</a>;
  return <span className="mono">{id}</span>;
}

function DailySpend({ days, since, period }: { days: Day[]; since: string; period: number }) {
  const byDay = new Map(days.map(d => [d.day, d]));
  const start = new Date(since);
  const series = Array.from({ length: period }, (_, i) => {
    const day = new Date(start.getTime() + i * 86_400_000).toISOString().slice(0, 10);
    return byDay.get(day) || { day, calls: 0, cost_usd: 0 };
  });
  const max = Math.max(...series.map(d => d.cost_usd), 0);
  if (max === 0) return <p className="muted">No estimated spend in this period.</p>;
  return (
    <div className="usage-bars" role="img" aria-label="Estimated spend per day">
      {series.map(d => (
        <div key={d.day} className="usage-bar" title={`${d.day}: about ${usd(d.cost_usd)} · ${d.calls} calls`}>
          <span style={{ height: `${Math.max(d.cost_usd / max * 100, d.cost_usd > 0 ? 2 : 0)}%` }} />
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
  if (!isAdmin) return <Notice>Only administrators can see what AI actions cost.</Notice>;

  return <>
    <Card title="Estimated spend" actions={<>
      <select className="input" value={period} aria-label="Period" onChange={e => setPeriod(Number(e.target.value))}>
        {PERIODS.map(p => <option key={p} value={p}>Last {p} days</option>)}
      </select>
      <button type="button" className="btn ghost sm" onClick={reload}>Reload</button>
    </>}>
      {state.status === 'loading' && <Loading what="AI usage" />}
      {state.status === 'error' && <LoadError error={state.error} what="AI usage" onRetry={reload} />}
      {state.status === 'ready' && <UsageReport view={state.data} />}
    </Card>
    <ProductSettings kinds={['ai_budget']} />
  </>;
}

function UsageReport({ view }: { view: UsageView }) {
  const { report, budget } = view;
  const t = report.totals;
  return <>
    {budget && <BudgetLine budget={budget} />}
    <dl className="kv-grid">
      <dt>Estimated cost</dt><dd><strong>{usd(t.cost_usd)}</strong>{t.unpriced_calls > 0 && <span className="warn-text small"> · {t.unpriced_calls} calls to models without a list price are not included</span>}</dd>
      <dt>Model calls</dt><dd>{t.calls}{t.failed_calls > 0 && <span className="muted"> · {t.failed_calls} failed or truncated (counted, since they used tokens)</span>}</dd>
      <dt>Tokens</dt><dd>{tokens(t.input_tokens)} in ({tokens(t.cached_tokens)} from cache) · {tokens(t.output_tokens)} out</dd>
    </dl>
    <h3 className="section-label">Per day</h3>
    <DailySpend days={report.days} since={report.since} period={view.days} />
    <h3 className="section-label">Per action</h3>
    <SpendTable rows={report.actions.map(a => ({ key: a.action, label: actionLabel(a.action), ...a }))} />
    <h3 className="section-label">Per model</h3>
    <SpendTable rows={report.models.map(m => ({ key: `${m.provider}/${m.model}`, label: <>{m.provider} / <span className="mono">{m.model}</span>{!m.priced && <span className="warn-text small"> · no list price</span>}</>, ...m }))} />
    <h3 className="section-label">Most expensive runs</h3>
    {report.runs.length === 0 ? <p className="muted">No documentation runs, plans, draft reviews or connect passes made model calls in this period.</p> : (
      <table className="tbl compact">
        <thead><tr><th>Run</th><th>Action</th><th className="num">Calls</th><th className="num">Est. cost</th><th className="num">Last call</th></tr></thead>
        <tbody>{report.runs.map(r => (
          <tr key={`${r.action}:${r.run_id || r.draft_id}`}>
            <td><RunLink run={r} /></td><td>{actionLabel(r.action)}</td><td className="num">{r.calls}</td>
            <td className="num">{usd(r.cost_usd)}</td><td className="num">{new Date(r.last_at).toLocaleString()}</td>
          </tr>
        ))}</tbody>
      </table>
    )}
    <p className="hint">Costs are estimates from list prices per million tokens, not a bill: they leave out long-context surcharges, discounts and provider-side retries. Days and months are UTC.</p>
  </>;
}

function SpendTable({ rows }: { rows: (ActionSpend & { key: string; label: ReactNode; priced?: boolean })[] }) {
  if (!rows.length) return <p className="muted">No model calls in this period.</p>;
  return (
    <table className="tbl compact">
      <thead><tr><th>Name</th><th className="num">Calls</th><th className="num">Input</th><th className="num">Output</th><th className="num">Est. cost</th></tr></thead>
      <tbody>{rows.map(r => (
        <tr key={r.key}><td>{r.label}</td><td className="num">{r.calls}</td><td className="num">{tokens(r.input_tokens)}</td><td className="num">{tokens(r.output_tokens)}</td><td className="num">{r.priced === false && r.cost_usd === 0 ? '—' : usd(r.cost_usd)}</td></tr>
      ))}</tbody>
    </table>
  );
}

export function BudgetLine({ budget }: { budget: Budget }) {
  const tone = budget.paused ? 'error' : budget.warning ? 'warn' : 'info';
  return (
    <Notice tone={tone}>
      This month: about {usd(budget.spent_usd)} of the {usd(budget.limit_usd)} budget ({budget.percent}%).
      {budget.paused ? ' Background actions (audience labelling, draft review, connect pass) are paused until next month or until the budget is raised.'
        : budget.warning ? ` Past the ${budget.warn_percent}% warning threshold.` : ''}
    </Notice>
  );
}
