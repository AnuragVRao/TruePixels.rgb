import React from 'react';
import { AlertTriangle, CheckCircle2, Info } from 'lucide-react';
import { ApiError, messageFor } from '../api/client';

type Tone = 'error' | 'info' | 'success' | 'warning';

const TONES: Record<Tone, string> = {
  error: 'bg-destructive/10 border-destructive text-foreground',
  warning: 'bg-warning/15 border-warning text-foreground',
  info: 'bg-info/10 border-info text-foreground',
  success: 'bg-success/10 border-success text-foreground',
};

export const Notice: React.FC<{ tone?: Tone; title?: string; children?: React.ReactNode }> = ({
  tone = 'info',
  title,
  children,
}) => {
  const Icon = tone === 'success' ? CheckCircle2 : tone === 'info' ? Info : AlertTriangle;
  return (
    <div role={tone === 'error' ? 'alert' : 'status'} className={`flex gap-3 rounded-lg border border-l-4 px-4 py-3 text-sm ${TONES[tone]}`}>
      <Icon className="w-5 h-5 shrink-0 mt-0.5 text-primary" aria-hidden="true" />
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
