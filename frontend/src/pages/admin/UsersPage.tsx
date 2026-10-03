import React, { useCallback, useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { apiRequest } from '../../api/client';
import type { AdminUser } from '../../api/adminTypes';
import { useAuth } from '../../context/AuthContext';
import { ErrorNotice, Notice } from '../../components/Feedback';
import { ConfirmDialog, Pager, when } from './AdminLayout';

const PAGE_SIZE = 20;
type Action = 'enable' | 'disable' | 'remove';

const STATUS_TONE: Record<string, string> = {
  active: 'text-emerald-300', disabled: 'text-amber-300', removed: 'text-rose-300',
};

/**
 * What each action does - this wording must match the backend
 * (app/m1_access/account_policy.py). Nothing is deleted by any of them.
 */
const EXPLAIN: Record<Action, { title: string; button: string; body: React.ReactNode }> = {
  disable: {
    title: 'Disable this account?',
    button: 'Disable account',
    body: (
      <>
        <p>They are refused at sign-in, and any session they have open stops working on its next request.</p>
        <p>Their images, results, explainability panels and stored files are <strong>kept unchanged</strong>.
          Enabling the account later restores everything.</p>
      </>
    ),
  },
  remove: {
    title: 'Mark this account as removed?',
    button: 'Mark as removed',
    body: (
      <>
        <p>This is <strong>not a deletion</strong>. It blocks sign-in and open sessions exactly like disabling;
          only the recorded status differs.</p>
        <p>Their images, results, explainability panels and stored files are <strong>kept unchanged</strong> -
          nothing is erased and no files are orphaned. Enabling the account restores everything.</p>
      </>
    ),
  },
  enable: {
    title: 'Enable this account?',
    button: 'Enable account',
    body: <p>They can sign in again and see all of their earlier results.</p>,
  },
};

/** Account metadata only - an administrator never sees a user's images (owner-only by design). */
export const UsersPage: React.FC = () => {
  const { user: me } = useAuth();
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [page, setPage] = useState(1);
  const [pending, setPending] = useState<{ target: AdminUser; action: Action } | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<unknown>(null);
  const [done, setDone] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      setUsers(await apiRequest<AdminUser[]>('/admin/users', { signal }));
    } catch (err) {
      if ((err as Error).name !== 'AbortError') setError(err);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const confirm = async () => {
    if (!pending) return;
    setBusy(true);
    setActionError(null);
    try {
      const res = await apiRequest<{ user_id: number; account_status: string }>(
        `/admin/users/${pending.target.user_id}/status`,
        { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: pending.action }) },
      );
      setDone(`${pending.target.email} is now ${res.account_status}.`);
      setPending(null);
      await load();
    } catch (err) {
      setActionError(err);
    } finally {
      setBusy(false);
    }
  };

  const totalPages = users ? Math.max(1, Math.ceil(users.length / PAGE_SIZE)) : 1;
  const shown = users ? users.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE) : [];

  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-bold text-white">Users</h1>
      <p className="text-sm text-slate-400">
        Account details only. Administrators cannot open users&apos; images or results. You cannot change your own
        account, and the server refuses any change that would leave no active administrator.
      </p>
      <ErrorNotice error={error} />
      {done && <Notice tone="success" title={done} />}
      {!users && !error && (
        <p className="text-slate-400 text-sm flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" /> Loading…</p>
      )}
      {users && users.length === 0 && <Notice tone="info" title="No registered users." />}
      {users && users.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-slate-800">
          <table className="w-full text-sm">
            <thead className="bg-slate-900 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-3 py-2">#</th>
                <th className="px-3 py-2">Name / email</th>
                <th className="px-3 py-2">Role</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Registered</th>
                <th className="px-3 py-2">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {shown.map((u) => {
                const self = me?.user_id === u.user_id;
                return (
                  <tr key={u.user_id} data-testid={`user-${u.user_id}`}>
                    <td className="px-3 py-2 font-mono text-slate-500">{u.user_id}</td>
                    <td className="px-3 py-2">
                      <p className="text-slate-100">{u.full_name}{self && <span className="text-slate-500"> (you)</span>}</p>
                      <p className="text-xs text-slate-400 break-all">{u.email}</p>
                    </td>
                    <td className="px-3 py-2 text-slate-300">{u.role}</td>
                    <td className={`px-3 py-2 ${STATUS_TONE[u.account_status] ?? ''}`}>{u.account_status}</td>
                    <td className="px-3 py-2 text-slate-400 whitespace-nowrap">{when(u.registered_at)}</td>
                    <td className="px-3 py-2">
                      {self ? <span className="text-xs text-slate-500">—</span> : (
                        <div className="flex flex-wrap gap-2">
                          {u.account_status !== 'active' && (
                            <button type="button" className="text-xs px-2 py-1 rounded border border-emerald-700 text-emerald-300"
                                    onClick={() => { setActionError(null); setDone(null); setPending({ target: u, action: 'enable' }); }}>Enable</button>
                          )}
                          {u.account_status === 'active' && (
                            <button type="button" className="text-xs px-2 py-1 rounded border border-amber-700 text-amber-300"
                                    onClick={() => { setActionError(null); setDone(null); setPending({ target: u, action: 'disable' }); }}>Disable</button>
                          )}
                          {u.account_status !== 'removed' && (
                            <button type="button" className="text-xs px-2 py-1 rounded border border-rose-800 text-rose-300"
                                    onClick={() => { setActionError(null); setDone(null); setPending({ target: u, action: 'remove' }); }}>Remove</button>
                          )}
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {users && <Pager page={page} totalPages={totalPages} total={users.length} noun="users" onPage={setPage} />}

      {pending && (
        <ConfirmDialog title={EXPLAIN[pending.action].title} confirmLabel={EXPLAIN[pending.action].button}
                       danger={pending.action !== 'enable'} busy={busy} onConfirm={confirm}
                       onCancel={() => { setPending(null); setActionError(null); }}>
          <p className="text-white">{pending.target.full_name} · {pending.target.email} ({pending.target.role})</p>
          {EXPLAIN[pending.action].body}
          <ErrorNotice error={actionError} />
        </ConfirmDialog>
      )}
    </div>
  );
};
