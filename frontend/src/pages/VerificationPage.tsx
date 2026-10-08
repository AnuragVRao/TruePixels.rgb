import React, { useState } from 'react';
import { CheckCircle2, Loader2, MinusCircle, Play, XCircle } from 'lucide-react';
import { getToken } from '../api/client';
import { useAuth } from '../context/AuthContext';

/**
 * Tab 4 - "1-Click Verification", after M3's original Live Verification Suite.
 * Live requests against the API's seams. A check passes only on its EXACT
 * expected status (no "PASS whatever happened", the old tester's bug); checks
 * that need one of your own predictions are SKIPPED, not failed, without one.
 * Raw fetch on purpose: an expected 401/403/404 must not trigger the app's
 * sign-out-on-401 handling.
 */
type Outcome = 'pass' | 'fail' | 'skip';
interface Result { name: string; request: string; expected: string; got: string; ms: number | null; outcome: Outcome; note?: string }

async function call(path: string, withToken = true): Promise<{ status: number; ms: number; response: Response }> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (withToken && token) headers.Authorization = `Bearer ${token}`;
  const start = performance.now();
  const response = await fetch(path, { headers });
  return { status: response.status, ms: Math.round(performance.now() - start), response };
}

export const VerificationPage: React.FC = () => {
  const { user } = useAuth();
  const isAdmin = user?.role === 'Admin';
  const [results, setResults] = useState<Result[]>([]);
  const [running, setRunning] = useState(false);

  const run = async () => {
    setRunning(true);
    setResults([]);
    const out: Result[] = [];
    const push = (r: Result) => { out.push(r); setResults([...out]); };
    const exact = async (name: string, path: string, expected: number, withToken = true,
                         extra?: (r: Response) => Promise<string | null>) => {
      try {
        const { status, ms, response } = await call(path, withToken);
        let note: string | undefined;
        let ok = status === expected;
        if (ok && extra) {
          const problem = await extra(response);
          if (problem) { ok = false; note = problem; }
        }
        push({ name, request: `GET ${path}`, expected: String(expected), got: String(status), ms, outcome: ok ? 'pass' : 'fail', note });
      } catch (err) {
        push({ name, request: `GET ${path}`, expected: String(expected), got: 'network error', ms: null, outcome: 'fail',
               note: (err as Error).message });
      }
    };

    await exact('System health', '/api/v1/health', 200);
    await exact('Models loaded and ready', '/ready', 200, true, async (r) => {
      const body = await r.json().catch(() => null);
      return body?.ready === true ? null : 'the readiness answer is not {ready: true}';
    });
    await exact('Your session is valid', '/api/v1/auth/me', 200);
    await exact('Requests without a session are refused', '/api/v1/history', 401, false);

    // Your newest prediction, if any.
    let newest: number | null = null;
    try {
      const { response } = await call('/api/v1/history?page=1&page_size=1');
      if (response.ok) newest = (await response.json()).items?.[0]?.prediction_id ?? null;
    } catch { /* reported by the checks below */ }

    if (newest === null) {
      for (const name of ['Your newest result (confidence rule)', 'PDF report for your newest result']) {
        push({ name, request: '-', expected: '-', got: '-', ms: null, outcome: 'skip', note: 'Analyse an image first.' });
      }
    } else {
      await exact('Your newest result (confidence rule)', `/api/v1/results/${newest}`, 200, true, async (r) => {
        const body = await r.json();
        // confidence_score is confidence in the PREDICTED class: never below one half.
        return body.confidence_score >= 0.5 ? null : `confidence ${body.confidence_score} is below 0.5`;
      });
      await exact('PDF report for your newest result', `/api/v1/reports/${newest}`, 200, true, async (r) =>
        (r.headers.get('content-type') ?? '').includes('application/pdf') ? null : 'not a PDF');
    }

    await exact('Security barrier: an id that is not yours', '/api/v1/results/2147483647', 404, true, async (r) => {
      const body = await r.json().catch(() => null);
      return body?.error?.code === 'INF_PREDICTION_NOT_FOUND' ? null : 'wrong error code';
    });
    await exact(isAdmin ? 'Admin summary (you are an admin)' : 'Admin summary is refused for users',
                '/api/v1/admin/summary', isAdmin ? 200 : 403);
    setRunning(false);
  };

  const passed = results.filter((r) => r.outcome === 'pass').length;
  const failed = results.filter((r) => r.outcome === 'fail').length;
  const skipped = results.filter((r) => r.outcome === 'skip').length;
  const done = !running && results.length > 0;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3 rounded-2xl border border-border bg-card p-5">
        <div>
          <h1 className="text-lg font-bold text-foreground flex items-center gap-2">
            <CheckCircle2 className="w-5 h-5 text-emerald-700 dark:text-emerald-400" /> Live Verification Suite
          </h1>
          <p className="text-sm text-muted-foreground">Runs live checks against the API&apos;s endpoints and seams, as you.</p>
        </div>
        <button type="button" onClick={run} disabled={running}
                className="flex items-center gap-2 px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-sm font-semibold text-white">
          {running ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />} Run Verification
        </button>
      </div>

      {results.length > 0 && (
        <ul className="space-y-2" data-testid="verification-results">
          {results.map((r) => (
            <li key={r.name} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border bg-background px-4 py-3 text-sm">
              <div className="min-w-0">
                <p className="font-medium text-foreground">{r.name}</p>
                <p className="text-xs text-muted-foreground/80 font-mono break-all">{r.request} · expected {r.expected}</p>
                {r.note && <p className="text-xs text-amber-700 dark:text-amber-300">{r.note}</p>}
              </div>
              <span className={`flex items-center gap-1.5 font-semibold ${
                r.outcome === 'pass' ? 'text-emerald-700 dark:text-emerald-400' : r.outcome === 'fail' ? 'text-rose-700 dark:text-rose-400' : 'text-muted-foreground'}`}
                    data-outcome={r.outcome}>
                {r.outcome === 'pass' ? <CheckCircle2 className="w-4 h-4" /> : r.outcome === 'fail' ? <XCircle className="w-4 h-4" /> : <MinusCircle className="w-4 h-4" />}
                {r.outcome === 'skip' ? 'SKIPPED' : `${r.outcome === 'pass' ? 'PASS' : 'FAIL'} (${r.got}${r.ms !== null ? `, ${r.ms} ms` : ''})`}
              </span>
            </li>
          ))}
        </ul>
      )}
      {done && (
        <p className={`text-sm font-semibold ${failed ? 'text-rose-700 dark:text-rose-400' : 'text-emerald-700 dark:text-emerald-400'}`} data-testid="verification-summary">
          {passed} passed, {failed} failed, {skipped} skipped
        </p>
      )}
    </div>
  );
};
