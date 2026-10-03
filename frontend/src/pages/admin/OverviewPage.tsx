import React, { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { apiRequest } from '../../api/client';
import type { AdminSummary, SystemAnalytics } from '../../api/adminTypes';
import { ErrorNotice, Notice } from '../../components/Feedback';

const DAY_CHOICES = [7, 30, 90];
const axis = { stroke: '#64748b', fontSize: 12 };
const tooltip = { contentStyle: { background: '#0f172a', border: '1px solid #334155', color: '#e2e8f0' } };

/** Every figure on this page is read from /admin/summary or /admin/analytics. Nothing is hard-coded. */
const Tile: React.FC<{ label: string; value: React.ReactNode; note?: string; tone?: string }> = ({ label, value, note, tone }) => (
  <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
    <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
    <p className={`mt-1 text-2xl font-bold ${tone ?? 'text-white'}`}>{value}</p>
    {note && <p className="mt-1 text-xs text-slate-500">{note}</p>}
  </div>
);

const Panel: React.FC<{ title: string; note?: string; children: React.ReactNode }> = ({ title, note, children }) => (
  <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-4 space-y-3">
    <div>
      <h2 className="font-semibold text-white">{title}</h2>
      {note && <p className="text-xs text-slate-500">{note}</p>}
    </div>
    {children}
  </section>
);

const ms = (value: number | null | undefined) => (value == null ? 'n/a' : `${(value / 1000).toFixed(2)} s`);

export const OverviewPage: React.FC = () => {
  const [days, setDays] = useState(30);
  const [summary, setSummary] = useState<AdminSummary | null>(null);
  const [analytics, setAnalytics] = useState<SystemAnalytics | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    setAnalytics(null);
    Promise.all([
      apiRequest<AdminSummary>('/admin/summary', { signal: controller.signal }),
      apiRequest<SystemAnalytics>(`/admin/analytics?days=${days}`, { signal: controller.signal }),
    ])
      .then(([s, a]) => { setSummary(s); setAnalytics(a); })
      .catch((err) => { if ((err as Error).name !== 'AbortError') setError(err); });
    return () => controller.abort();
  }, [days]);

  const latency = analytics?.latency ?? null;
  const usage = analytics?.usage_over_time ?? [];
  const histogramEmpty = (analytics?.confidence_distribution ?? []).every((b) => b.count === 0);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold text-white">System overview</h1>
        <label className="text-sm text-slate-400 flex items-center gap-2">
          Window
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}
                  className="rounded-lg bg-slate-900 border border-slate-700 px-2 py-1 text-slate-100">
            {DAY_CHOICES.map((d) => <option key={d} value={d}>last {d} days</option>)}
          </select>
        </label>
      </div>
      <ErrorNotice error={error} />
      {!summary && !error && (
        <p className="text-slate-400 text-sm flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" /> Loading…</p>
      )}

      {summary && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <Tile label="Predictions (all time)" value={summary.total_predictions} />
          <Tile label="Predictions, last 24 h" value={summary.predictions_last_24h} />
          <Tile label="Called Real / AI Generated" value={
            `${summary.class_distribution['Real'] ?? 0} / ${summary.class_distribution['AI Generated'] ?? 0}`} note="all time" />
          <Tile label="Error log entries, last 24 h" value={summary.error_count_last_24h}
                tone={summary.error_count_last_24h > 0 ? 'text-rose-300' : 'text-white'} />
          <Tile label="Inference p50 (warm)" value={ms(latency?.p50_ms)}
                note={latency ? `${latency.warm_count} warm predictions, last ${analytics?.days} days` : undefined} />
          <Tile label="Inference p95 (warm)" value={ms(latency?.p95_ms)}
                note={latency ? `excludes ${latency.cold_count} cold start(s) and ${latency.unknown_count} unrecorded` : undefined} />
          <Tile label="Error share of all log entries" value={analytics ? `${analytics.error_rate_percentage}%` : '…'}
                note={analytics ? `${analytics.total_logs} log entries, all time` : undefined} />
          <Tile label="Active models" value={summary.active_models.length} note="see below" />
        </div>
      )}

      {summary && (
        <Panel title="Active models" note="What predictions run with now (from the model registry, D3).">
          {summary.active_models.length === 0 ? (
            <p className="text-sm text-slate-400">No active models are registered yet. The first prediction or the Models screen bootstraps them.</p>
          ) : (
            <ul className="text-sm divide-y divide-slate-800">
              {summary.active_models.map((m) => (
                <li key={m.model_type} className="py-2 flex flex-wrap gap-x-3">
                  <span className="text-slate-400 w-56">{m.model_type}</span>
                  <span className="text-slate-100">{m.model_name}</span>
                  <span className="font-mono text-xs text-slate-500 break-all">{m.version}</span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      )}

      {analytics && (
        <div className="grid lg:grid-cols-2 gap-4">
          <Panel title="Predictions per day" note={`UTC days, last ${analytics.days} days`}>
            {usage.length === 0 ? <p className="text-sm text-slate-400">No predictions in this window.</p> : (
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={usage}>
                    <CartesianGrid stroke="#1e293b" />
                    <XAxis dataKey="date" {...axis} />
                    <YAxis allowDecimals={false} {...axis} />
                    <Tooltip {...tooltip} />
                    <Legend />
                    <Line type="monotone" dataKey="predictions_count" name="predictions" stroke="#818cf8" dot={false} />
                    <Line type="monotone" dataKey="active_users" name="distinct users" stroke="#34d399" dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
          </Panel>

          <Panel title="Confidence in the predicted class" note="All predictions. Confidence is in whichever class was predicted - not P(AI).">
            {histogramEmpty ? <p className="text-sm text-slate-400">No predictions yet.</p> : (
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={analytics.confidence_distribution}>
                    <CartesianGrid stroke="#1e293b" />
                    <XAxis dataKey="bin_range" {...axis} interval={1} />
                    <YAxis allowDecimals={false} {...axis} />
                    <Tooltip {...tooltip} />
                    <Bar dataKey="count" name="predictions" fill="#818cf8" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </Panel>

          <Panel title="Inference latency per day (warm only)"
                 note="Seconds. Cold starts - a model loaded inside the request - are excluded, as are rows recorded before cold starts were tracked.">
            {analytics.latency_over_time.length === 0 ? (
              <p className="text-sm text-slate-400">No warm predictions in this window, so there is no latency to show.</p>
            ) : (
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={analytics.latency_over_time.map((p) => ({
                    ...p, p50: p.p50_ms == null ? null : p.p50_ms / 1000, p95: p.p95_ms == null ? null : p.p95_ms / 1000 }))}>
                    <CartesianGrid stroke="#1e293b" />
                    <XAxis dataKey="date" {...axis} />
                    <YAxis {...axis} />
                    <Tooltip {...tooltip} />
                    <Legend />
                    <Line type="monotone" dataKey="p50" name="p50 (s)" stroke="#34d399" />
                    <Line type="monotone" dataKey="p95" name="p95 (s)" stroke="#fbbf24" />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
          </Panel>
        </div>
      )}
      {analytics && analytics.total_predictions === 0 && (
        <Notice tone="info" title="No predictions have been made yet.">Charts fill in as people analyse images.</Notice>
      )}
    </div>
  );
};
