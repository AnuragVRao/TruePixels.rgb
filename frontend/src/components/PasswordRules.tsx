import React from 'react';

/** The server's password policy (security.validate_password_strength), checked as the user types. */
export function passwordRules(password: string) {
  return [
    { ok: password.length >= 10, text: 'at least 10 characters' },
    { ok: /[a-zA-Z]/.test(password), text: 'a letter' },
    { ok: /[0-9]/.test(password), text: 'a digit' },
  ];
}

export const passwordOk = (password: string) => passwordRules(password).every((rule) => rule.ok);

export const PasswordRules: React.FC<{ password: string }> = ({ password }) => (
  <ul className="text-xs space-y-1" aria-label="Password rules">
    {passwordRules(password).map((rule) => (
      <li key={rule.text} className={rule.ok ? 'text-emerald-700 dark:text-emerald-400' : 'text-muted-foreground/80'}>
        {rule.ok ? '✓' : '•'} {rule.text}
      </li>
    ))}
  </ul>
);
