import React, { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import { apiRequest } from '../api/client';
import type { HistoryPage as HistoryPageData } from '../api/types';
import { AuthImage } from '../components/AuthImage';
import { ErrorNotice, Notice } from '../components/Feedback';

const PAGE_SIZE = 10;

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
