import React, { useEffect, useState } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';
import { Activity, AlertCircle, ArrowLeft, Brain, Download, Info, Layers, Loader2, RefreshCw } from 'lucide-react';
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

const BAND_CHIP: Record<ResultView['confidence_band'], string> = {
  High: 'bg-emerald-500/10 border-emerald-500/40 text-emerald-700 dark:text-emerald-300',
  Moderate: 'bg-sky-500/10 border-sky-500/40 text-sky-700 dark:text-sky-300',
  Low: 'bg-amber-500/10 border-amber-500/40 text-amber-700 dark:text-amber-300',
};

// A 240° arc with the gap at the bottom; pathLength 100 makes the dash a percentage.
const GAUGE_ARC = 'M 23.04 100 A 60 60 0 1 1 126.96 100';

/** Confidence in the predicted class (never fusion_score - CLAUDE.md §7). */
const ConfidenceGauge: React.FC<{ percentage: number; label: string; band: ResultView['confidence_band']; ai: boolean }> = ({
  percentage, label, band, ai,
}) => (
  <div className="flex flex-col items-center">
    <div className="relative w-48 h-40">
      <svg viewBox="0 0 150 130" className="w-full h-full" aria-hidden="true">
        <defs>
          <linearGradient id="gauge-ai" x1="0" x2="1"><stop offset="0" stopColor="#f43f5e" /><stop offset="1" stopColor="#fb7185" /></linearGradient>
          <linearGradient id="gauge-real" x1="0" x2="1"><stop offset="0" stopColor="#10b981" /><stop offset="1" stopColor="#34d399" /></linearGradient>
        </defs>
        <path d={GAUGE_ARC} pathLength={100} fill="none" stroke="var(--muted)" strokeWidth="12" strokeLinecap="round" />
        <path d={GAUGE_ARC} pathLength={100} fill="none" stroke={`url(#${ai ? 'gauge-ai' : 'gauge-real'})`} strokeWidth="12"
              strokeLinecap="round" strokeDasharray={`${Math.min(100, Math.max(0, percentage))} 100`} />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center pb-3">
        <span className="text-3xl font-bold text-foreground">{percentage.toFixed(1)}%</span>
        <span className="text-sm text-foreground/80">{label}</span>
      </div>
    </div>
    <span className={`-mt-3 inline-flex items-center gap-1.5 px-3 py-1 rounded-full border text-xs font-medium ${BAND_CHIP[band]}`}>
      <AlertCircle className="w-3.5 h-3.5" /> {band} confidence
    </span>
  </div>
);

const ScoreCard: React.FC<{ icon: React.ReactNode; title: string; value: string }> = ({ icon, title, value }) => (
  <div className="flex gap-4 rounded-2xl border border-border bg-card p-5">
    <div className="text-primary shrink-0">{icon}</div>
    <div>
      <p className="text-sm text-foreground/80">{title}</p>
      <p className="mt-1 text-2xl font-mono font-semibold text-foreground">{value}</p>
      <p className="text-xs text-muted-foreground/80" title="Probability that the image is AI-generated, as this detector scores it">P(AI)</p>
    </div>
  </div>
);

const Panel: React.FC<{ v: Visualization }> = ({ v }) => (
  <figure className="space-y-2">
    <figcaption className="text-sm font-semibold text-foreground">{PANEL_LABEL[v.branch]}</figcaption>
    <AuthImage src={v.visualization_url} alt={PANEL_LABEL[v.branch]}
               className="w-full rounded-xl border border-border object-contain bg-card min-h-40" />
    {/* The backend's caption, rendered as text, exactly as returned. */}
    <p className="text-xs leading-relaxed text-muted-foreground">{v.caption}</p>
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
  if (!result) return <p className="text-muted-foreground text-sm flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" /> Loading result…</p>;

  const ai = result.predicted_class === 'AI Generated';
  const xai = xaiMessage(navState.xaiStatus, navState.xaiReasons, result.visualizations.length);
  const ordered = [...result.visualizations].sort((a, b) => a.branch.localeCompare(b.branch)).reverse();
  const models = [result.models?.semantic, result.models?.frequency, result.models?.fusion].filter(Boolean);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link to="/" className="flex items-center gap-2 text-sm text-primary hover:text-primary/80">
          <ArrowLeft className="w-4 h-4" /> New Analysis
        </Link>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={downloadPdf} disabled={pdfBusy}
                  className="flex items-center gap-2 rounded-xl border border-border hover:border-primary bg-card px-4 py-2 text-sm font-medium text-foreground disabled:opacity-50">
            {pdfBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />} Download Report (PDF)
          </button>
          <Link to="/"
                className="flex items-center gap-2 rounded-xl border border-border hover:border-primary bg-card px-4 py-2 text-sm font-medium text-foreground">
            <RefreshCw className="w-4 h-4" /> Analyse Another
          </Link>
        </div>
      </div>
      <ErrorNotice error={pdfError} />

      <div className="relative overflow-hidden rounded-3xl border border-border bg-card p-6 sm:p-8 flex flex-wrap items-center justify-between gap-6">
        <div className="space-y-2">
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-muted border border-border text-[11px] font-semibold tracking-wider text-foreground/80">
            <Info className="w-3.5 h-3.5" /> RESULT #{result.prediction_id}
          </span>
          <h1 className={`text-4xl sm:text-5xl font-extrabold tracking-tight ${ai ? 'text-rose-700 dark:text-rose-400' : 'text-emerald-700 dark:text-emerald-400'}`}>
            {result.predicted_class}
          </h1>
          <p className="text-lg text-foreground">
            Confidence: <strong>{result.confidence_percentage.toFixed(1)}%</strong>{' '}
            <span className="text-muted-foreground/80">({result.confidence_band})</span>
          </p>
          <p className="text-sm text-muted-foreground/80">{new Date(result.prediction_timestamp).toLocaleString()}</p>
        </div>
        <ConfidenceGauge percentage={result.confidence_percentage} label={result.predicted_class}
                         band={result.confidence_band} ai={ai} />
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <ScoreCard icon={<Brain className="w-7 h-7" />} title="Semantic detector (SigLIP 2)"
                   value={pct(result.semantic_score)} />
        <ScoreCard icon={<Activity className="w-7 h-7" />} title="Frequency detector (SPAI)"
                   value={result.frequency_score === null ? 'not measured' : pct(result.frequency_score)} />
        <ScoreCard icon={<Layers className="w-7 h-7" />} title="Combined score" value={pct(result.fusion_score)} />
      </div>
      {result.frequency_score === null && (
        <Notice tone="warning" title="Semantic-only verdict">
          The image is smaller than the frequency detector's 224-pixel patch, so only the content-based detector
          produced a score. The two-kinds-of-evidence check does not apply to this result.
        </Notice>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <figure className="space-y-2">
          <figcaption className="text-sm font-semibold text-foreground">Original image</figcaption>
          {result.original_available ? (
            <AuthImage src={result.original_image_url} alt="Original image"
                       className="w-full rounded-xl border border-border object-contain bg-card min-h-40" />
          ) : (
            <Notice tone="warning" title="The original image is no longer stored.">
              The verdict and scores are the recorded result of the analysis made while it was.
            </Notice>
          )}
        </figure>
        {ordered.map((v) => <Panel key={v.branch} v={v} />)}
      </div>
      {xai && <Notice tone={xai.tone}>{xai.text}</Notice>}

      <div className="flex gap-4 rounded-2xl border border-sky-300 dark:border-sky-800/60 bg-sky-50 dark:bg-sky-950/30 px-5 py-4">
        <Info className="w-6 h-6 shrink-0 text-sky-700 dark:text-sky-300" />
        <div className="space-y-1">
          <p className="font-semibold text-foreground">How to read this result</p>
          <p className="text-sm leading-relaxed text-foreground/80">{result.interpretive_caption}</p>
        </div>
      </div>

      {models.length > 0 && (
        <div className="text-xs text-muted-foreground/80 space-y-0.5">
          <p className="font-semibold text-muted-foreground">Models that produced this result</p>
          {models.map((m) => (
            <p key={m!.model_id} className="font-mono">#{m!.model_id} {m!.model_name} · {m!.model_version}</p>
          ))}
        </div>
      )}
      <Link to="/history" className="text-sm text-primary hover:underline">← All results</Link>
    </div>
  );
};
