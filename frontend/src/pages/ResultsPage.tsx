import React, { useEffect, useState } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';
import { Download, Loader2 } from 'lucide-react';
import { apiBlob, apiRequest } from '../api/client';
import type { ResultView, Visualization, XaiStatus } from '../api/types';
import { AuthImage } from '../components/AuthImage';
import { ErrorNotice, Notice } from '../components/Feedback';

const PANEL_LABEL: Record<Visualization['branch'], string> = {
  semantic: 'SigLIP 2 attention rollout',
  frequency: 'SPAI patch spectrum',
};

const pct = (x: number) => `${(x * 100).toFixed(1)}%`;

function xaiMessage(status: XaiStatus | undefined, reasons: string[] | undefined, panels: number) {
  if (status === 'unavailable') {
    return { tone: 'warning' as const, text: 'Explainability panels could not be produced for this result. The verdict above is unaffected.' };
  }
  if (status === 'partial' || (status === undefined && panels === 1)) {
    const small = reasons?.some((r) => r.startsWith('frequency:not_applicable'));
    return {
      tone: 'info' as const,
      text: small
        ? 'Only the semantic panel is shown: the image is smaller than the frequency detector\'s 224-pixel patch.'
        : 'Only one explainability panel could be produced for this result.',
    };
  }
  if (status === 'not_requested' || (status === undefined && panels === 0)) {
    return { tone: 'info' as const, text: 'No explainability panels were requested for this result.' };
  }
  return null;
}

const Panel: React.FC<{ v: Visualization }> = ({ v }) => (
  <figure className="space-y-2">
    <figcaption className="text-sm font-semibold text-slate-200">{PANEL_LABEL[v.branch]}</figcaption>
    <AuthImage src={v.visualization_url} alt={PANEL_LABEL[v.branch]}
               className="w-full rounded-xl border border-slate-800 object-contain bg-slate-900 min-h-40" />
    {/* The backend's caption, rendered as text, exactly as returned. */}
    <p className="text-xs leading-relaxed text-slate-400">{v.caption}</p>
  </figure>
);

export const ResultsPage: React.FC = () => {
  const { id } = useParams();
  const location = useLocation();
  const navState = (location.state ?? {}) as { xaiStatus?: XaiStatus; xaiReasons?: string[] };
  const [result, setResult] = useState<ResultView | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [pdfBusy, setPdfBusy] = useState(false);
  const [pdfError, setPdfError] = useState<unknown>(null);

  useEffect(() => {
    const controller = new AbortController();
    setResult(null);
    setError(null);
    apiRequest<ResultView>(`/results/${id}`, { signal: controller.signal })
      .then(setResult)
      .catch((err) => { if ((err as Error).name !== 'AbortError') setError(err); });
    return () => controller.abort();
  }, [id]);

  const downloadPdf = async () => {
    setPdfBusy(true);
    setPdfError(null);
    try {
      const blob = await apiBlob(`/reports/${id}`);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `TruePixels_Report_${id}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) {
      setPdfError(err);
    } finally {
      setPdfBusy(false);
    }
  };

  if (error) return <div className="max-w-2xl mx-auto"><ErrorNotice error={error} /></div>;
  if (!result) return <p className="text-slate-400 text-sm flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" /> Loading result…</p>;

  const ai = result.predicted_class === 'AI Generated';
  const xai = xaiMessage(navState.xaiStatus, navState.xaiReasons, result.visualizations.length);
  const ordered = [...result.visualizations].sort((a, b) => a.branch.localeCompare(b.branch)).reverse();
  const models = [result.models?.semantic, result.models?.frequency, result.models?.fusion].filter(Boolean);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-500">Result #{result.prediction_id}</p>
          <h1 className={`text-3xl font-bold ${ai ? 'text-rose-300' : 'text-emerald-300'}`}>{result.predicted_class}</h1>
          <p className="text-slate-300 mt-1">
            Confidence <strong>{result.confidence_percentage.toFixed(1)}%</strong>{' '}
            <span className="text-slate-500">({result.confidence_band})</span>
          </p>
          <p className="text-xs text-slate-500 mt-1">{new Date(result.prediction_timestamp).toLocaleString()}</p>
        </div>
        <button type="button" onClick={downloadPdf} disabled={pdfBusy}
                className="flex items-center gap-2 rounded-lg border border-slate-700 hover:border-indigo-500 px-4 py-2 text-sm text-slate-200 disabled:opacity-50">
          {pdfBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />} PDF report
        </button>
      </div>
      <ErrorNotice error={pdfError} />

      <div className="grid gap-3 sm:grid-cols-3 text-sm">
        <div className="rounded-xl bg-slate-900/60 border border-slate-800 p-3">
          <p className="text-slate-500 text-xs">Semantic detector, P(AI)</p>
          <p className="text-white font-mono">{pct(result.semantic_score)}</p>
        </div>
        <div className="rounded-xl bg-slate-900/60 border border-slate-800 p-3">
          <p className="text-slate-500 text-xs">Frequency detector, P(AI)</p>
          <p className="text-white font-mono">{result.frequency_score === null ? 'not measured' : pct(result.frequency_score)}</p>
        </div>
        <div className="rounded-xl bg-slate-900/60 border border-slate-800 p-3">
          <p className="text-slate-500 text-xs">Combined score, P(AI)</p>
          <p className="text-white font-mono">{pct(result.fusion_score)}</p>
        </div>
      </div>
      {result.frequency_score === null && (
        <Notice tone="warning" title="Semantic-only verdict">
          The image is smaller than the frequency detector's 224-pixel patch, so only the content-based detector
          produced a score. The two-kinds-of-evidence check does not apply to this result.
        </Notice>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <figure className="space-y-2">
          <figcaption className="text-sm font-semibold text-slate-200">Original image</figcaption>
          {result.original_available ? (
            <AuthImage src={result.original_image_url} alt="Original image"
                       className="w-full rounded-xl border border-slate-800 object-contain bg-slate-900 min-h-40" />
          ) : (
            <Notice tone="warning" title="The original image is no longer stored.">
              The verdict and scores are the recorded result of the analysis made while it was.
            </Notice>
          )}
        </figure>
        {ordered.map((v) => <Panel key={v.branch} v={v} />)}
      </div>
      {xai && <Notice tone={xai.tone}>{xai.text}</Notice>}

      <Notice tone="info" title="How to read this">{result.interpretive_caption}</Notice>

      {models.length > 0 && (
        <div className="text-xs text-slate-500 space-y-0.5">
          <p className="font-semibold text-slate-400">Models that produced this result</p>
          {models.map((m) => (
            <p key={m!.model_id} className="font-mono">#{m!.model_id} {m!.model_name} · {m!.model_version}</p>
          ))}
        </div>
      )}
      <Link to="/history" className="text-sm text-indigo-400 hover:underline">← All results</Link>
    </div>
  );
};
