import React from 'react';
import { Link, NavLink, Navigate, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { History, LogOut, ScanSearch, Settings, ShieldCheck } from 'lucide-react';
import { useAuth } from '../context/AuthContext';

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm transition-colors ${
    isActive ? 'bg-slate-800 text-white' : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
  }`;

export const Layout: React.FC = () => {
  const { user, signOut } = useAuth();
  const navigate = useNavigate();

  return (
    <div className="min-h-screen flex flex-col bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 bg-slate-950/90 sticky top-0 z-30 backdrop-blur">
        <div className="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between gap-3">
          <Link to="/" className="flex items-center gap-2 font-bold text-white shrink-0">
            <ShieldCheck className="w-5 h-5 text-indigo-400" />
            <span>TruePixels.rgb</span>
          </Link>
          {user && (
            <nav className="flex items-center gap-1 overflow-x-auto" aria-label="Main">
              <NavLink to="/" end className={linkClass}>
                <ScanSearch className="w-4 h-4" /> <span className="hidden sm:inline">Analyse</span>
              </NavLink>
              <NavLink to="/history" className={linkClass}>
                <History className="w-4 h-4" /> <span className="hidden sm:inline">History</span>
              </NavLink>
              {user.role === 'Admin' && (
                <NavLink to="/admin" className={linkClass}>
                  <Settings className="w-4 h-4" /> <span className="hidden sm:inline">Admin</span>
                </NavLink>
              )}
              <span className="hidden md:inline text-xs text-slate-500 px-2 truncate max-w-[14rem]">
                {user.email}
                {user.role === 'Admin' ? ' (Admin)' : ''}
              </span>
              <button
                type="button"
                onClick={async () => {
                  await signOut();
                  navigate('/login');
                }}
                className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm text-slate-400 hover:text-white hover:bg-slate-800/60"
              >
                <LogOut className="w-4 h-4" /> <span className="hidden sm:inline">Sign out</span>
              </button>
            </nav>
          )}
        </div>
      </header>
      <main className="flex-1 w-full max-w-6xl mx-auto px-4 py-8">
        <Outlet />
      </main>
      <footer className="border-t border-slate-800 py-5 text-center text-xs text-slate-500 px-4">
        TruePixels.rgb flags likely AI-generated images. A result is a model's estimate, not proof.
      </footer>
    </div>
  );
};

/** Routes below require a session; otherwise go to /login and come back afterwards. */
export const RequireAuth: React.FC = () => {
  const { isAuthenticated, loading } = useAuth();
  const location = useLocation();
  if (loading) return <p className="text-slate-400 text-sm">Checking your session…</p>;
  if (!isAuthenticated) {
    return <Navigate to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`} replace />;
  }
  return <Outlet />;
};
