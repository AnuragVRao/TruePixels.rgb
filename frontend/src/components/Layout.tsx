import React, { useState } from 'react';
import { Link, NavLink, Navigate, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { BarChart3, CheckCircle, Clock, Lock, LogOut, ScanSearch, ShieldAlert, ShieldCheck, UserCog } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { ConfirmDialog } from './ConfirmDialog';
import { ThemeToggle } from './ThemeToggle';

/**
 * Signed in: the four numbered tabs of M3's original dashboard (Forensic
 * Detection, User Scan History, Admin Dashboard & Analytics, 1-Click
 * Verification) and its header (email, role badge, Sign Out with a
 * confirmation). Signed out: M1's three entry points.
 */
const tabClass = (active: boolean) =>
  `flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap transition-colors ${
    active ? 'bg-primary text-primary-foreground shadow-md shadow-primary/30' : 'text-foreground/80 hover:text-foreground hover:bg-muted'
  }`;

const Tabs: React.FC<{ isAdmin: boolean }> = ({ isAdmin }) => {
  const { pathname } = useLocation();
  const forensic = pathname === '/' || pathname.startsWith('/results/');
  return (
    <nav className="max-w-6xl mx-auto px-4 pb-2 flex gap-1.5 overflow-x-auto" aria-label="Main">
      <NavLink to="/" className={() => tabClass(forensic)}>
        <ScanSearch className="w-4 h-4" /> 1. Forensic Detection
      </NavLink>
      <NavLink to="/history" className={({ isActive }) => tabClass(isActive)}>
        <Clock className="w-4 h-4" /> 2. User Scan History
      </NavLink>
      <NavLink to="/admin" className={({ isActive }) => tabClass(isActive && pathname !== '/admin/login')}
               title={isAdmin ? undefined : 'Administrators only'}>
        {isAdmin ? <BarChart3 className="w-4 h-4" /> : <Lock className="w-4 h-4" />} 3. Admin Dashboard &amp; Analytics
      </NavLink>
      <NavLink to="/verification" className={({ isActive }) => tabClass(isActive)}>
        <CheckCircle className="w-4 h-4" /> 4. 1-Click Verification
      </NavLink>
    </nav>
  );
};

export const Layout: React.FC = () => {
  const { user, signOut } = useAuth();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [confirmSignOut, setConfirmSignOut] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const isAdmin = user?.role === 'Admin';

  return (
    <div className="min-h-screen flex flex-col bg-background text-foreground">
      <header className="border-b border-border bg-background/90 sticky top-0 z-30 backdrop-blur">
        <div className="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between gap-3">
          <Link to="/" className="flex items-center gap-2 font-bold text-foreground shrink-0">
            <ShieldCheck className="w-5 h-5 text-primary" />
            <span>TruePixels.rgb</span>
          </Link>
          <div className="flex items-center gap-2 min-w-0">
          <ThemeToggle />
          {!user && (
            /* Signed out: M1's three entry points - each its own page. */
            <nav className="flex items-center gap-2" aria-label="Account">
              <NavLink to="/admin/login"
                       className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium text-amber-700 dark:text-amber-400 hover:text-amber-700 dark:hover:text-amber-300 hover:bg-amber-50 dark:hover:bg-amber-950/40 border border-amber-300 dark:border-amber-900/40">
                <ShieldAlert className="w-3.5 h-3.5" /> <span className="hidden sm:inline">Admin Login</span>
              </NavLink>
              <NavLink to="/login"
                       className="px-3.5 py-1.5 rounded-xl text-xs font-medium text-foreground hover:text-foreground hover:bg-card border border-border">
                Sign In
              </NavLink>
              <NavLink to="/register"
                       className="px-4 py-1.5 rounded-xl text-xs font-semibold text-primary-foreground bg-primary hover:bg-primary/90 shadow-md shadow-primary/30">
                Create Account
              </NavLink>
            </nav>
          )}
          {user && (
            <div className="flex items-center gap-2 min-w-0">
              <Link to="/account" title="Account: change password, login activity"
                    className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-card border border-border hover:border-primary text-xs text-foreground/80 min-w-0">
                <UserCog className="w-3.5 h-3.5 shrink-0 text-muted-foreground" />
                <span className={`w-2 h-2 rounded-full shrink-0 ${isAdmin ? 'bg-amber-400' : 'bg-emerald-400'}`} />
                <span className="truncate hidden sm:inline max-w-[14rem]">{user.email}</span>
                <span className={`text-[10px] font-bold uppercase px-1.5 py-0.5 rounded-md ${
                  isAdmin ? 'bg-amber-500/20 text-amber-700 dark:text-amber-300 border border-amber-500/30' : 'bg-muted text-muted-foreground'}`}>
                  {user.role}
                </span>
              </Link>
              <button
                type="button"
                onClick={() => setConfirmSignOut(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs text-foreground/80 hover:text-foreground bg-muted hover:bg-muted/70 border border-border"
              >
                <LogOut className="w-3.5 h-3.5" /> <span className="hidden sm:inline">Sign Out</span>
              </button>
            </div>
          )}
          </div>
        </div>
        {user && <Tabs isAdmin={isAdmin} />}
      </header>
      <main className="flex-1 w-full max-w-6xl mx-auto px-4 py-8">
        <Outlet />
      </main>
      {user || pathname !== '/' ? (
        <footer className="border-t border-border py-5 px-6 flex flex-col items-center gap-1 text-center text-xs text-muted-foreground/80">
          <span>&copy; {new Date().getFullYear()} TruePixels.rgb. All rights reserved.</span>
          <span>A result is a model&apos;s estimate, not proof.</span>
        </footer>
      ) : (
        <footer className="relative z-10 py-5 px-6 text-center text-xs text-muted-foreground">
          &copy; {new Date().getFullYear()} TruePixels.rgb. All rights reserved.
        </footer>
      )}

      {confirmSignOut && (
        <ConfirmDialog title="Sign out?" confirmLabel="Yes, sign out" busy={signingOut}
                       onCancel={() => setConfirmSignOut(false)}
                       onConfirm={async () => {
                         setSigningOut(true);
                         await signOut();
                         setSigningOut(false);
                         setConfirmSignOut(false);
                         navigate('/');  // back to the landing page, as in M1
                       }}>
          <p>Your session ends on this device. Your results stay saved and are there when you sign in again.</p>
        </ConfirmDialog>
      )}
    </div>
  );
};

/** Routes below require a session; otherwise go to /login and come back afterwards. */
export const RequireAuth: React.FC = () => {
  const { isAuthenticated, loading } = useAuth();
  const location = useLocation();
  if (loading) return <p className="text-muted-foreground text-sm">Checking your session…</p>;
  if (!isAuthenticated) {
    return <Navigate to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`} replace />;
  }
  return <Outlet />;
};
