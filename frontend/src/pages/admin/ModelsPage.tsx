import React, { useCallback, useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { ApiError, apiRequest, postJson } from '../../api/client';
import {
  MODEL_TYPE_LABEL,
  type Activation, type ActivationResponse, type GateMetrics, type GatePreview, type GateResult,
  type ModelList, type ModelRow, type ModelType,
} from '../../api/adminTypes';
import { ErrorNotice, Notice } from '../../components/Feedback';
import { ConfirmDialog, when } from './AdminLayout';

const TYPES: ModelType[] = ['semantic-classifier', 'frequency-artifact-classifier', 'fusion-configuration'];

/** Mirrors model_artifacts.MAX_BYTES and accepted formats. A convenience: the server re-checks everything. */
const UPLOAD_RULES: Record<ModelType, { ext: string; maxBytes: number; hint: string }> = {
  'fusion-configuration': { ext: '.json', maxBytes: 16 * 1024,
    hint: 'JSON with exactly strategy ("weighted_average"), weight_semantic, tau, temperature. Max 16 KB.' },
  'semantic-classifier': { ext: '.safetensors', maxBytes: 1024 * 1024,
    hint: 'safetensors with exactly classifier.weight [2, 768] and classifier.bias [2]. Max 1 MB.' },
  'frequency-artifact-classifier': { ext: '.safetensors', maxBytes: 64 * 1024 * 1024,
    hint: "safetensors with exactly SPAI's cls_head tensors. Max 64 MB." },
};

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
  if (row.head) return `uploaded head, sha256 ${row.head.sha256.slice(0, 12)}…`;
  return 'published head';
}

const fmt = (v: number | undefined) => (v == null ? '—' : v.toFixed(3));

/**
 * The gate's own numbers, with honest framing: a coarse safety net on a small
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
      {title && <p className="font-semibold text-white">{title}</p>}
      <p className={gate.passed ? 'text-emerald-300' : 'text-amber-300'}>{verdict}</p>
      <div className="overflow-x-auto">
        <table className="text-xs w-full">
          <thead className="text-slate-500 text-left">
            <tr><th className="pr-3 py-1">Metric</th><th className="pr-3">Published baseline</th><th className="pr-3">Active now</th><th>Candidate</th></tr>
          </thead>
          <tbody className="text-slate-200 font-mono">
            {rows.map(([key, label]) => (
              <tr key={key}>
                <td className="pr-3 py-0.5 font-sans text-slate-400">{label}</td>
                <td className="pr-3">{fmt(gate.baseline?.[key])}</td>
                <td className="pr-3">{fmt(gate.current?.[key])}</td>
                <td>{fmt(gate.candidate?.[key])}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {gate.reasons.length > 0 && (
        <ul className="list-disc pl-5 text-amber-200">{gate.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
      )}
      <p className="text-xs text-slate-500">
        Quality gate: a coarse safety net, not a verification. It scores {gate.reference?.images ?? '?'} images
        ({gate.reference?.real ?? '?'} real, {gate.reference?.generated ?? '?'} generated) from {gate.reference?.split ?? 'the validation split'},
        never the held-out test set. Passing means the candidate did not fall below these thresholds on that small
        sample - not that it is better or correct. {gate.labels_changed != null && `${gate.labels_changed} of these images would change label.`}
      </p>
    </div>
  );
};

const UploadForm: React.FC<{ onDone: (row: ModelRow) => void }> = ({ onDone }) => {
  const [type, setType] = useState<ModelType>('fusion-configuration');
  const [name, setName] = useState('');
  const [version, setVersion] = useState('');
  const [reference, setReference] = useState('');
  const [id2label, setId2label] = useState('{"0": "Real", "1": "AI"}');
  const [aiPositive, setAiPositive] = useState(true);
  const [file, setFile] = useState<File | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const rule = UPLOAD_RULES[type];

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setLocalError(null);
    setError(null);
    if (!file) return setLocalError('Choose a file.');
    if (!file.name.toLowerCase().endsWith(rule.ext)) return setLocalError(`This model type expects a ${rule.ext} file.`);
    if (file.size > rule.maxBytes) return setLocalError(`The file is larger than ${rule.maxBytes / 1024} KB.`);
    const form = new FormData();
    form.set('model_type', type);
    form.set('name', name.trim());
    form.set('version', version.trim());
    form.set('training_reference', reference.trim());
    if (type === 'semantic-classifier') form.set('id2label', id2label);
    if (type === 'frequency-artifact-classifier') form.set('ai_is_positive', String(aiPositive));
    form.set('file', file);
    setBusy(true);
    try {
      onDone(await apiRequest<ModelRow>('/models', { method: 'POST', body: form }));
      setName(''); setVersion(''); setReference(''); setFile(null);
      (event.target as HTMLFormElement).reset();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  const input = 'w-full rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-white';
  return (
    <form onSubmit={submit} className="space-y-3" aria-label="Register a model">
      <div className="grid sm:grid-cols-2 gap-3">
        <label className="text-xs text-slate-400 space-y-1">
          <span className="block">Type</span>
          <select className={input} value={type} onChange={(e) => setType(e.target.value as ModelType)}>
            {TYPES.map((t) => <option key={t} value={t}>{MODEL_TYPE_LABEL[t]}</option>)}
          </select>
        </label>
        <label className="text-xs text-slate-400 space-y-1">
          <span className="block">File ({rule.ext})</span>
          <input className={input} type="file" accept={rule.ext} required
                 onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        <label className="text-xs text-slate-400 space-y-1">
          <span className="block">Name</span>
          <input className={input} required maxLength={120} value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="text-xs text-slate-400 space-y-1">
          <span className="block">Version</span>
          <input className={input} required maxLength={40} value={version} onChange={(e) => setVersion(e.target.value)} />
        </label>
      </div>
      <label className="text-xs text-slate-400 space-y-1 block">
        <span className="block">Evaluation / training reference - where this artefact and any figures for it come from</span>
        <input className={input} required value={reference} onChange={(e) => setReference(e.target.value)} />
      </label>
      {type === 'semantic-classifier' && (
        <label className="text-xs text-slate-400 space-y-1 block">
          <span className="block">id2label (JSON) - which output index means AI is resolved from this, never assumed</span>
          <input className={`${input} font-mono`} value={id2label} onChange={(e) => setId2label(e.target.value)} />
        </label>
      )}
      {type === 'frequency-artifact-classifier' && (
        <label className="flex items-center gap-2 text-sm text-slate-300">
          <input type="checkbox" checked={aiPositive} onChange={(e) => setAiPositive(e.target.checked)} />
          A positive logit means AI-generated
        </label>
      )}
      <p className="text-xs text-slate-500">{rule.hint} These checks in the browser are a convenience only; the server
        validates format, keys, shapes and values itself, and registration never activates anything.</p>
      {localError && <Notice tone="error" title={localError} />}
      <ErrorNotice error={error} />
      <button type="submit" disabled={busy}
              className="flex items-center gap-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 px-4 py-2 text-sm font-semibold text-white">
        {busy && <Loader2 className="w-4 h-4 animate-spin" />} Register (inactive)
      </button>
    </form>
  );
};

type Pending =
  | { kind: 'activate'; row: ModelRow }
  | { kind: 'force'; row: ModelRow; gate: GateResult }
  | { kind: 'rollback'; type: ModelType; target: ModelRow | undefined; targetId: number };

export const ModelsPage: React.FC = () => {
  const [list, setList] = useState<ModelList | null>(null);
  const [activations, setActivations] = useState<Activation[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [previews, setPreviews] = useState<Record<number, GatePreview | ApiError | 'running'>>({});
  const [pending, setPending] = useState<Pending | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<unknown>(null);
  const [outcome, setOutcome] = useState<{ title: string; gate?: GateResult; tone: 'success' | 'warning' } | null>(null);
  const [reason, setReason] = useState('');
  const [acknowledged, setAcknowledged] = useState(false);
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

  const preview = async (row: ModelRow) => {
    setPreviews((p) => ({ ...p, [row.model_id]: 'running' }));
    try {
      const result = await postJson<GatePreview>(`/models/${row.model_id}/gate-preview`, {});
      setPreviews((p) => ({ ...p, [row.model_id]: result }));
    } catch (err) {
      setPreviews((p) => ({ ...p, [row.model_id]: err instanceof ApiError ? err : new ApiError('ERROR', String(err), 0) }));
    }
  };

  const closeDialog = () => { setPending(null); setActionError(null); setReason(''); setAcknowledged(false); };

  const run = async () => {
    if (!pending) return;
    setBusy(true);
    setActionError(null);
    try {
      let res: ActivationResponse;
      if (pending.kind === 'rollback') {
        res = await postJson<ActivationResponse>('/models/rollback', { model_type: pending.type });
      } else {
        const body = pending.kind === 'force' ? { force: true, reason: reason.trim() } : {};
        res = await postJson<ActivationResponse>(`/models/${pending.row.model_id}/activate`, body);
      }
      const verb = res.action === 'rollback' ? 'Rolled back to' : res.forced ? 'Activated (gate overridden):' : 'Activated';
      setOutcome({ title: `${verb} model #${res.activated_model_id} (${MODEL_TYPE_LABEL[res.model_type]}). It is used from the next prediction.`,
        gate: res.gate, tone: res.forced || (res.gate && !res.gate.passed) ? 'warning' : 'success' });
      closeDialog();
      await load();
    } catch (err) {
      if (pending.kind === 'activate' && err instanceof ApiError && err.code === 'MDL_GATE_REFUSED') {
        const gate = (err.body as { gate?: GateResult } | undefined)?.gate;
        setOutcome({ title: `The quality gate refused model #${pending.row.model_id}. Nothing changed.`, gate, tone: 'warning' });
        setPreviews((p) => (gate ? { ...p, [pending.row.model_id]: { model_id: pending.row.model_id,
          model_type: pending.row.model_type, is_active: false, canary: {}, gate } } : p));
        closeDialog();
      } else {
        setActionError(err);
      }
    } finally {
      setBusy(false);
    }
  };

  const latestByType = (type: ModelType) => activations.find((a) => a.model_type === type);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-white">Models</h1>
      <ErrorNotice error={error} />
      {!list && !error && (
        <p className="text-slate-400 text-sm flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" /> Loading…</p>
      )}
      {outcome && (
        <Notice tone={outcome.tone} title={outcome.title}>
          {outcome.gate && <GateReport gate={outcome.gate} />}
        </Notice>
      )}

      {list && (
        <section className="space-y-3" aria-label="Active configuration">
          <h2 className="font-semibold text-white">Running now</h2>
          <div className="grid lg:grid-cols-3 gap-3">
            {TYPES.map((type) => {
              const row = list.active[type];
              const last = latestByType(type);
              const back = last?.previous_model_id != null ? last.previous_model_id : null;
              return (
                <div key={type} className="rounded-xl border border-slate-800 bg-slate-900/50 p-4 space-y-2 text-sm" data-testid={`active-${type}`}>
                  <p className="text-xs uppercase tracking-wide text-slate-500">{MODEL_TYPE_LABEL[type]}</p>
                  {row ? (
                    <>
                      <p className="text-white">#{row.model_id} {row.model_name} <span className="font-mono text-xs text-slate-400 break-all">{row.model_version}</span></p>
                      <p className="text-slate-300">{describeConfig(row)}</p>
                      <p className="text-xs text-slate-400"><span className="text-slate-500">Evaluation reference: </span>{row.training_reference ?? 'none recorded'}</p>
                    </>
                  ) : <p className="text-slate-400">Nothing active (type not in use).</p>}
                  {back != null && (
                    <button type="button" className="text-xs px-2 py-1 rounded border border-slate-600 text-slate-200"
                            onClick={() => { setOutcome(null); setPending({ kind: 'rollback', type, target: byId.get(back), targetId: back }); }}>
                      Roll back to #{back}
                    </button>
                  )}
                </div>
              );
            })}
          </div>
          <p className="text-xs text-slate-500">
            Rollback is offered only where an earlier activation exists, and returns to the model that was active
            before the latest change of that type. Its quality gate is advisory; its canary still blocks.
          </p>
        </section>
      )}

      {list && (
        <section className="space-y-3" aria-label="Registered models">
          <h2 className="font-semibold text-white">Registered models</h2>
          {list.models.length === 0 ? <Notice tone="info" title="No models are registered." /> : (
            <ul className="space-y-3">
              {list.models.map((row) => {
                const p = previews[row.model_id];
                return (
                  <li key={row.model_id} className="rounded-xl border border-slate-800 p-4 space-y-2 text-sm" data-testid={`model-${row.model_id}`}>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="text-white">
                        #{row.model_id} {row.model_name}{' '}
                        <span className="font-mono text-xs text-slate-400 break-all">{row.model_version}</span>{' '}
                        <span className="text-xs text-slate-500">· {MODEL_TYPE_LABEL[row.model_type]}</span>
                        {row.is_active && <span className="ml-2 text-xs rounded bg-emerald-900 text-emerald-200 px-1.5 py-0.5">active</span>}
                      </p>
                      {!row.is_active && (
                        <div className="flex gap-2">
                          <button type="button" disabled={p === 'running'} onClick={() => preview(row)}
                                  className="text-xs px-2 py-1 rounded border border-slate-600 text-slate-200 disabled:opacity-50">
                            {p === 'running' ? 'Checking…' : 'Check quality gate'}
                          </button>
                          <button type="button" onClick={() => { setOutcome(null); setPending({ kind: 'activate', row }); }}
                                  className="text-xs px-2 py-1 rounded bg-indigo-600 text-white">Activate…</button>
                        </div>
                      )}
                    </div>
                    <p className="text-slate-300">{describeConfig(row)}</p>
                    <p className="text-xs text-slate-400">
                      Registered {when(row.registered_at)} · reference: {row.training_reference ?? 'none recorded'}
                    </p>
                    {p instanceof ApiError && <ErrorNotice error={p} />}
                    {p && p !== 'running' && !(p instanceof ApiError) && (
                      <div className="rounded-lg bg-slate-900/70 p-3 space-y-2">
                        <GateReport gate={p.gate} title="Quality gate preview (nothing was activated)" />
                        {!p.gate.passed && !row.is_active && (
                          <button type="button" className="text-xs px-2 py-1 rounded border border-rose-700 text-rose-300"
                                  onClick={() => { setOutcome(null); setPending({ kind: 'force', row, gate: p.gate }); }}>
                            Override the gate…
                          </button>
                        )}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      )}

      {list && (
        <section className="rounded-xl border border-slate-800 p-4 space-y-3">
          <h2 className="font-semibold text-white">Register a model</h2>
          <UploadForm onDone={(row) => { setOutcome({ title: `Registered model #${row.model_id}, inactive. Check its gate, then activate.`, tone: 'success' }); load(); }} />
        </section>
      )}

      {activations.length > 0 && (
        <section className="space-y-2">
          <h2 className="font-semibold text-white">Activation history</h2>
          <div className="overflow-x-auto rounded-xl border border-slate-800">
            <table className="w-full text-xs">
              <thead className="bg-slate-900 text-left text-slate-500">
                <tr><th className="px-3 py-2">When</th><th className="px-3 py-2">Type</th><th className="px-3 py-2">Action</th>
                  <th className="px-3 py-2">Model</th><th className="px-3 py-2">Replaced</th><th className="px-3 py-2">Gate</th><th className="px-3 py-2">Reason</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-800 text-slate-300">
                {activations.slice(0, 25).map((a) => (
                  <tr key={a.activation_id}>
                    <td className="px-3 py-1.5 whitespace-nowrap">{when(a.activated_at)}</td>
                    <td className="px-3 py-1.5">{MODEL_TYPE_LABEL[a.model_type]}</td>
                    <td className="px-3 py-1.5">{a.action}{a.forced && <span className="text-rose-300"> (forced)</span>}</td>
                    <td className="px-3 py-1.5 font-mono">#{a.model_id}</td>
                    <td className="px-3 py-1.5 font-mono">{a.previous_model_id != null ? `#${a.previous_model_id}` : '—'}</td>
                    <td className="px-3 py-1.5">{a.gate == null ? '—' : !a.gate.available ? 'not run' : a.gate.passed ? 'within thresholds' : 'refused'}{a.gate?.advisory ? ' (advisory)' : ''}</td>
                    <td className="px-3 py-1.5 whitespace-pre-wrap break-words max-w-xs">{a.reason ?? ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {pending?.kind === 'activate' && (
        <ConfirmDialog title={`Activate model #${pending.row.model_id}?`} confirmLabel={busy ? `Working… ${elapsed}s` : 'Activate'}
                       busy={busy} onConfirm={run} onCancel={closeDialog}>
          <p>{pending.row.model_name} {pending.row.model_version} ({MODEL_TYPE_LABEL[pending.row.model_type]}).</p>
          <p>The server first runs a canary forward pass, then the quality gate on the validation reference set.
            If either refuses, nothing changes. This can take several seconds.</p>
          {busy && <p className="flex items-center gap-2 text-indigo-300"><Loader2 className="w-4 h-4 animate-spin" /> Running canary and quality gate… {elapsed}s</p>}
          <ErrorNotice error={actionError} />
        </ConfirmDialog>
      )}

      {pending?.kind === 'force' && (
        <ConfirmDialog title={`Override the quality gate for model #${pending.row.model_id}?`}
                       confirmLabel={busy ? `Working… ${elapsed}s` : 'Override and activate'} danger busy={busy}
                       canConfirm={acknowledged && reason.trim().length >= 10} onConfirm={run} onCancel={closeDialog}>
          <p className="text-rose-200">The gate refused this model. Overriding makes it run on every prediction from
            the next request, despite these results:</p>
          <ul className="list-disc pl-5 text-amber-200">{pending.gate.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
          <p>The override and your reason are stored with the activation and written to the audit log as a warning.
            The canary still runs and cannot be overridden.</p>
          <label className="block space-y-1">
            <span className="text-xs text-slate-400">Reason (required, at least 10 characters)</span>
            <textarea className="w-full rounded-lg bg-slate-950 border border-slate-700 px-3 py-2 text-sm text-white"
                      rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={acknowledged} onChange={(e) => setAcknowledged(e.target.checked)} />
            I understand the gate refused this model and I am overriding it.
          </label>
          {busy && <p className="flex items-center gap-2 text-indigo-300"><Loader2 className="w-4 h-4 animate-spin" /> Running canary… {elapsed}s</p>}
          <ErrorNotice error={actionError} />
        </ConfirmDialog>
      )}

      {pending?.kind === 'rollback' && (
        <ConfirmDialog title={`Roll back ${MODEL_TYPE_LABEL[pending.type]}?`}
                       confirmLabel={busy ? `Working… ${elapsed}s` : `Roll back to #${pending.targetId}`} busy={busy}
                       onConfirm={run} onCancel={closeDialog}>
          <p>Returns to model #{pending.targetId}
            {pending.target ? ` (${pending.target.model_name} ${pending.target.model_version})` : ''}, which was active
            before the latest change of this type.</p>
          <p>The canary must pass. The quality gate is run and recorded, but is advisory for a rollback.</p>
          {busy && <p className="flex items-center gap-2 text-indigo-300"><Loader2 className="w-4 h-4 animate-spin" /> Rolling back… {elapsed}s</p>}
          <ErrorNotice error={actionError} />
        </ConfirmDialog>
      )}
    </div>
  );
};
