import React, { useCallback } from 'react';
import { BrowserRouter, Link, Route, Routes, useNavigate } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import { Layout, RequireAuth } from './components/Layout';
import { LoginPage, RegisterPage, VerifyOtpPage } from './pages/AuthPages';
import { UploadPage } from './pages/UploadPage';
import { ResultsPage } from './pages/ResultsPage';
import { HistoryPage } from './pages/HistoryPage';

const NotFound: React.FC = () => (
  <div className="text-center space-y-3 py-16">
    <p className="text-slate-300">That page does not exist.</p>
    <Link className="text-indigo-400 hover:underline" to="/">Go to the start page</Link>
  </div>
);

const Routed: React.FC = () => {
  const navigate = useNavigate();
  // Any 401 from the API: the session is gone - back to sign-in, then here again.
  const onExpired = useCallback(() => {
    const here = window.location.pathname + window.location.search;
    navigate(`/login?expired=1&next=${encodeURIComponent(here)}`, { replace: true });
  }, [navigate]);

  return (
    <AuthProvider onExpired={onExpired}>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/verify" element={<VerifyOtpPage />} />
          <Route element={<RequireAuth />}>
            <Route path="/" element={<UploadPage />} />
            <Route path="/results/:id" element={<ResultsPage />} />
            <Route path="/history" element={<HistoryPage />} />
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
