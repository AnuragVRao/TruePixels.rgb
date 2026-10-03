import React from 'react';
import { AlertTriangle, CheckCircle2, Info } from 'lucide-react';
import { ApiError, messageFor } from '../api/client';

type Tone = 'error' | 'info' | 'success' | 'warning';

const TONES: Record<Tone, string> = {
  error: 'bg-rose-950/60 border-rose-700/60 text-rose-100',
  warning: 'bg-amber-950/50 border-amber-700/60 text-amber-100',
  info: 'bg-sky-950/50 border-sky-700/60 text-sky-100',
  success: 'bg-emerald-950/50 border-emerald-700/60 text-emerald-100',
};

export const Notice: React.FC<{ tone?: Tone; title?: string; children?: React.ReactNode }> = ({
  tone = 'info',
  title,
  children,
}) => {
  const Icon = tone === 'success' ? CheckCircle2 : tone === 'info' ? Info : AlertTriangle;
  return (
    <div role={tone === 'error' ? 'alert' : 'status'} className={`flex gap-3 rounded-xl border px-4 py-3 text-sm ${TONES[tone]}`}>
      <Icon className="w-5 h-5 shrink-0 mt-0.5" />
      <div className="space-y-1">
        {title && <p className="font-semibold">{title}</p>}
        {children && <div className="leading-relaxed opacity-90">{children}</div>}
      </div>
    </div>
  );
};

/** A failed request, in plain language, with the code and request id for support. */
export const ErrorNotice: React.FC<{ error: unknown }> = ({ error }) => {
  if (!error) return null;
  const api = error instanceof ApiError ? error : null;
  return (
    <Notice tone="error" title={messageFor(error)}>
      {api && (
        <span className="font-mono text-xs opacity-75">
          {api.code}
          {api.requestId ? ` · request ${api.requestId}` : ''}
        </span>
      )}
    </Notice>
  );
};
