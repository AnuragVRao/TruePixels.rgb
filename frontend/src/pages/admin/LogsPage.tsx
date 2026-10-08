import React, { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import { apiRequest } from '../../api/client';
import type { PaginatedLogs } from '../../api/adminTypes';
import { ErrorNotice, Notice } from '../../components/Feedback';
import { Pager, when } from './AdminLayout';

const PAGE_SIZE = 25;
const EVENT_TYPES = ['authentication', 'prediction-request', 'administrative-action', 'error'];
const SEVERITIES = ['info', 'warning', 'error'];
const SEVERITY_TONE: Record<string, string> = {
  error: 'text-rose-700 dark:text-rose-300', warning: 'text-amber-700 dark:text-amber-300', info: 'text-foreground/80',
};
const select = 'rounded-lg bg-card border border-border px-2 py-1.5 text-sm text-foreground';

/** datetime-local (browser-local time) -> ISO 8601 in UTC, as the API expects. */
function toIso(local: string): string | null {
  if (!local) return null;
  const parsed = new Date(local);
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
}

/**
 * D6 audit log. Every field - event_detail above all, which can quote
 * user-supplied text such as e-mail addresses or file names - is rendered as
 * a React text node: plain text, never HTML. Viewing logs is itself audited.
 */
export const LogsPage: React.FC = () => {
  const [params, setParams] = useSearchParams();
  const page = Math.max(1, Number(params.get('page')) || 1);
  const eventType = params.get('event_type') ?? '';
  const severity = params.get('severity') ?? '';
  const from = params.get('from') ?? '';
  const to = params.get('to') ?? '';
  const [data, setData] = useState<PaginatedLogs | null>(null);
  const [error, setError] = useState<unknown>(null);

  const update = (changes: Record<string, string>) => {
    const next = new URLSearchParams(params);
    Object.entries(changes).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    if (!('page' in changes)) next.delete('page');
    setParams(next);
  };

  useEffect(() => {
    const controller = new AbortController();
    const query = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) });
    if (eventType) query.set('event_type', eventType);
    if (severity) query.set('severity', severity);
    const start = toIso(from);
    const end = toIso(to);
    if (start) query.set('start_time', start);
    if (end) query.set('end_time', end);
    setData(null);
    setError(null);
    apiRequest<PaginatedLogs>(`/admin/logs?${query}`, { signal: controller.signal })
      .then(setData)
      .catch((err) => { if ((err as Error).name !== 'AbortError') setError(err); });
    return () => controller.abort();
  }, [page, eventType, severity, from, to]);

  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-bold text-foreground">Audit log</h1>
      <form className="flex flex-wrap items-end gap-3" aria-label="Log filters" onSubmit={(e) => e.preventDefault()}>
        <label className="text-xs text-muted-foreground space-y-1">
          <span className="block">Event type</span>
          <select className={select} value={eventType} onChange={(e) => update({ event_type: e.target.value })}>
            <option value="">all</option>
            {EVENT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
        <label className="text-xs text-muted-foreground space-y-1">
          <span className="block">Severity</span>
          <select className={select} value={severity} onChange={(e) => update({ severity: e.target.value })}>
            <option value="">all</option>
            {SEVERITIES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label className="text-xs text-muted-foreground space-y-1">
          <span className="block">From (your local time)</span>
          <input type="datetime-local" className={select} value={from} onChange={(e) => update({ from: e.target.value })} />
        </label>
        <label className="text-xs text-muted-foreground space-y-1">
          <span className="block">To</span>
          <input type="datetime-local" className={select} value={to} onChange={(e) => update({ to: e.target.value })} />
        </label>
        {(eventType || severity || from || to) && (
          <button type="button" className="text-sm text-primary hover:underline pb-1.5"
                  onClick={() => setParams(new URLSearchParams())}>Clear filters</button>
        )}
      </form>

      <ErrorNotice error={error} />
      {!data && !error && (
        <p className="text-muted-foreground text-sm flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" /> Loading…</p>
      )}
      {data && data.total === 0 && <Notice tone="info" title="No log entries match these filters." />}
      {data && data.items.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full text-sm">
            <thead className="bg-card text-left text-xs uppercase tracking-wide text-muted-foreground/80">
              <tr>
                <th className="px-3 py-2">Time</th>
                <th className="px-3 py-2">Severity</th>
                <th className="px-3 py-2">Type</th>
                <th className="px-3 py-2">User</th>
                <th className="px-3 py-2">Detail</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border" data-testid="log-rows">
              {data.items.map((row) => (
                <tr key={row.log_id} className="align-top">
                  <td className="px-3 py-2 whitespace-nowrap text-muted-foreground">{when(row.log_timestamp)}</td>
                  <td className={`px-3 py-2 ${SEVERITY_TONE[row.severity] ?? 'text-foreground/80'}`}>{row.severity}</td>
                  <td className="px-3 py-2 text-foreground/80 whitespace-nowrap">{row.event_type}</td>
                  <td className="px-3 py-2 text-muted-foreground font-mono">{row.user_id ?? '—'}</td>
                  <td className="px-3 py-2 text-foreground whitespace-pre-wrap break-words max-w-xl">{row.event_detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && (
        <Pager page={data.page} totalPages={data.total_pages} total={data.total} noun="entries"
               onPage={(p) => update({ page: String(p) })} />
      )}
    </div>
  );
};
