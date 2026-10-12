import React, { useState } from 'react';
import { Link, NavLink, Navigate, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { BarChart3, CheckCircle, Clock, LogOut, ScanSearch, ShieldAlert, ShieldCheck, UserCog } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { ConfirmDialog } from './ConfirmDialog';
import { CONTACT_EMAIL } from '../lib/contact';
import { formatDate } from '../lib/format';
import { AccessibilityControls } from './AccessibilityControls';

/**
 * The DBIM "Header 3" (§5.4.3) for an organisation that may not use the State
 * Emblem: skip link, Lockup 3B (own mark, name, tagline - no emblem, no
 * Government of India text: TruePixels is not a government body), user
 * controls (accessibility, account) and the global navigation. Signed in:
 * the numbered tabs of M3's original dashboard (admins also see Admin
 * Dashboard & Analytics and 1-Click Verification). Signed out: M1's three
 * entry points. The footer is in the key colour of the Blue group (§5.6).
 */
const tabClass = (active: boolean) =>
  `flex items-center gap-2 px-3 py-2.5 text-sm font-semibold whitespace-nowrap border-b-[3px] transition-colors ${
    active ? 'border-primary text-primary' : 'border-transparent text-foreground hover:text-primary hover:border-primary/40'
  }`;

const Tabs: React.FC<{ isAdmin: boolean }> = ({ isAdmin }) => {
  const { pathname } = useLocation();
  const forensic = pathname === '/' || pathname.startsWith('/results/');
  return (
    <nav className="border-t border-border" aria-label="Main">
      <div className="max-w-6xl mx-auto px-4 flex gap-2 overflow-x-auto">
        <NavLink to="/" className={() => tabClass(forensic)}>
          <ScanSearch className="w-5 h-5" aria-hidden="true" /> 1. Forensic Detection
        </NavLink>
        <NavLink to="/history" className={({ isActive }) => tabClass(isActive)}>
          <Clock className="w-5 h-5" aria-hidden="true" /> 2. User Scan History
        </NavLink>
        {/* Admins only: a User never sees these tabs (the pages and the API still enforce the role). */}
        {isAdmin && (
          <>
            <NavLink to="/admin" className={({ isActive }) => tabClass(isActive && pathname !== '/admin/login')}>
              <BarChart3 className="w-5 h-5" aria-hidden="true" /> 3. Admin Dashboard &amp; Analytics
            </NavLink>
            <NavLink to="/verification" className={({ isActive }) => tabClass(isActive)}>
              <CheckCircle className="w-5 h-5" aria-hidden="true" /> 4. 1-Click Verification
            </NavLink>
          </>
        )}
      </div>
    </nav>
  );
};

/** Footer links: only pages that exist (DBIM §5.6 asks for more; the rest are recorded as not built). */
const FooterLinks: React.FC<{ signedIn: boolean }> = ({ signedIn }) => {
  const link = 'hover:underline';
  return (
    <nav aria-label="Useful links">
      <p className="text-xs font-semibold mb-2">Useful links</p>
      <ul className="grid grid-cols-2 sm:flex sm:flex-wrap gap-x-6 gap-y-1 text-sm">
        {signedIn ? (
          <>
            <li><Link to="/" className={link}>› Analyse an image</Link></li>
            <li><Link to="/history" className={link}>› Scan history</Link></li>
            <li><Link to="/account" className={link}>› Account</Link></li>
          </>
        ) : (
          <>
            <li><Link to="/login" className={link}>› Sign in</Link></li>
            <li><Link to="/register" className={link}>› Create account</Link></li>
            <li><Link to="/forgot-password" className={link}>› Forgot password</Link></li>
          </>
        )}
        <li><Link to="/faq" className={link}>› FAQ</Link></li>
        <li><a href={`mailto:${CONTACT_EMAIL}`} className={link} title={CONTACT_EMAIL}>› Contact us</a></li>
      </ul>
    </nav>
  );
};

export const Layout: React.FC = () => {
  const { user, signOut } = useAuth();
  const navigate = useNavigate();
  const [confirmSignOut, setConfirmSignOut] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const isAdmin = user?.role === 'Admin';

  return (
    <div className="min-h-screen flex flex-col bg-background text-foreground">
      <a href="#main" className="skip-link">Skip to main content</a>
      <header className="border-b border-border bg-background sm:sticky sm:top-0 z-30">
        <div className="max-w-6xl mx-auto px-4 py-2 min-h-16 flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
          {/* Lockup 3B: the organisation's own mark and name, with a tagline. */}
          <Link to="/" className="flex items-center gap-2.5 shrink-0" aria-label="TruePixels.rgb home">
            <ShieldCheck className="w-8 h-8 text-primary" aria-hidden="true" />
            <span className="flex flex-col leading-tight">
              <span className="text-base font-bold text-primary whitespace-nowrap">TruePixels.rgb</span>
              <span className="text-xs text-muted-foreground hidden sm:block">AI-generated image detection</span>
            </span>
          </Link>
          <div className="flex items-center gap-2 min-w-0 ml-auto">
            <AccessibilityControls />
            {!user && (
              /* Signed out: M1's three entry points - each its own page. */
              <nav className="flex items-center gap-2" aria-label="Account">
                <NavLink to="/admin/login" title="Admin login" className="btn-secondary px-3">
                  <ShieldAlert className="w-5 h-5" aria-hidden="true" /> <span className="hidden sm:inline">Admin Login</span>
                </NavLink>
                <NavLink to="/login" className="btn-secondary px-3 whitespace-nowrap">Sign In</NavLink>
                <NavLink to="/register" className="btn-primary px-3 whitespace-nowrap">Create Account</NavLink>
              </nav>
            )}
            {user && (
              <div className="flex items-center gap-2 min-w-0">
                <Link to="/account" title="Account: change password, login activity"
                      className="flex items-center gap-2 px-3 py-2 rounded-md bg-card border border-border hover:border-primary hover:bg-accent text-sm text-foreground min-w-0">
                  <UserCog className="w-5 h-5 shrink-0 text-primary" aria-hidden="true" />
                  <span className="truncate hidden sm:inline max-w-[14rem]">{user.email}</span>
                  <span className={`text-xs font-semibold px-1.5 py-0.5 rounded ${
                    isAdmin ? 'bg-warning text-warning-foreground' : 'bg-muted text-muted-foreground'}`}>
                    {user.role}
                  </span>
                </Link>
                <button type="button" onClick={() => setConfirmSignOut(true)} title="Sign out" className="btn-secondary px-3">
                  <LogOut className="w-5 h-5" aria-hidden="true" /> <span className="hidden sm:inline">Sign Out</span>
                </button>
              </div>
            )}
          </div>
        </div>
        {user && <Tabs isAdmin={isAdmin} />}
      </header>
      <main id="main" tabIndex={-1} className="flex-1 w-full max-w-6xl mx-auto px-4 py-5 sm:py-8 focus:outline-none">
        <Outlet />
      </main>
      <footer className="bg-footer text-footer-foreground">
        <div className="max-w-6xl mx-auto px-4 py-6 flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4">
          <div className="space-y-3">
            <FooterLinks signedIn={!!user} />
            <p className="text-xs">&copy; {new Date().getFullYear()} TruePixels.rgb. All rights reserved. A result is a model&apos;s estimate, not proof.</p>
          </div>
          <p className="text-xs whitespace-nowrap">Last updated on: {formatDate(__BUILD_DATE__)}</p>
        </div>
      </footer>

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
