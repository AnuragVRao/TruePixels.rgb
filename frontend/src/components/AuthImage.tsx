import React from 'react';
import { ImageOff, Loader2 } from 'lucide-react';
import { messageFor } from '../api/client';
import { useAuthBlob } from '../hooks/useAuthBlob';

interface AuthImageProps {
  src: string | null;
  alt: string;
  className?: string;
  /** Shown instead of the image when the server says the file is gone / missing. */
  fallbackText?: string;
}

/** An <img> whose bytes come from an authenticated endpoint (blob URL, revoked on unmount). */
export const AuthImage: React.FC<AuthImageProps> = ({ src, alt, className, fallbackText }) => {
  const state = useAuthBlob(src);

  if (state.status === 'loading') {
    return (
      <div className={`flex items-center justify-center bg-slate-900 text-slate-500 ${className ?? ''}`}>
        <Loader2 className="w-5 h-5 animate-spin" aria-label="Loading image" />
      </div>
    );
  }
  if (state.status === 'error') {
    return (
      <div
        role="img"
        aria-label={alt}
        className={`flex flex-col items-center justify-center gap-2 bg-slate-900 text-slate-400 text-xs text-center p-3 ${className ?? ''}`}
      >
        <ImageOff className="w-5 h-5" />
        <span>{fallbackText ?? messageFor(state.error)}</span>
      </div>
    );
  }
  return <img src={state.url} alt={alt} className={className} />;
};
