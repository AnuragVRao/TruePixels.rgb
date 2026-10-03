import React from 'react';
import { NavLink, Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { Notice } from '../../components/Feedback';

const tab = ({ isActive }: { isActive: boolean }) =>
  `px-3 py-1.5 rounded-lg text-sm whitespace-nowrap ${
    isActive ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
  }`;

/**
 * Admin area: signed in AND role Admin. This guard is convenience only - every
 * /admin and /models endpoint enforces the role itself (403 AUTH_FORBIDDEN).
 * Admin screens show metadata only; no user's images are ever fetched here.
 */
export const AdminLayout: React.FC = () => {
  const { isAuthenticated, isAdmin, loading } = useAuth();
  const location = useLocation();
  if (loading) return <p className="text-slate-400 text-sm">Checking your session…</p>;
  if (!isAuthenticated) {
    return <Navigate to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`} replace />;
  }
  if (!isAdmin) {
    return (
      <Notice tone="error" title="Administrators only.">
        This area needs an administrator account. Your own results are under History.
      </Notice>
    );
  }
  return (
    <div className="space-y-6">
      <nav className="flex gap-1 overflow-x-auto border-b border-slate-800 pb-3" aria-label="Administration">
        <NavLink to="/admin" end className={tab}>Overview</NavLink>
        <NavLink to="/admin/logs" className={tab}>Logs</NavLink>
        <NavLink to="/admin/users" className={tab}>Users</NavLink>
        <NavLink to="/admin/models" className={tab}>Models</NavLink>
      </nav>
      <Outlet />
    </div>
  );
};

/** A modal confirmation. `children` explains exactly what will happen. */
export const ConfirmDialog: React.FC<{
  title: string;
  confirmLabel: string;
  danger?: boolean;
  busy?: boolean;
  canConfirm?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  children: React.ReactNode;
}> = ({ title, confirmLabel, danger, busy, canConfirm = true, onConfirm, onCancel, children }) => (
  <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="dialog" aria-modal="true"
       aria-labelledby="confirm-title">
    <div className="w-full max-w-lg rounded-2xl border border-slate-700 bg-slate-900 p-6 space-y-4">
      <h2 id="confirm-title" className="text-lg font-semibold text-white">{title}</h2>
      <div className="text-sm text-slate-300 space-y-2">{children}</div>
      <div className="flex justify-end gap-2">
        <button type="button" onClick={onCancel} disabled={busy}
                className="px-4 py-2 rounded-lg border border-slate-700 text-sm text-slate-200">Cancel</button>
        <button type="button" onClick={onConfirm} disabled={busy || !canConfirm}
                className={`px-4 py-2 rounded-lg text-sm font-semibold text-white disabled:opacity-40 ${
                  danger ? 'bg-rose-700 hover:bg-rose-600' : 'bg-indigo-600 hover:bg-indigo-500'}`}>
          {confirmLabel}
        </button>
      </div>
    </div>
  </div>
);

export const Pager: React.FC<{ page: number; totalPages: number; total: number; noun: string;
  onPage: (page: number) => void }> = ({ page, totalPages, total, noun, onPage }) =>
  totalPages > 1 ? (
    <nav className="flex items-center justify-between text-sm" aria-label="Pagination">
      <button type="button" disabled={page <= 1} onClick={() => onPage(page - 1)}
              className="px-3 py-1.5 rounded-lg border border-slate-700 disabled:opacity-40">Previous</button>
      <span className="text-slate-400">Page {page} of {totalPages} · {total} {noun}</span>
      <button type="button" disabled={page >= totalPages} onClick={() => onPage(page + 1)}
              className="px-3 py-1.5 rounded-lg border border-slate-700 disabled:opacity-40">Next</button>
    </nav>
  ) : null;

export function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : '—';
}
