import React from 'react';

/** The asterisk after a mandatory field's label (DBIM Annex B iv). The input's `required` tells screen readers. */
export const Req: React.FC = () => <span className="text-destructive-text" aria-hidden="true">*</span>;

/** The instruction line at the start of a form (DBIM Annex B i). */
export const RequiredNote: React.FC = () => (
  <p className="text-xs text-muted-foreground">Fields marked <Req /> are required.</p>
);
