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
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-indigo-900/50 bg-indigo-950/20 p-4">
      <div className="flex gap-3 min-w-0">
        <ShieldCheck className="w-5 h-5 text-indigo-400 shrink-0 mt-0.5" />
        <div className="min-w-0">
          <h2 className="text-sm font-bold text-white">Strict Data Privacy &amp; User Isolation (F.13 / MM3.1)</h2>
          <p className="text-xs text-slate-400">
            Every query is filtered in the database by your user id. You can never view or guess other users&apos; scans.
          </p>
          {verdict && <p className={`text-xs mt-1 ${verdict.ok ? 'text-emerald-300' : 'text-rose-300'}`} role="status">{verdict.text}</p>}
        </div>
      </div>
      <button type="button" onClick={probe} disabled={busy}
              className="px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-xs font-semibold text-white whitespace-nowrap">
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
      <h1 className="text-2xl font-bold text-white">Your results</h1>
      <PrivacyPanel />
      <ErrorNotice error={error} />
      {!data && !error && <p className="text-slate-400 text-sm flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" /> Loading…</p>}
      {data && data.total === 0 && (
        <Notice tone="info" title="No results yet.">
          <Link to="/" className="text-indigo-300 underline">Analyse an image</Link> to see it here.
        </Notice>
      )}
      {data && data.items.length > 0 && (
        <ul className="divide-y divide-slate-800 rounded-xl border border-slate-800 overflow-hidden">
          {data.items.map((item) => (
            <li key={item.prediction_id}>
              <Link to={`/results/${item.prediction_id}`} className="flex items-center gap-4 p-3 hover:bg-slate-900/70">
                <AuthImage src={item.thumbnail_url} alt={`Result ${item.prediction_id}`}
                           fallbackText="image unavailable"
                           className="w-16 h-12 sm:w-20 sm:h-14 rounded-md object-cover shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className={`font-semibold ${item.predicted_class === 'AI Generated' ? 'text-rose-300' : 'text-emerald-300'}`}>
                    {item.predicted_class}
                  </p>
                  <p className="text-xs text-slate-400">
                    {item.confidence_percentage.toFixed(1)}% ({item.confidence_band}) ·{' '}
                    {new Date(item.prediction_timestamp).toLocaleString()}
                  </p>
                </div>
                <span className="text-xs text-slate-500 font-mono">#{item.prediction_id}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {data && data.total_pages > 1 && (
        <nav className="flex items-center justify-between text-sm" aria-label="Pagination">
          <button type="button" disabled={page <= 1} onClick={() => setParams({ page: String(page - 1) })}
                  className="px-3 py-1.5 rounded-lg border border-slate-700 disabled:opacity-40">Previous</button>
          <span className="text-slate-400">Page {data.page} of {data.total_pages} · {data.total} results</span>
          <button type="button" disabled={page >= data.total_pages} onClick={() => setParams({ page: String(page + 1) })}
                  className="px-3 py-1.5 rounded-lg border border-slate-700 disabled:opacity-40">Next</button>
        </nav>
      )}
    </div>
  );
};
