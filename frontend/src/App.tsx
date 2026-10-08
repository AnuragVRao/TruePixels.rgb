import React, { Suspense, lazy, useCallback } from 'react';
import { BrowserRouter, Link, Route, Routes, useNavigate } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import { Layout, RequireAuth } from './components/Layout';
import { useAuth } from './context/AuthContext';
import { LandingPage } from './pages/LandingPage';
import { AdminLoginPage, ForgotPasswordPage, LoginPage, RegisterPage, VerifyOtpPage } from './pages/AuthPages';
import { AccountPage } from './pages/AccountPage';
import { UploadPage } from './pages/UploadPage';
import { ResultsPage } from './pages/ResultsPage';
import { HistoryPage } from './pages/HistoryPage';
import { VerificationPage } from './pages/VerificationPage';
import { AdminLayout } from './pages/admin/AdminLayout';

// Admin screens (and recharts) load only when an admin opens them.
const OverviewPage = lazy(() => import('./pages/admin/OverviewPage').then((m) => ({ default: m.OverviewPage })));
const LogsPage = lazy(() => import('./pages/admin/LogsPage').then((m) => ({ default: m.LogsPage })));
const UsersPage = lazy(() => import('./pages/admin/UsersPage').then((m) => ({ default: m.UsersPage })));
const LoginActivityPage = lazy(() => import('./pages/admin/LoginActivityPage').then((m) => ({ default: m.LoginActivityPage })));
const ModelsPage = lazy(() => import('./pages/admin/ModelsPage').then((m) => ({ default: m.ModelsPage })));
const loadingAdmin = <p className="text-muted-foreground text-sm">Loading…</p>;

const NotFound: React.FC = () => (
  <div className="text-center space-y-3 py-16">
    <p className="text-foreground/80">That page does not exist.</p>
    <Link className="text-primary hover:underline" to="/">Go to the start page</Link>
  </div>
);

/** "/" - the landing page when signed out (as in M1), the analyse page when signed in. */
const Home: React.FC = () => {
  const { isAuthenticated, loading } = useAuth();
  if (loading) return <p className="text-muted-foreground text-sm">Checking your session…</p>;
  return isAuthenticated ? <UploadPage /> : <LandingPage />;
};

const Routed: React.FC = () => {
  const navigate = useNavigate();
  // Any 401 from the API: the session is gone - back to sign-in, then here again.
  const onExpired = useCallback(() => {
    const here = window.location.pathname + window.location.search;
    // Admin screens send an expired admin back to the Administrator Portal.
    const portal = window.location.pathname.startsWith('/admin') ? '/admin/login' : '/login';
    navigate(`${portal}?expired=1&next=${encodeURIComponent(here)}`, { replace: true });
  }, [navigate]);

  return (
    <AuthProvider onExpired={onExpired}>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Home />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/admin/login" element={<AdminLoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/verify" element={<VerifyOtpPage />} />
          <Route path="/forgot-password" element={<ForgotPasswordPage />} />
          <Route element={<RequireAuth />}>
            <Route path="/results/:id" element={<ResultsPage />} />
            <Route path="/history" element={<HistoryPage />} />
            <Route path="/verification" element={<VerificationPage />} />
            <Route path="/account" element={<AccountPage />} />
          </Route>
          <Route path="/admin" element={<AdminLayout />}>
            <Route index element={<Suspense fallback={loadingAdmin}><OverviewPage /></Suspense>} />
            <Route path="logs" element={<Suspense fallback={loadingAdmin}><LogsPage /></Suspense>} />
            <Route path="users" element={<Suspense fallback={loadingAdmin}><UsersPage /></Suspense>} />
            <Route path="login-activity" element={<Suspense fallback={loadingAdmin}><LoginActivityPage /></Suspense>} />
            <Route path="models" element={<Suspense fallback={loadingAdmin}><ModelsPage /></Suspense>} />
          </Route>
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </AuthProvider>
  );
};

export function App() {
  return (
    <BrowserRouter>
      <Routed />
    </BrowserRouter>
  );
}

export default App;
