import React, { useState } from 'react';
import { X, KeyRound, ArrowRight } from 'lucide-react';
import { apiRequest } from '../../api/client';
import { useAuth } from '../../context/AuthContext';
import { ErrorBanner } from '../../components/ErrorBanner';

interface OTPModalProps {
  isOpen: boolean;
  email: string;
  onClose: () => void;
}

export const OTPModal: React.FC<OTPModalProps> = ({
  isOpen,
  email,
  onClose,
}) => {
  const [otp, setOtp] = useState('');
  const [loading, setLoading] = useState(false);
  const [resending, setResending] = useState(false);
  const [resendSuccess, setResendSuccess] = useState(false);
  const [error, setError] = useState<any>(null);
  const { login } = useAuth();

  React.useEffect(() => {
    if (isOpen) {
      setOtp('');
      setError(null);
      setResendSuccess(false);
    }
  }, [isOpen, email]);

  if (!isOpen) return null;

  const handleVerify = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      const res = await apiRequest<{ token?: string; message: string }>(
        '/auth/otp/verify',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email: email.trim().toLowerCase(), otp: otp.trim() }),
        }
      );

      if (res.token) {
        await login(res.token);
      }
      onClose();
    } catch (err: any) {
      setError(err);
    } finally {
      setLoading(false);
    }
  };

  const handleResend = async () => {
    setError(null);
    setResending(true);
    setResendSuccess(false);
    setOtp(''); // Clear stale code
    try {
      await apiRequest<{ message: string }>('/auth/otp/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim().toLowerCase() }),
      });
      setResendSuccess(true);
    } catch (err: any) {
      setError(err);
    } finally {
      setResending(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-md animate-in fade-in duration-150">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-md p-6 shadow-2xl relative">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800 transition-colors"
        >
          <X className="w-5 h-5" />
        </button>

        <div className="flex items-center gap-3 mb-6">
          <div className="w-10 h-10 rounded-xl bg-purple-600/20 border border-purple-500/30 flex items-center justify-center">
            <KeyRound className="w-5 h-5 text-purple-400" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-white">Two-Factor Verification</h2>
            <p className="text-xs text-slate-400">Enter the 6-digit code sent to your email</p>
          </div>
        </div>

        <p className="text-xs text-slate-300 bg-slate-950 p-3 rounded-xl border border-slate-800 mb-4">
          Code dispatched to: <span className="font-mono text-indigo-400 font-bold">{email}</span>
        </p>

        {resendSuccess && (
          <div className="mb-4 p-3 rounded-xl bg-emerald-950/40 border border-emerald-800/40 text-xs text-emerald-300 flex items-center gap-2">
            <span>✓</span>
            <span>A fresh 6-digit code was sent to your inbox. Please enter the new code.</span>
          </div>
        )}

        <ErrorBanner error={error} onDismiss={() => setError(null)} />

        <form onSubmit={handleVerify} className="space-y-4" autoComplete="off">
          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1.5">6-Digit Code</label>
            <input
              type="text"
              name="tp_security_otp_code"
              id="tp_security_otp_code"
              autoComplete="one-time-code"
              autoCorrect="off"
              autoCapitalize="off"
              spellCheck={false}
              data-form-type="other"
              data-lpignore="true"
              required
              maxLength={6}
              value={otp}
              onChange={(e) => setOtp(e.target.value.replace(/\D/g, ''))}
              placeholder="000000"
              className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-center tracking-[12px] font-mono text-2xl font-bold text-indigo-400 placeholder-slate-700 focus:outline-none focus:border-indigo-500 transition-colors"
            />
          </div>

          <button
            type="submit"
            disabled={loading || otp.length !== 6}
            className="w-full py-2.5 px-4 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 font-semibold text-sm text-white shadow-lg shadow-indigo-600/30 transition-all flex items-center justify-center gap-2"
          >
            {loading ? (
              <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            ) : (
              <>
                <span>Verify & Continue</span>
                <ArrowRight className="w-4 h-4" />
              </>
            )}
          </button>
        </form>

        <div className="mt-4 text-center">
          <button
            onClick={handleResend}
            disabled={resending}
            className="text-xs text-slate-400 hover:text-indigo-400 disabled:opacity-50 transition-colors"
          >
            {resending ? 'Sending new code...' : (
              <>Didn't receive a code? <span className="underline">Resend OTP</span></>
            )}
          </button>
        </div>
      </div>
    </div>
  );
};
