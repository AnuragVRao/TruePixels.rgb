import React from 'react';
import { Loader2 } from 'lucide-react';

/** A modal confirmation. `children` explains exactly what will happen. */
export const ConfirmDialog: React.FC<{
  title: string;
  confirmLabel: string;
  cancelLabel?: string;
  danger?: boolean;
  busy?: boolean;
  canConfirm?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  children?: React.ReactNode;
}> = ({ title, confirmLabel, cancelLabel = 'Cancel', danger, busy, canConfirm = true, onConfirm, onCancel, children }) => (
  <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="dialog" aria-modal="true"
       aria-labelledby="confirm-title">
    <div className="w-full max-w-lg rounded-lg border border-border bg-card p-6 space-y-4">
      <h2 id="confirm-title" className="text-lg font-semibold text-foreground">{title}</h2>
      {children && <div className="text-sm text-foreground/80 space-y-2">{children}</div>}
      <div className="flex justify-end gap-2">
        <button type="button" onClick={onCancel} disabled={busy}
                className="btn-secondary">{cancelLabel}</button>
        <button type="button" onClick={onConfirm} disabled={busy || !canConfirm}
                className={danger ? 'btn-danger' : 'btn-primary'}>
          {busy && <Loader2 className="w-5 h-5 animate-spin" aria-hidden="true" />}
          {confirmLabel}
        </button>
      </div>
    </div>
  </div>
);
