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
    return <Navigate to={`/admin/login?next=${encodeURIComponent(location.pathname + location.search)}`} replace />;
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
        <NavLink to="/admin/login-activity" className={tab}>Login Activity</NavLink>
        <NavLink to="/admin/models" className={tab}>Models</NavLink>
      </nav>
      <Outlet />
    </div>
  );
};

// Moved to components/ConfirmDialog (shared with the Sign Out confirmation).
export { ConfirmDialog } from '../../components/ConfirmDialog';

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
