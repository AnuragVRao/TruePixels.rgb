import React from 'react';
import type { LoginEvent, LoginOutcome } from '../api/types';

export const OUTCOME: Record<LoginOutcome, { label: string; tone: string }> = {
  success: { label: 'Signed in', tone: 'bg-emerald-500/10 border-emerald-500/40 text-emerald-700 dark:text-emerald-300' },
  otp_sent: { label: 'Password correct, code sent', tone: 'bg-sky-500/10 border-sky-500/40 text-sky-700 dark:text-sky-300' },
  wrong_password: { label: 'Wrong password', tone: 'bg-rose-500/10 border-rose-500/40 text-rose-700 dark:text-rose-300' },
  unknown_account: { label: 'No such account', tone: 'bg-rose-500/10 border-rose-500/40 text-rose-700 dark:text-rose-300' },
  account_disabled: { label: 'Account disabled', tone: 'bg-amber-500/10 border-amber-500/40 text-amber-700 dark:text-amber-300' },
  not_admin: { label: 'Not an administrator', tone: 'bg-amber-500/10 border-amber-500/40 text-amber-700 dark:text-amber-300' },
  otp_failed: { label: 'Wrong verification code', tone: 'bg-rose-500/10 border-rose-500/40 text-rose-700 dark:text-rose-300' },
  password_reset: { label: 'Password reset by e-mail', tone: 'bg-violet-500/10 border-violet-500/40 text-violet-700 dark:text-violet-300' },
  password_changed: { label: 'Password changed', tone: 'bg-violet-500/10 border-violet-500/40 text-violet-700 dark:text-violet-300' },
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
  <div className="overflow-x-auto rounded-xl border border-border">
    <table className="w-full text-sm">
      <thead className="bg-card text-left text-xs uppercase tracking-wide text-muted-foreground/80">
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
              <td className="px-3 py-2 whitespace-nowrap text-muted-foreground">{new Date(row.created_at).toLocaleString()}</td>
              {showEmail && (
                <td className="px-3 py-2 text-foreground break-all">
                  {row.email}
                  {row.user_id === null && <span className="ml-1 text-xs text-muted-foreground/80">(no account)</span>}
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
