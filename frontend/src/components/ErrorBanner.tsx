import React from 'react';
import { AlertTriangle, XCircle } from 'lucide-react';

interface ErrorBannerProps {
  error: {
    code?: string;
    message: string;
    requestId?: string;
  } | string | null;
  onDismiss?: () => void;
}

export const ErrorBanner: React.FC<ErrorBannerProps> = ({ error, onDismiss }) => {
  if (!error) return null;

  const isObj = typeof error === 'object';
  const code = isObj ? error.code : undefined;
  const message = isObj ? error.message : error;
  const requestId = isObj ? error.requestId : undefined;

  return (
    <div className="bg-rose-950/70 border border-rose-600/50 text-rose-200 px-4 py-3 rounded-xl backdrop-blur-md shadow-lg flex items-start gap-3 my-4 animate-in fade-in duration-200">
      <AlertTriangle className="w-5 h-5 text-rose-400 shrink-0 mt-0.5" />
      <div className="flex-1 text-sm">
        <div className="flex items-center gap-2 font-semibold text-rose-100">
          <span>{code ? `Error: ${code}` : 'System Error'}</span>
        </div>
        <p className="mt-1 text-rose-300 leading-relaxed">{message}</p>
        {requestId && (
          <p className="mt-2 text-xs font-mono text-rose-400/80">
            Request ID: <span className="underline">{requestId}</span>
          </p>
        )}
      </div>
      {onDismiss && (
        <button
          onClick={onDismiss}
          className="text-rose-400 hover:text-rose-200 transition-colors p-1"
        >
          <XCircle className="w-4 h-4" />
        </button>
      )}
    </div>
  );
};
