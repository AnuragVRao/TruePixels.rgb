import React from 'react';

/** The server's password policy (security.validate_password_strength), checked as the user types. */
export function passwordRules(password: string) {
  return [
    { ok: password.length >= 10, text: 'at least 10 characters' },
    { ok: /\p{Lu}/u.test(password), text: 'an uppercase letter' },
    { ok: /\p{Ll}/u.test(password), text: 'a lowercase letter' },
    { ok: /\p{Nd}/u.test(password), text: 'a digit' },
    { ok: /[^\p{L}\p{N}\s]/u.test(password), text: 'a special character (e.g. ! @ # $ %)' },
  ];
}

export const passwordOk = (password: string) => passwordRules(password).every((rule) => rule.ok);

export const PasswordRules: React.FC<{ password: string }> = ({ password }) => (
  <ul className="text-xs space-y-1" aria-label="Password rules">
    {passwordRules(password).map((rule) => (
      <li key={rule.text} className={rule.ok ? 'text-success-text' : 'text-muted-foreground'}>
        {rule.ok ? '✓' : '•'} {rule.text}
      </li>
    ))}
  </ul>
);
