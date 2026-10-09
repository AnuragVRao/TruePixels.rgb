import React, { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { History, KeyRound, Loader2 } from 'lucide-react';
import { apiRequest, postJson } from '../api/client';
import type { LoginResponse, PaginatedLoginEvents } from '../api/types';
import { useAuth } from '../context/AuthContext';
import { ErrorNotice, Notice } from '../components/Feedback';
import { LoginActivityTable } from '../components/LoginActivityTable';
import { PasswordInput } from '../components/PasswordInput';
import { PasswordRules, passwordOk } from '../components/PasswordRules';
import { Pager } from './admin/AdminLayout';

const PAGE_SIZE = 15;
const field =
  'w-full rounded-lg bg-card border border-border px-3 py-2.5 text-sm text-foreground placeholder-muted-foreground/60 ' +
  'focus:outline-none focus:ring-2 focus:ring-ring';

/**
 * Change password: the server ends every other session and returns a new
 * token for this one, so this tab stays signed in.
 */
const ChangePassword: React.FC<{ onChanged: () => void }> = ({ onChanged }) => {
  const { signIn } = useAuth();
  const [current, setCurrent] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const mismatch = confirm.length > 0 && confirm !== password;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setDone(false);
    try {
      const res = await postJson<LoginResponse>('/auth/password/change',
        { current_password: current, new_password: password });
      await signIn(res.token);
      setCurrent('');
      setPassword('');
      setConfirm('');
      setDone(true);
      onChanged();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="max-w-md rounded-2xl border border-border bg-card p-6 space-y-4">
      <h2 className="flex items-center gap-2 text-lg font-semibold text-foreground">
        <KeyRound className="w-5 h-5 text-primary" /> Change password
      </h2>
      {done && (
        <Notice tone="success" title="Password changed.">
          You stay signed in here. Every other session of this account was signed out.
        </Notice>
      )}
      <ErrorNotice error={error} />
      <form onSubmit={submit} className="space-y-4" aria-label="Change password">
        <label className="block space-y-1.5 text-sm">
          <span className="text-foreground/80">Current password</span>
          <PasswordInput className={field} autoComplete="current-password" required value={current}
                 onChange={(e) => setCurrent(e.target.value)} />
        </label>
        <label className="block space-y-1.5 text-sm">
          <span className="text-foreground/80">New password</span>
          <PasswordInput className={field} autoComplete="new-password" required value={password}
                 onChange={(e) => setPassword(e.target.value)} />
        </label>
        <label className="block space-y-1.5 text-sm">
          <span className="text-foreground/80">Confirm new password</span>
          <PasswordInput className={field} autoComplete="new-password" required value={confirm}
                 onChange={(e) => setConfirm(e.target.value)} />
        </label>
        <PasswordRules password={password} />
        {mismatch && <p className="text-xs text-rose-700 dark:text-rose-300">The two passwords do not match.</p>}
        <button type="submit" disabled={busy || !current || !passwordOk(password) || confirm !== password}
                className="w-full flex items-center justify-center gap-2 rounded-lg bg-primary hover:bg-primary/90 disabled:opacity-50 px-4 py-2.5 text-sm font-semibold text-primary-foreground">
          {busy && <Loader2 className="w-4 h-4 animate-spin" />} Change password
        </button>
      </form>
    </section>
  );
};

export const AccountPage: React.FC = () => {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const page = Math.max(1, Number(params.get('page')) || 1);
  const [data, setData] = useState<PaginatedLoginEvents | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    apiRequest<PaginatedLoginEvents>(`/users/me/login-activity?page=${page}&page_size=${PAGE_SIZE}`,
      { signal: controller.signal })
      .then(setData)
      .catch((err) => { if ((err as Error).name !== 'AbortError') setError(err); });
    return () => controller.abort();
  }, [page, reload]);

  return (
    <div className="max-w-6xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-foreground">Account</h1>
        <p className="text-sm text-muted-foreground mt-1">{user?.email}</p>
      </div>

      {/* Stacked, not side by side: beside the form the table was too narrow and scrolled sideways. */}
      <div className="space-y-8">
        <ChangePassword onChanged={() => setReload((n) => n + 1)} />

        <section className="space-y-4 min-w-0">
          <h2 className="flex items-center gap-2 text-lg font-semibold text-foreground">
            <History className="w-5 h-5 text-primary" /> Login activity
          </h2>
          <p className="text-xs text-muted-foreground/80">
            Every sign-in to this account and every password change, newest first, kept for 90 days. If you see one
            you do not recognise, change your password.
          </p>
          <ErrorNotice error={error} />
          {!data && !error && (
            <p className="text-muted-foreground text-sm flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" /> Loading…</p>
          )}
          {data && data.total === 0 && <Notice tone="info" title="No sign-ins recorded yet." />}
          {data && data.items.length > 0 && <LoginActivityTable rows={data.items} />}
          {data && (
            <Pager page={data.page} totalPages={data.total_pages} total={data.total} noun="entries"
                   onPage={(p) => setParams(p > 1 ? { page: String(p) } : {})} />
          )}
        </section>
      </div>
    </div>
  );
};
