import React, { useEffect, useState } from 'react';
import { ShieldCheck } from 'lucide-react';
import { getToken } from '../api/client';
import { Link, useSearchParams } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import { apiRequest } from '../api/client';
import type { HistoryPage as HistoryPageData } from '../api/types';
import { AuthImage } from '../components/AuthImage';
import { ErrorNotice, Notice } from '../components/Feedback';

const PAGE_SIZE = 10;

/**
 * From M3's original History tab: the isolation notice and its "Test Security
 * Barrier" button. It asks for a prediction id that is not yours; the API must
 * answer exactly as for one that does not exist (404 INF_PREDICTION_NOT_FOUND),
 * so nobody can tell whether another user's result exists. Raw fetch: the
 * expected 404 is not an app error.
 */
const PrivacyPanel: React.FC = () => {
  const [verdict, setVerdict] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const probe = async () => {
    setBusy(true);
    setVerdict(null);
    try {
      const response = await fetch('/api/v1/results/2147483647', { headers: { Authorization: `Bearer ${getToken() ?? ''}` } });
      const body = await response.json().catch(() => null);
      const ok = response.status === 404 && body?.error?.code === 'INF_PREDICTION_NOT_FOUND';
      setVerdict({ ok, text: ok
        ? 'Barrier active: the server answered 404 INF_PREDICTION_NOT_FOUND - the same answer as for a result that does not exist.'
        : `Unexpected answer: ${response.status} ${body?.error?.code ?? ''}` });
    } catch {
      setVerdict({ ok: false, text: 'Could not reach the server.' });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-primary/30 bg-primary/5 p-4">
      <div className="flex gap-3 min-w-0">
        <ShieldCheck className="w-5 h-5 text-primary shrink-0 mt-0.5" />
        <div className="min-w-0">
          <h2 className="text-sm font-bold text-foreground">Strict Data Privacy &amp; User Isolation (F.13 / MM3.1)</h2>
          <p className="text-xs text-muted-foreground">
            Every query is filtered in the database by your user id. You can never view or guess other users&apos; scans.
          </p>
          {verdict && <p className={`text-xs mt-1 ${verdict.ok ? 'text-emerald-700 dark:text-emerald-300' : 'text-rose-700 dark:text-rose-300'}`} role="status">{verdict.text}</p>}
        </div>
      </div>
      <button type="button" onClick={probe} disabled={busy}
              className="px-3 py-1.5 rounded-lg bg-primary hover:bg-primary/90 disabled:opacity-50 text-xs font-semibold text-primary-foreground whitespace-nowrap">
        Test Security Barrier
      </button>
    </div>
  );
};

export const HistoryPage: React.FC = () => {
  const [params, setParams] = useSearchParams();
  const page = Math.max(1, Number(params.get('page')) || 1);
  const [data, setData] = useState<HistoryPageData | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError(null);
    apiRequest<HistoryPageData>(`/history?page=${page}&page_size=${PAGE_SIZE}`, { signal: controller.signal })
      .then(setData)
      .catch((err) => { if ((err as Error).name !== 'AbortError') setError(err); });
    return () => controller.abort();
  }, [page]);

  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-bold text-foreground">Your results</h1>
      <PrivacyPanel />
      <ErrorNotice error={error} />
      {!data && !error && <p className="text-muted-foreground text-sm flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" /> Loading…</p>}
      {data && data.total === 0 && (
        <Notice tone="info" title="No results yet.">
          <Link to="/" className="text-primary underline">Analyse an image</Link> to see it here.
        </Notice>
      )}
      {data && data.items.length > 0 && (
        <ul className="divide-y divide-border rounded-xl border border-border overflow-hidden">
          {data.items.map((item) => (
            <li key={item.prediction_id}>
              <Link to={`/results/${item.prediction_id}`} className="flex items-center gap-4 p-3 hover:bg-card">
                <AuthImage src={item.thumbnail_url} alt={`Result ${item.prediction_id}`}
                           fallbackText="image unavailable"
                           className="w-16 h-12 sm:w-20 sm:h-14 rounded-md object-cover shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className={`font-semibold ${item.predicted_class === 'AI Generated' ? 'text-rose-700 dark:text-rose-300' : 'text-emerald-700 dark:text-emerald-300'}`}>
                    {item.predicted_class}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {item.p_ai_display !== null
                      ? `${item.p_ai_display} likely AI (${item.certainty_label})`
                      : 'likelihood not calibrated'}
                    {item.leans_ai_below_threshold ? ' · leans AI' : ''}
                    {item.semantic_only ? ' · low reliability' : ''} ·{' '}
                    {new Date(item.prediction_timestamp).toLocaleString()}
                  </p>
                </div>
                <span className="text-xs text-muted-foreground/80 font-mono">#{item.prediction_id}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {data && data.total_pages > 1 && (
        <nav className="flex items-center justify-between text-sm" aria-label="Pagination">
          <button type="button" disabled={page <= 1} onClick={() => setParams({ page: String(page - 1) })}
                  className="px-3 py-1.5 rounded-lg border border-border disabled:opacity-40">Previous</button>
          <span className="text-muted-foreground">Page {data.page} of {data.total_pages} · {data.total} results</span>
          <button type="button" disabled={page >= data.total_pages} onClick={() => setParams({ page: String(page + 1) })}
                  className="px-3 py-1.5 rounded-lg border border-border disabled:opacity-40">Next</button>
        </nav>
      )}
    </div>
  );
};
