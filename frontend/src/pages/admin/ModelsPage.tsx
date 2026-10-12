import React, { useCallback, useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { apiRequest, postJson } from '../../api/client';
import {
  MODEL_TYPE_LABEL,
  type Activation, type ActivationResponse, type GateMetrics, type GateResult,
  type ModelList, type ModelRow, type ModelType,
} from '../../api/adminTypes';
import { ErrorNotice, Notice } from '../../components/Feedback';
import { ConfirmDialog } from './AdminLayout';

const TYPES: ModelType[] = ['semantic-classifier', 'frequency-artifact-classifier', 'fusion-configuration'];

function useElapsed(running: boolean): number {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!running) return undefined;
    setSeconds(0);
    const started = Date.now();
    const id = window.setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 500);
    return () => window.clearInterval(id);
  }, [running]);
  return seconds;
}

function describeConfig(row: ModelRow): string {
  const c = row.configuration;
  if (row.model_type === 'fusion-configuration') {
    return `w(semantic) = ${c.weight_semantic}, τ = ${c.tau}, temperature = ${c.temperature}`;
  }
  const backbone = row.model_type === 'semantic-classifier' && typeof c.checkpoint === 'string' ? `${c.checkpoint} · ` : '';
  if (row.head) return `${backbone}uploaded head, sha256 ${row.head.sha256.slice(0, 12)}…`;
  return `${backbone}published head`;
}

const fmt = (v: number | undefined) => (v == null ? '—' : v.toFixed(3));

/**
 * The gate's own numbers (shown after a rollback, where the gate is advisory), with honest framing: a coarse safety net on a small
 * validation sample, not a certificate that the candidate is better or correct.
 */
const GateReport: React.FC<{ gate: GateResult; title?: string }> = ({ gate, title }) => {
  if (!gate.available) {
    return (
      <Notice tone="warning" title="The quality gate could not run.">
        {gate.reasons.map((r) => <span key={r} className="block">{r}</span>)}
      </Notice>
    );
  }
  const rows: [keyof GateMetrics, string][] = [
    ['accuracy', 'Accuracy'], ['fpr', 'False-positive rate (real called AI)'], ['recall', 'Recall (AI caught)'], ['auc', 'AUC'],
  ];
  const verdict = gate.advisory
    ? `Advisory only (rollback): the gate would have ${gate.passed ? 'passed' : 'refused'} this model.`
    : gate.passed ? 'Within the gate thresholds.' : 'Outside the gate thresholds - activation is refused.';
  return (
    <div className="space-y-2 text-sm" data-testid="gate-report">
      {title && <p className="font-semibold text-foreground">{title}</p>}
      <p className={gate.passed ? 'text-success-text' : 'text-warning-text'}>{verdict}</p>
      <div className="overflow-x-auto">
        <table className="text-xs w-full">
          <thead className="text-muted-foreground text-left">
            <tr><th className="pr-3 py-1">Metric</th><th className="pr-3">Published baseline</th><th className="pr-3">Active now</th><th>Candidate</th></tr>
          </thead>
          <tbody className="text-foreground font-mono">
            {rows.map(([key, label]) => (
              <tr key={key}>
                <td className="pr-3 py-0.5 font-sans text-muted-foreground">{label}</td>
                <td className="pr-3">{fmt(gate.baseline?.[key])}</td>
                <td className="pr-3">{fmt(gate.current?.[key])}</td>
                <td>{fmt(gate.candidate?.[key])}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {gate.reasons.length > 0 && (
        <ul className="list-disc pl-5 text-warning-text">{gate.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
      )}
      <p className="text-xs text-muted-foreground">
        Quality gate: a coarse safety net, not a verification. It scores {gate.reference?.images ?? '?'} images
        ({gate.reference?.real ?? '?'} real, {gate.reference?.generated ?? '?'} generated) from {gate.reference?.split ?? 'the validation split'},
        never the held-out test set. Passing means the candidate did not fall below these thresholds on that small
        sample - not that it is better or correct. {gate.labels_changed != null && `${gate.labels_changed} of these images would change label.`}
      </p>
    </div>
  );
};

/** A rollback waiting for confirmation. */
type Pending = { type: ModelType; target: ModelRow | undefined; targetId: number };

export const ModelsPage: React.FC = () => {
  const [list, setList] = useState<ModelList | null>(null);
  const [activations, setActivations] = useState<Activation[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<unknown>(null);
  const [outcome, setOutcome] = useState<{ title: string; gate?: GateResult; tone: 'success' | 'warning' } | null>(null);
  const elapsed = useElapsed(busy);

  const load = useCallback(async () => {
    try {
      const [models, history] = await Promise.all([
        apiRequest<ModelList>('/models'), apiRequest<Activation[]>('/models/activations'),
      ]);
      setList(models);
      setActivations(history);
    } catch (err) {
      setError(err);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const byId = new Map((list?.models ?? []).map((m) => [m.model_id, m]));

  const closeDialog = () => { setPending(null); setActionError(null); };

  const run = async () => {
    if (!pending) return;
    setBusy(true);
    setActionError(null);
    try {
      const res = await postJson<ActivationResponse>('/models/rollback', { model_type: pending.type });
      setOutcome({ title: `Rolled back to model #${res.activated_model_id} (${MODEL_TYPE_LABEL[res.model_type]}). It is used from the next prediction.`,
        gate: res.gate, tone: res.gate && !res.gate.passed ? 'warning' : 'success' });
      closeDialog();
      await load();
    } catch (err) {
      setActionError(err);
    } finally {
      setBusy(false);
    }
  };

  const latestByType = (type: ModelType) => activations.find((a) => a.model_type === type);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-foreground">Models</h1>
      <ErrorNotice error={error} />
      {!list && !error && (
        <p className="text-muted-foreground text-sm flex items-center gap-2"><Loader2 className="w-5 h-5 animate-spin" aria-hidden="true" /> Loading…</p>
      )}
      {outcome && (
        <Notice tone={outcome.tone} title={outcome.title}>
          {outcome.gate && <GateReport gate={outcome.gate} />}
        </Notice>
      )}

      {list && (
        <section className="space-y-3" aria-label="Active configuration">
          <h2 className="font-semibold text-foreground">Running now</h2>
          <div className="grid lg:grid-cols-3 gap-3">
            {TYPES.map((type) => {
              const row = list.active[type];
              const last = latestByType(type);
              const back = last?.previous_model_id != null ? last.previous_model_id : null;
              return (
                <div key={type} className="rounded-lg border border-border bg-card p-4 space-y-2 text-sm" data-testid={`active-${type}`}>
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">{MODEL_TYPE_LABEL[type]}</p>
                  {row ? (
                    <>
                      <p className="text-foreground">#{row.model_id} {row.model_name} <span className="font-mono text-xs text-muted-foreground break-all">{row.model_version}</span></p>
                      <p className="text-foreground/80">{describeConfig(row)}</p>
                      <p className="text-xs text-muted-foreground"><span className="text-muted-foreground">Evaluation reference: </span>{row.training_reference ?? 'none recorded'}</p>
                    </>
                  ) : <p className="text-muted-foreground">Nothing active (type not in use).</p>}
                  {back != null && (
                    <button type="button" className="btn-secondary px-2.5 py-1 text-xs"
                            onClick={() => { setOutcome(null); setPending({ type, target: byId.get(back), targetId: back }); }}>
                      Roll back to #{back}
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      )}

      {pending && (
        <ConfirmDialog title={`Roll back ${MODEL_TYPE_LABEL[pending.type]}?`}
                       confirmLabel={busy ? `Working… ${elapsed}s` : `Roll back to #${pending.targetId}`} busy={busy}
                       onConfirm={run} onCancel={closeDialog}>
          <p>Returns to model #{pending.targetId}
            {pending.target ? ` (${pending.target.model_name} ${pending.target.model_version})` : ''}, which was active
            before the latest change of this type.</p>
          <p>The canary must pass. The quality gate is run and recorded, but is advisory for a rollback.</p>
          {busy && <p className="flex items-center gap-2 text-primary"><Loader2 className="w-5 h-5 animate-spin" aria-hidden="true" /> Rolling back… {elapsed}s</p>}
          <ErrorNotice error={actionError} />
        </ConfirmDialog>
      )}
    </div>
  );
};
