import React, { useState } from 'react';
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import { postJson } from '../api/client';
import type { LoginResponse, OtpVerifyResponse, RegisterResponse } from '../api/types';
import { useAuth } from '../context/AuthContext';
import { ErrorNotice, Notice } from '../components/Feedback';

const field =
  'w-full rounded-lg bg-slate-900 border border-slate-700 px-3 py-2.5 text-sm text-white placeholder-slate-500 ' +
  'focus:outline-none focus:ring-2 focus:ring-indigo-500';
const button =
  'w-full flex items-center justify-center gap-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 ' +
  'px-4 py-2.5 text-sm font-semibold text-white';

const Card: React.FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => (
  <div className="max-w-md mx-auto bg-slate-900/60 border border-slate-800 rounded-2xl p-6 sm:p-8 space-y-5">
    <h1 className="text-xl font-bold text-white">{title}</h1>
    {children}
  </div>
);

/**
 * Where to go after signing in: a same-origin relative path, or '/'.
 *
 * Rejects absolute URLs ("https://evil.example"), protocol-relative ones
 * ("//evil.example") and backslash variants ("/\evil.example", which browsers
 * treat like "//"), then confirms the resolved URL stays on this origin.
 */
export function safeNext(raw: string | null): string {
  if (!raw || !raw.startsWith('/') || raw.startsWith('//') || raw.includes('\\')) return '/';
  try {
    const resolved = new URL(raw, window.location.origin);
    if (resolved.origin !== window.location.origin) return '/';
    return resolved.pathname + resolved.search + resolved.hash;
  } catch {
    return '/';
  }
}

function useNext(): string {
  const [params] = useSearchParams();
  return safeNext(params.get('next'));
}

export const LoginPage: React.FC = () => {
  const { signIn, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const next = useNext();
  const location = useLocation();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [asAdmin, setAsAdmin] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const expired = new URLSearchParams(location.search).get('expired') === '1';

  if (isAuthenticated) return <Navigate to={next} replace />;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = { email: email.trim().toLowerCase(), password };
      const res = await postJson<LoginResponse>(asAdmin ? '/auth/admin/login' : '/auth/login', body);
      if (res.requires_otp) {
        navigate(`/verify?email=${encodeURIComponent(body.email)}&next=${encodeURIComponent(next)}`);
        return;
      }
      await signIn(res.token);
      navigate(next, { replace: true });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Sign in">
      {expired && <Notice tone="warning" title="Your session ended. Please sign in again." />}
      <ErrorNotice error={error} />
      <form onSubmit={submit} className="space-y-4" noValidate={false}>
        <label className="block space-y-1.5 text-sm">
          <span className="text-slate-300">Email</span>
          <input className={field} type="email" autoComplete="email" required value={email}
                 onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="block space-y-1.5 text-sm">
          <span className="text-slate-300">Password</span>
          <input className={field} type="password" autoComplete="current-password" required value={password}
                 onChange={(e) => setPassword(e.target.value)} />
        </label>
        <label className="flex items-center gap-2 text-sm text-slate-400">
          <input type="checkbox" checked={asAdmin} onChange={(e) => setAsAdmin(e.target.checked)} />
          Sign in as administrator
        </label>
        <button className={button} disabled={busy} type="submit">
          {busy && <Loader2 className="w-4 h-4 animate-spin" />} Sign in
        </button>
      </form>
      <p className="text-sm text-slate-400">
        No account? <Link className="text-indigo-400 hover:underline" to="/register">Create one</Link>
      </p>
    </Card>
  );
};

export const RegisterPage: React.FC = () => {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const rules = [
    { ok: password.length >= 10, text: 'at least 10 characters' },
    { ok: /[a-zA-Z]/.test(password), text: 'a letter' },
    { ok: /[0-9]/.test(password), text: 'a digit' },
  ];

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const cleanEmail = email.trim().toLowerCase();
    try {
      const res = await postJson<RegisterResponse>('/auth/register', {
        full_name: fullName.trim(),
        email: cleanEmail,
        password,
      });
      if (res.requires_2fa) {
        navigate(`/verify?email=${encodeURIComponent(cleanEmail)}`);
        return;
      }
      const login = await postJson<LoginResponse>('/auth/login', { email: cleanEmail, password });
      if (login.requires_otp) {
        navigate(`/verify?email=${encodeURIComponent(cleanEmail)}`);
        return;
      }
      await signIn(login.token);
      navigate('/', { replace: true });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Create an account">
      <ErrorNotice error={error} />
      <form onSubmit={submit} className="space-y-4">
        <label className="block space-y-1.5 text-sm">
          <span className="text-slate-300">Full name</span>
          <input className={field} autoComplete="name" required minLength={2} maxLength={120} value={fullName}
                 onChange={(e) => setFullName(e.target.value)} />
        </label>
        <label className="block space-y-1.5 text-sm">
          <span className="text-slate-300">Email</span>
          <input className={field} type="email" autoComplete="email" required value={email}
                 onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="block space-y-1.5 text-sm">
          <span className="text-slate-300">Password</span>
          <input className={field} type="password" autoComplete="new-password" required value={password}
                 onChange={(e) => setPassword(e.target.value)} />
        </label>
        <ul className="text-xs space-y-1" aria-label="Password rules">
          {rules.map((rule) => (
            <li key={rule.text} className={rule.ok ? 'text-emerald-400' : 'text-slate-500'}>
              {rule.ok ? '✓' : '•'} {rule.text}
            </li>
          ))}
        </ul>
        <button className={button} disabled={busy || !rules.every((r) => r.ok)} type="submit">
          {busy && <Loader2 className="w-4 h-4 animate-spin" />} Create account
        </button>
      </form>
      <p className="text-sm text-slate-400">
        Already registered? <Link className="text-indigo-400 hover:underline" to="/login">Sign in</Link>
      </p>
    </Card>
  );
};

export const VerifyOtpPage: React.FC = () => {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const email = params.get('email') ?? '';
  const next = useNext();
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [resent, setResent] = useState(false);
  const [error, setError] = useState<unknown>(null);

  if (!email) return <Navigate to="/login" replace />;

  const verify = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await postJson<OtpVerifyResponse>('/auth/otp/verify', { email, otp: code.trim() });
      if (res.token) {
        await signIn(res.token);
        navigate(next, { replace: true });
      } else {
        navigate('/login', { replace: true });
      }
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  const resend = async () => {
    setError(null);
    setResent(false);
    try {
      await postJson('/auth/otp/send', { email });
      setResent(true);
    } catch (err) {
      setError(err);
    }
  };

  return (
    <Card title="Enter your verification code">
      <Notice tone="info">
        We sent a 6-digit code to <strong>{email}</strong>. It expires in a few minutes.
        <br />
        <span className="text-xs opacity-80">
          Development servers without email configured print the code to the server console instead.
        </span>
      </Notice>
      {resent && <Notice tone="success" title="A new code has been sent." />}
      <ErrorNotice error={error} />
      <form onSubmit={verify} className="space-y-4">
        <input
          className={`${field} text-center tracking-[0.5em] text-lg font-mono`}
          inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} required
          aria-label="Verification code" value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
        />
        <button className={button} disabled={busy || code.length !== 6} type="submit">
          {busy && <Loader2 className="w-4 h-4 animate-spin" />} Verify
        </button>
      </form>
      <button type="button" onClick={resend} className="text-sm text-indigo-400 hover:underline">
        Send a new code
      </button>
    </Card>
  );
};
