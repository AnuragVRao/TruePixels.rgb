import React, { useEffect, useState } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';
import { Activity, AlertCircle, ArrowLeft, Brain, Download, Info, Layers, Loader2, RefreshCw } from 'lucide-react';
import { apiBlob, apiRequest, saveBlob } from '../api/client';
import type { ResultView, Visualization, XaiStatus } from '../api/types';
import { AuthImage } from '../components/AuthImage';
import { formatDateTime } from '../lib/format';
import { ErrorNotice, Notice } from '../components/Feedback';

/** Display name of the content detector that produced THIS result (its D3 row). */
function contentDetectorName(result: ResultView): string {
  const name = result.models?.semantic?.model_name ?? '';
  if (/commfor/i.test(name)) return 'Community Forensics';
  if (/siglip/i.test(name)) return 'SigLIP 2';
  return name || 'Content detector';
}

const PANEL_LABEL: Record<Visualization['branch'], string> = {
  semantic: 'Content detector attention rollout',
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
  High: 'bg-success/10 border-success/50 text-success-text',
  Moderate: 'bg-info/10 border-info/50 text-info-text',
  Low: 'bg-warning/10 border-warning/50 text-warning-text',
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
        <path d={GAUGE_ARC} pathLength={100} fill="none" stroke="var(--muted)" strokeWidth="12" strokeLinecap="round" />
        <path d={GAUGE_ARC} pathLength={100} fill="none" stroke={ai ? 'var(--destructive)' : 'var(--success)'} strokeWidth="12"
              strokeLinecap="round" strokeDasharray={`${Math.min(100, Math.max(0, percentage))} 100`} />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center pb-3">
        <span className="text-3xl font-bold text-foreground">{percentage.toFixed(1)}%</span>
        <span className="text-sm text-foreground/80">{label}</span>
      </div>
    </div>
    <span className={`-mt-3 inline-flex items-center gap-1.5 px-3 py-1 rounded-full border text-xs font-medium ${BAND_CHIP[band]}`}>
      <AlertCircle className="w-5 h-5 text-primary" aria-hidden="true" /> {band} confidence
    </span>
  </div>
);

const ScoreCard: React.FC<{ icon: React.ReactNode; title: string; value: string }> = ({ icon, title, value }) => (
  <div className="flex gap-4 rounded-lg border border-border bg-card p-5">
    <div className="text-primary shrink-0">{icon}</div>
    <div>
      <p className="text-sm text-foreground/80">{title}</p>
      <p className="mt-1 text-2xl font-mono font-semibold text-foreground">{value}</p>
      <p className="text-xs text-muted-foreground" title="Probability that the image is AI-generated, as this detector scores it">P(AI)</p>
    </div>
  </div>
);

/**
 * How to read the SPAI spectrum, as page text so the image itself stays
 * clean. Both features are the ones recorded in ml/evaluation/RESULTS.md
 * ("What the panels look like"); SPAI applies no window, hence the cross.
 */
const SpectrumKey: React.FC = () => (
  <div className="space-y-1.5 text-xs leading-relaxed text-muted-foreground">
    <p>
      The centre is coarse detail (shapes, colour), the edges fine detail (texture, noise); brighter means more of
      it. The dashed circle is where SPAI splits the two before comparing them.
    </p>
    <details>
      <summary className="cursor-pointer select-none text-foreground/80 hover:text-foreground">What to look for</summary>
      <ul className="mt-1 list-disc space-y-1 pl-4">
        <li>A bright cross through the centre is mostly the edges of the squares SPAI cut the image into. Every image has it.</li>
        <li>Isolated dots in a regular grid mean a pattern repeating every few pixels, such as JPEG&apos;s 8-pixel blocks or the upsampling some generators use.</li>
        <li>It shows what SPAI looked at, not which part of it drove its score.</li>
      </ul>
    </details>
  </div>
);

const Panel: React.FC<{ v: Visualization; label?: string }> = ({ v, label = PANEL_LABEL[v.branch] }) => {
  const tipId = `panel-tip-${v.branch}`;
  return (
    <figure className="relative space-y-2">
      <figcaption className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
        {label}
        {/* The backend's caption, rendered as text, exactly as returned - shown on hover, focus or tap. */}
        <span className="group sm:relative inline-flex">
          <button type="button" aria-label={`About the ${label}`} aria-describedby={tipId}
                  className="rounded-full text-muted-foreground hover:text-primary focus:text-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-primary">
            <Info className="w-5 h-5" aria-hidden="true" />
          </button>
          <span id={tipId} role="tooltip"
                className="pointer-events-none invisible opacity-0 group-hover:visible group-hover:opacity-100 group-focus-within:visible group-focus-within:opacity-100 transition-opacity absolute inset-x-0 top-7 sm:inset-x-auto sm:left-1/2 sm:-translate-x-1/2 sm:top-6 z-20 sm:w-72 sm:max-w-[80vw] rounded-lg border border-border bg-card px-3 py-2 text-xs font-normal leading-relaxed text-muted-foreground shadow-lg">
            {v.caption}
          </span>
        </span>
      </figcaption>
      <AuthImage src={v.visualization_url} alt={label}
                 className="w-full rounded-lg border border-border object-contain bg-card min-h-40" />
      {v.branch === 'frequency' && <SpectrumKey />}
    </figure>
  );
};

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
      saveBlob(await apiBlob(`/reports/${id}`), `TruePixels_Report_${id}.pdf`);
    } catch (err) {
      setPdfError(err);
    } finally {
      setPdfBusy(false);
    }
  };

  if (error) return <div className="max-w-2xl mx-auto"><ErrorNotice error={error} /></div>;
  if (!result) return <p className="text-muted-foreground text-sm flex items-center gap-2"><Loader2 className="w-5 h-5 animate-spin" aria-hidden="true" /> Loading result…</p>;

  const ai = result.predicted_class === 'AI Generated';
  const xai = xaiMessage(navState.xaiStatus, navState.xaiReasons, result.visualizations.length);
  const ordered = [...result.visualizations].sort((a, b) => a.branch.localeCompare(b.branch)).reverse();
  const models = [result.models?.semantic, result.models?.frequency, result.models?.fusion].filter(Boolean);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link to="/" className="flex items-center gap-2 text-sm text-link hover:underline">
          <ArrowLeft className="w-5 h-5" aria-hidden="true" /> New Analysis
        </Link>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={downloadPdf} disabled={pdfBusy}
                  className="btn-secondary">
            {pdfBusy ? <Loader2 className="w-5 h-5 animate-spin" aria-hidden="true" /> : <Download className="w-5 h-5" aria-hidden="true" />} Download Report (PDF)
          </button>
          <Link to="/"
                className="btn-secondary">
            <RefreshCw className="w-5 h-5" aria-hidden="true" /> Analyse Another
          </Link>
        </div>
      </div>
      <ErrorNotice error={pdfError} />

      <div className="relative overflow-hidden rounded-lg border border-border bg-card p-5 sm:p-8 flex flex-wrap items-center justify-center sm:justify-between gap-6">
        <div className="space-y-2">
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-muted border border-border text-xs font-semibold text-foreground">
            <Info className="w-5 h-5 text-primary" aria-hidden="true" /> Result #{result.prediction_id}
          </span>
          <h1 className={`text-4xl sm:text-5xl font-bold tracking-tight ${ai ? 'text-destructive-text' : 'text-success-text'}`}>
            {result.predicted_class}
          </h1>
          <p className="text-lg text-foreground">
            Confidence: <strong>{result.confidence_percentage.toFixed(1)}%</strong>{' '}
            <span className="text-muted-foreground">({result.confidence_band})</span>
          </p>
          <p className="text-sm text-muted-foreground">{formatDateTime(result.prediction_timestamp)}</p>
        </div>
        <ConfidenceGauge percentage={result.confidence_percentage} label={result.predicted_class}
                         band={result.confidence_band} ai={ai} />
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <ScoreCard icon={<Brain className="w-7 h-7" />} title={`Content detector (${contentDetectorName(result)})`}
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
                       className="w-full rounded-lg border border-border object-contain bg-card min-h-40" />
          ) : (
            <Notice tone="warning" title="The original image is no longer stored.">
              The verdict and scores are the recorded result of the analysis made while it was.
            </Notice>
          )}
        </figure>
        {ordered.map((v) => (
          <Panel key={v.branch} v={v}
                 label={v.branch === 'semantic' ? `${contentDetectorName(result)} attention rollout` : undefined} />
        ))}
      </div>
      {xai && <Notice tone={xai.tone}>{xai.text}</Notice>}

      <div className="flex gap-4 rounded-lg border border-info border-l-4 bg-info/10 px-5 py-4">
        <Info className="w-6 h-6 shrink-0 text-primary" aria-hidden="true" />
        <div className="space-y-1">
          <p className="font-semibold text-foreground">How to read this result</p>
          <p className="text-sm leading-relaxed text-foreground/80">{result.interpretive_caption}</p>
        </div>
      </div>

      {models.length > 0 && (
        <div className="text-xs text-muted-foreground space-y-0.5">
          <p className="font-semibold text-muted-foreground">Models that produced this result</p>
          {models.map((m) => (
            <p key={m!.model_id} className="font-mono">#{m!.model_id} {m!.model_name} · {m!.model_version}</p>
          ))}
        </div>
      )}
      <Link to="/history" className="text-sm text-link hover:underline">← All results</Link>
    </div>
  );
};
