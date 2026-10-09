import React, { useState } from 'react';
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { Loader2, ShieldAlert } from 'lucide-react';
import { ApiError, postJson } from '../api/client';
import type { LoginResponse, MessageResponse, OtpVerifyResponse, RegisterResponse } from '../api/types';
import { useAuth } from '../context/AuthContext';
import { ErrorNotice, Notice } from '../components/Feedback';
import { PasswordInput } from '../components/PasswordInput';
import { PasswordRules, passwordOk } from '../components/PasswordRules';

const field =
  'w-full rounded-lg bg-card border border-border px-3 py-2.5 text-sm text-foreground placeholder-muted-foreground/60 ' +
  'focus:outline-none focus:ring-2 focus:ring-ring';
const adminField =
  'w-full rounded-lg bg-background border border-amber-300 dark:border-amber-900/60 px-3 py-2.5 text-sm text-foreground placeholder-muted-foreground/60 ' +
  'focus:outline-none focus:ring-2 focus:ring-amber-500';
const adminButton =
  'w-full flex items-center justify-center gap-2 rounded-lg bg-amber-600 hover:bg-amber-500 disabled:opacity-50 ' +
  'px-4 py-2.5 text-sm font-semibold text-white';
const button =
  'w-full flex items-center justify-center gap-2 rounded-lg bg-primary hover:bg-primary/90 disabled:opacity-50 ' +
  'px-4 py-2.5 text-sm font-semibold text-primary-foreground';

const Card: React.FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => (
  <div className="max-w-md mx-auto bg-card border border-border rounded-2xl p-6 sm:p-8 space-y-5">
    <h1 className="text-xl font-bold text-foreground">{title}</h1>
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

type SignInProps = { portal: 'user' | 'admin' };

/**
 * One form, two portals (as in M1: AuthModal for users, AdminLoginModal for
 * administrators). The user portal calls /auth/login; the Administrator Portal
 * calls /auth/admin/login, which refuses non-admin accounts (AUTH_FORBIDDEN).
 */
const SignInForm: React.FC<SignInProps> = ({ portal }) => {
  const admin = portal === 'admin';
  const { signIn, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const requested = useNext();
  const next = admin && requested === '/' ? '/admin' : requested;
  const location = useLocation();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const expired = new URLSearchParams(location.search).get('expired') === '1';
  const wasReset = new URLSearchParams(location.search).get('reset') === '1';

  if (isAuthenticated) return <Navigate to={next} replace />;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = { email: email.trim().toLowerCase(), password };
      const res = await postJson<LoginResponse>(admin ? '/auth/admin/login' : '/auth/login', body);
      if (res.requires_otp) {
        navigate(`/verify?email=${encodeURIComponent(body.email)}&next=${encodeURIComponent(next)}`
          + (admin ? '&portal=admin' : ''));
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

  const fields = (
    <>
      <label className="block space-y-1.5 text-sm">
        <span className="text-foreground/80">{admin ? 'Admin Email' : 'Email'}</span>
        <input className={admin ? adminField : field} type="email" autoComplete="email" required value={email}
               onChange={(e) => setEmail(e.target.value)} />
      </label>
      <label className="block space-y-1.5 text-sm">
        <span className="flex items-baseline justify-between">
          <span className="text-foreground/80">{admin ? 'Master Password' : 'Password'}</span>
          <Link to={`/forgot-password${admin ? '?portal=admin' : ''}`}
                className={`text-xs hover:underline ${admin ? 'text-amber-700 dark:text-amber-400' : 'text-primary'}`}>
            Forgot password?
          </Link>
        </span>
        <PasswordInput className={admin ? adminField : field} autoComplete="current-password" required
               value={password} onChange={(e) => setPassword(e.target.value)} />
      </label>
    </>
  );

  if (admin) {
    return (
      <div className="max-w-md mx-auto bg-card border border-amber-300 dark:border-amber-900/50 rounded-2xl p-6 sm:p-8 space-y-5">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-amber-500/10 border border-amber-500/30 flex items-center justify-center text-amber-700 dark:text-amber-400">
            <ShieldAlert className="w-5 h-5" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-foreground">Administrator Portal</h1>
            <p className="text-xs text-amber-700/80 dark:text-amber-300/80">Elevated privilege authentication (F.3)</p>
          </div>
        </div>
        {expired && <Notice tone="warning" title="Your session ended. Please sign in again." />}
        {wasReset && <Notice tone="success" title="Password changed. Sign in with your new password." />}
        <Notice tone="warning" title="Administrators only.">
          This sign-in accepts Admin accounts only. Any other account is refused with AUTH_FORBIDDEN, and the attempt
          is recorded in the audit log.
        </Notice>
        <ErrorNotice error={error} />
        <form onSubmit={submit} className="space-y-4" aria-label="Administrator sign-in">
          {fields}
          <button className={adminButton} disabled={busy} type="submit">
            {busy && <Loader2 className="w-4 h-4 animate-spin" />} Sign in as administrator
          </button>
        </form>
        <p className="text-sm text-muted-foreground">
          Not an administrator? <Link className="text-primary hover:underline" to="/login">User sign-in</Link>
        </p>
      </div>
    );
  }

  return (
    <Card title="Sign in">
      {expired && <Notice tone="warning" title="Your session ended. Please sign in again." />}
      {wasReset && <Notice tone="success" title="Password changed. Sign in with your new password." />}
      <ErrorNotice error={error} />
      <form onSubmit={submit} className="space-y-4" aria-label="User sign-in">
        {fields}
        <button className={button} disabled={busy} type="submit">
          {busy && <Loader2 className="w-4 h-4 animate-spin" />} Sign in
        </button>
      </form>
      <p className="text-sm text-muted-foreground">
        No account? <Link className="text-primary hover:underline" to="/register">Create one</Link>
      </p>
      <p className="text-xs text-muted-foreground/80">
        Administrator? <Link className="text-amber-700 dark:text-amber-400 hover:underline" to="/admin/login">Use the Administrator Portal</Link>
      </p>
    </Card>
  );
};

export const LoginPage: React.FC = () => <SignInForm portal="user" />;
export const AdminLoginPage: React.FC = () => <SignInForm portal="admin" />;

export const RegisterPage: React.FC = () => {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

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
        navigate(`/verify?email=${encodeURIComponent(cleanEmail)}&purpose=register`);
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
    <Card title="Create Account">
      <ErrorNotice error={error} />
      <form onSubmit={submit} className="space-y-4">
        <label className="block space-y-1.5 text-sm">
          <span className="text-foreground/80">Full name</span>
          <input className={field} autoComplete="name" required minLength={2} maxLength={120} value={fullName}
                 onChange={(e) => setFullName(e.target.value)} />
        </label>
        <label className="block space-y-1.5 text-sm">
          <span className="text-foreground/80">Email</span>
          <input className={field} type="email" autoComplete="email" required value={email}
                 onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="block space-y-1.5 text-sm">
          <span className="text-foreground/80">Password</span>
          <PasswordInput className={field} autoComplete="new-password" required value={password}
                 onChange={(e) => setPassword(e.target.value)} />
        </label>
        <PasswordRules password={password} />
        <button className={button} disabled={busy || !passwordOk(password)} type="submit">
          {busy && <Loader2 className="w-4 h-4 animate-spin" />} Create account
        </button>
      </form>
      <p className="text-sm text-muted-foreground">
        Already registered? <Link className="text-primary hover:underline" to="/login">Sign in</Link>
      </p>
    </Card>
  );
};

export const VerifyOtpPage: React.FC = () => {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const email = params.get('email') ?? '';
  // Which challenge the code redeems: registration or a password sign-in.
  const purpose = params.get('purpose') === 'register' ? 'register' : 'login';
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
      const res = await postJson<OtpVerifyResponse>('/auth/otp/verify', { email, otp: code.trim(), purpose });
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
    <Card title={params.get('portal') === 'admin' ? 'Administrator verification' : 'Enter your verification code'}>
      <Notice tone="info">
        We sent a 6-digit code to <strong>{email}</strong>. It expires in a few minutes.
        <br />
        <span className="text-xs opacity-80">
          Development servers without email configured print the code to the server console instead.
        </span>
      </Notice>
      {resent && (
        <Notice tone="success" title="If a sign-in or registration is waiting for a code, a new one has been sent.">
          You can request at most one code a minute. A code stops working after 5 wrong entries.
        </Notice>
      )}
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
      <button type="button" onClick={resend} className="text-sm text-primary hover:underline">
        Send a new code
      </button>
    </Card>
  );
};

/**
 * Forgot password (signed out): e-mail -> 6-digit code + new password -> sign
 * in again. The server answers the first step the same way whether or not the
 * account exists, and a reset code never opens a session by itself.
 */
export const ForgotPasswordPage: React.FC = () => {
  const [params] = useSearchParams();
  const admin = params.get('portal') === 'admin';
  const signInPath = admin ? '/admin/login' : '/login';
  const navigate = useNavigate();
  const [step, setStep] = useState<'email' | 'code'>('email');
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [resent, setResent] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const cleanEmail = email.trim().toLowerCase();
  const mismatch = confirm.length > 0 && confirm !== password;

  const requestCode = async (event?: React.FormEvent) => {
    event?.preventDefault();
    setBusy(true);
    setError(null);
    setResent(false);
    try {
      await postJson<MessageResponse>('/auth/password/forgot', { email: cleanEmail });
      if (step === 'code') setResent(true);
      setStep('code');
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  const reset = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await postJson<MessageResponse>('/auth/password/reset',
        { email: cleanEmail, otp: code.trim(), new_password: password });
      navigate(`${signInPath}?reset=1`, { replace: true });
    } catch (err) {
      // AUTH_INVALID_CREDENTIALS here means the code, not the password.
      setError(err instanceof ApiError && err.code === 'AUTH_INVALID_CREDENTIALS'
        ? new Error('That code is wrong or has expired. Check it, or send a new code.') : err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title={admin ? 'Reset administrator password' : 'Reset your password'}>
      <ErrorNotice error={error} />
      {step === 'email' ? (
        <form onSubmit={requestCode} className="space-y-4" aria-label="Request a reset code">
          <p className="text-sm text-muted-foreground">
            Enter the e-mail address of your account. We will send a 6-digit code to choose a new password.
          </p>
          <label className="block space-y-1.5 text-sm">
            <span className="text-foreground/80">Email</span>
            <input className={field} type="email" autoComplete="email" required value={email}
                   onChange={(e) => setEmail(e.target.value)} />
          </label>
          <button className={button} disabled={busy} type="submit">
            {busy && <Loader2 className="w-4 h-4 animate-spin" />} Send reset code
          </button>
        </form>
      ) : (
        <>
          <Notice tone="info">
            If an account exists for <strong>{cleanEmail}</strong>, a 6-digit code has been sent to it. It expires in a
            few minutes.
            <br />
            <span className="text-xs opacity-80">
              Development servers without email configured print the code to the server console instead.
            </span>
          </Notice>
          {resent && (
            <Notice tone="success" title="If the account exists, a new code has been sent.">
              You can request at most one code a minute. A code stops working after 5 wrong entries.
            </Notice>
          )}
          <form onSubmit={reset} className="space-y-4" aria-label="Choose a new password">
            <label className="block space-y-1.5 text-sm">
              <span className="text-foreground/80">Reset code</span>
              <input className={`${field} text-center tracking-[0.5em] text-lg font-mono`}
                     inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} required
                     value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} />
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
            <button className={button} type="submit"
                    disabled={busy || code.length !== 6 || !passwordOk(password) || confirm !== password}>
              {busy && <Loader2 className="w-4 h-4 animate-spin" />} Set new password
            </button>
          </form>
          <button type="button" onClick={() => void requestCode()} disabled={busy}
                  className="text-sm text-primary hover:underline disabled:opacity-50">
            Send a new code
          </button>
        </>
      )}
      <p className="text-sm text-muted-foreground">
        Remembered it? <Link className="text-primary hover:underline" to={signInPath}>Back to sign in</Link>
      </p>
    </Card>
  );
};
