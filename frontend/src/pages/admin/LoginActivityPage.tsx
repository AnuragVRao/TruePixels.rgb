import React, { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import { apiRequest } from '../../api/client';
import type { LoginOutcome, PaginatedLoginEvents } from '../../api/types';
import { ErrorNotice, Notice } from '../../components/Feedback';
import { LoginActivityTable, OUTCOME } from '../../components/LoginActivityTable';
import { Pager } from './AdminLayout';

const PAGE_SIZE = 25;
const select = 'rounded-lg bg-slate-900 border border-slate-700 px-2 py-1.5 text-sm text-slate-100';

/** Every account's sign-ins and password changes, including attempts on unknown addresses. Viewing is audited. */
export const LoginActivityPage: React.FC = () => {
  const [params, setParams] = useSearchParams();
  const page = Math.max(1, Number(params.get('page')) || 1);
  const outcome = params.get('outcome') ?? '';
  const email = params.get('email') ?? '';
  const [emailDraft, setEmailDraft] = useState(email);
  const [data, setData] = useState<PaginatedLoginEvents | null>(null);
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
    if (outcome) query.set('outcome', outcome);
    if (email) query.set('email', email);
    setData(null);
    setError(null);
    apiRequest<PaginatedLoginEvents>(`/admin/login-activity?${query}`, { signal: controller.signal })
      .then(setData)
      .catch((err) => { if ((err as Error).name !== 'AbortError') setError(err); });
    return () => controller.abort();
  }, [page, outcome, email]);

  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-bold text-white">Login activity</h1>
      <form className="flex flex-wrap items-end gap-3" aria-label="Login activity filters"
            onSubmit={(e) => { e.preventDefault(); update({ email: emailDraft.trim().toLowerCase() }); }}>
        <label className="text-xs text-slate-400 space-y-1">
          <span className="block">Result</span>
          <select className={select} value={outcome} onChange={(e) => update({ outcome: e.target.value })}>
            <option value="">all</option>
            {(Object.keys(OUTCOME) as LoginOutcome[]).map((o) => <option key={o} value={o}>{OUTCOME[o].label}</option>)}
          </select>
        </label>
        <label className="text-xs text-slate-400 space-y-1">
          <span className="block">E-mail contains</span>
          <input className={select} value={emailDraft} onChange={(e) => setEmailDraft(e.target.value)}
                 placeholder="press Enter to filter" />
        </label>
        {(outcome || email) && (
          <button type="button" className="text-sm text-indigo-400 hover:underline pb-1.5"
                  onClick={() => { setEmailDraft(''); setParams(new URLSearchParams()); }}>Clear filters</button>
        )}
      </form>

      <ErrorNotice error={error} />
      {!data && !error && (
        <p className="text-slate-400 text-sm flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" /> Loading…</p>
      )}
      {data && data.total === 0 && <Notice tone="info" title="No sign-ins match these filters." />}
      {data && data.items.length > 0 && <LoginActivityTable rows={data.items} showEmail />}
      {data && (
        <Pager page={data.page} totalPages={data.total_pages} total={data.total} noun="entries"
               onPage={(p) => update({ page: String(p) })} />
      )}
    </div>
  );
};
