import React from 'react';

/** A modal confirmation. `children` explains exactly what will happen. */
export const ConfirmDialog: React.FC<{
  title: string;
  confirmLabel: string;
  danger?: boolean;
  busy?: boolean;
  canConfirm?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  children: React.ReactNode;
}> = ({ title, confirmLabel, danger, busy, canConfirm = true, onConfirm, onCancel, children }) => (
  <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="dialog" aria-modal="true"
       aria-labelledby="confirm-title">
    <div className="w-full max-w-lg rounded-2xl border border-border bg-card p-6 space-y-4">
      <h2 id="confirm-title" className="text-lg font-semibold text-foreground">{title}</h2>
      <div className="text-sm text-foreground/80 space-y-2">{children}</div>
      <div className="flex justify-end gap-2">
        <button type="button" onClick={onCancel} disabled={busy}
                className="px-4 py-2 rounded-lg border border-border text-sm text-foreground">Cancel</button>
        <button type="button" onClick={onConfirm} disabled={busy || !canConfirm}
                className={`px-4 py-2 rounded-lg text-sm font-semibold disabled:opacity-40 ${
                  danger ? 'bg-rose-700 hover:bg-rose-600 text-white' : 'bg-primary hover:bg-primary/90 text-primary-foreground'}`}>
          {confirmLabel}
        </button>
      </div>
    </div>
  </div>
);

