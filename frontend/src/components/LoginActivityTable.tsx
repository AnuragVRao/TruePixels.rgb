import React from 'react';
import type { LoginEvent, LoginOutcome } from '../api/types';
import { formatDateTime } from '../lib/format';

export const OUTCOME: Record<LoginOutcome, { label: string; tone: string }> = {
  success: { label: 'Signed in', tone: 'bg-success/10 border-success/50 text-success-text' },
  otp_sent: { label: 'Password correct, code sent', tone: 'bg-info/10 border-info/50 text-info-text' },
  wrong_password: { label: 'Wrong password', tone: 'bg-destructive/10 border-destructive/50 text-destructive-text' },
  unknown_account: { label: 'No such account', tone: 'bg-destructive/10 border-destructive/50 text-destructive-text' },
  account_disabled: { label: 'Account disabled', tone: 'bg-warning/10 border-warning/50 text-warning-text' },
  not_admin: { label: 'Not an administrator', tone: 'bg-warning/10 border-warning/50 text-warning-text' },
  otp_failed: { label: 'Wrong verification code', tone: 'bg-destructive/10 border-destructive/50 text-destructive-text' },
  password_reset: { label: 'Password reset by e-mail', tone: 'bg-accent border-primary/40 text-primary' },
  password_changed: { label: 'Password changed', tone: 'bg-accent border-primary/40 text-primary' },
};

/** "Chrome 129 on Windows" from a user-agent string; the full string is in the tooltip. */
// Order matters: Edge and Opera also claim "Chrome", and Chrome also claims "Safari".
const BROWSERS: [string, RegExp][] = [
  ['Edge', /Edg\/(\d+)/], ['Opera', /OPR\/(\d+)/], ['Firefox', /Firefox\/(\d+)/],
  ['Chrome', /Chrome\/(\d+)/], ['Safari', /Version\/(\d+).*Safari/],
];
const SYSTEMS: [string, RegExp][] = [
  ['Windows', /Windows/], ['Android', /Android/], ['iOS', /iPhone|iPad/], ['macOS', /Mac OS X/], ['Linux', /Linux/],
];

export function browserOf(agent: string | null): string {
  if (!agent) return 'Unknown';
  const found = BROWSERS.map(([name, re]) => [name, re.exec(agent)] as const).find(([, m]) => m);
  const browser = found ? `${found[0]} ${found[1]![1]}` : null;
  const os = SYSTEMS.find(([, re]) => re.test(agent))?.[0] ?? null;
  if (browser && os) return `${browser} on ${os}`;
  return browser ?? os ?? (agent.length > 40 ? `${agent.slice(0, 40)}…` : agent);
}

/** Every field is rendered as text: e-mails and user-agents are attacker-supplied. */
export const LoginActivityTable: React.FC<{ rows: LoginEvent[]; showEmail?: boolean }> = ({ rows, showEmail }) => (
  <div className="overflow-x-auto rounded-lg border border-border">
    <table className="w-full text-sm">
      <thead className="bg-muted text-center text-xs uppercase tracking-wide text-muted-foreground">
        <tr>
          <th className="px-3 py-2">Time</th>
          {showEmail && <th className="px-3 py-2">E-mail</th>}
          <th className="px-3 py-2">Result</th>
          <th className="px-3 py-2">Portal</th>
          <th className="px-3 py-2">IP address</th>
          <th className="px-3 py-2">Browser</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-border" data-testid="login-activity-rows">
        {rows.map((row) => {
          const outcome = OUTCOME[row.outcome] ?? { label: row.outcome, tone: 'border-border text-foreground/80' };
          return (
            <tr key={row.event_id}>
              <td className="px-3 py-2 whitespace-nowrap text-muted-foreground">{formatDateTime(row.created_at)}</td>
              {showEmail && (
                <td className="px-3 py-2 text-foreground break-all">
                  {row.email}
                  {row.user_id === null && <span className="ml-1 text-xs text-muted-foreground">(no account)</span>}
                </td>
              )}
              <td className="px-3 py-2">
                <span className={`inline-block whitespace-nowrap px-2 py-0.5 rounded-full border text-xs ${outcome.tone}`}>
                  {outcome.label}
                </span>
              </td>
              <td className="px-3 py-2 text-foreground/80 capitalize">{row.portal}</td>
              <td className="px-3 py-2 text-foreground/80 font-mono whitespace-nowrap">{row.ip_address ?? '—'}</td>
              <td className="px-3 py-2 text-foreground/80 whitespace-nowrap" title={row.user_agent ?? undefined}>
                {browserOf(row.user_agent)}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  </div>
);
