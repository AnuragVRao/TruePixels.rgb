import React, { useEffect, useMemo, useState } from 'react';
import { Link, useLocation, useSearchParams } from 'react-router-dom';
import { ArrowLeft, Download, FileArchive, Loader2, ScanLine } from 'lucide-react';
import { apiBlob, apiRequest, messageFor, postBlob, saveBlob } from '../api/client';
import type { ResultView } from '../api/types';
import { AuthImage } from '../components/AuthImage';
import { ErrorNotice, Notice } from '../components/Feedback';
import type { BatchFailure } from './UploadPage';
import { MAX_FILES } from './UploadPage';

const BAND_CHIP: Record<ResultView['confidence_band'], string> = {
  High: 'bg-success/10 border-success/50 text-success-text',
  Moderate: 'bg-info/10 border-info/50 text-info-text',
  Low: 'bg-warning/10 border-warning/50 text-warning-text',
};

const pct = (score: number) => `${(score * 100).toFixed(1)}%`;

type Entry = { id: number; result?: ResultView; error?: unknown };

/** Every result of one batch upload on one page, with all PDF reports as one ZIP. */
export const BatchResultsPage: React.FC = () => {
  const [params] = useSearchParams();
  const location = useLocation();
  const failed = ((location.state as { failed?: BatchFailure[] } | null)?.failed) ?? [];
  const ids = useMemo(() => {
    const parsed = (params.get('ids') ?? '').split(',').map((s) => Number(s.trim()))
      .filter((n) => Number.isInteger(n) && n > 0);
    return Array.from(new Set(parsed)).slice(0, MAX_FILES);
  }, [params]);

  const [entries, setEntries] = useState<Entry[]>([]);
  const [zipBusy, setZipBusy] = useState(false);
  const [zipError, setZipError] = useState<unknown>(null);
  const [pdfBusy, setPdfBusy] = useState<number | null>(null);
  const [pdfError, setPdfError] = useState<unknown>(null);

  useEffect(() => {
    const controller = new AbortController();
    setEntries(ids.map((id) => ({ id })));
    ids.forEach((id) => {
      apiRequest<ResultView>(`/results/${id}`, { signal: controller.signal })
        .then((result) => setEntries((cur) => cur.map((e) => (e.id === id ? { id, result } : e))))
        .catch((error) => {
          if ((error as Error).name !== 'AbortError') setEntries((cur) => cur.map((e) => (e.id === id ? { id, error } : e)));
        });
    });
    return () => controller.abort();
  }, [ids]);

  const loaded = entries.filter((e) => e.result).map((e) => e.result!);
  const aiCount = loaded.filter((r) => r.predicted_class === 'AI Generated').length;
  const stillLoading = entries.some((e) => !e.result && !e.error);
  const zipIds = entries.filter((e) => e.result).map((e) => e.id);

  const downloadZip = async () => {
    setZipBusy(true);
    setZipError(null);
    try {
      saveBlob(await postBlob('/reports/zip', { prediction_ids: zipIds }), 'TruePixels_Reports.zip');
    } catch (err) {
      setZipError(err);
    } finally {
      setZipBusy(false);
    }
  };

  const downloadPdf = async (id: number) => {
    setPdfBusy(id);
    setPdfError(null);
    try {
      saveBlob(await apiBlob(`/reports/${id}`), `TruePixels_Report_${id}.pdf`);
    } catch (err) {
      setPdfError(err);
    } finally {
      setPdfBusy(null);
    }
  };

  if (ids.length === 0) {
    return (
      <div className="max-w-2xl mx-auto space-y-4">
        <Notice tone="warning" title="No results to show.">Analyse some images first.</Notice>
        <Link to="/" className="btn-primary"><ScanLine className="w-5 h-5" aria-hidden="true" /> Analyse images</Link>
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <Link to="/" className="inline-flex items-center gap-1.5 text-sm text-primary hover:underline">
        <ArrowLeft className="w-5 h-5" aria-hidden="true" /> Analyse more images
      </Link>

      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-3xl sm:text-4xl font-bold text-primary">Batch results</h1>
          <p className="text-sm text-muted-foreground">
            {stillLoading ? 'Loading results…' : (
              <>{loaded.length} image{loaded.length === 1 ? '' : 's'} analysed:{' '}
                <strong className="text-destructive-text">{aiCount} AI Generated</strong>,{' '}
                <strong className="text-success-text">{loaded.length - aiCount} Real</strong></>
            )}
          </p>
        </div>
        <button type="button" className="btn-primary" onClick={downloadZip} disabled={zipBusy || stillLoading || zipIds.length === 0}>
          {zipBusy ? <Loader2 className="w-5 h-5 animate-spin" aria-hidden="true" /> : <FileArchive className="w-5 h-5" aria-hidden="true" />}
          {zipBusy ? 'Preparing ZIP…' : `Download all reports (.zip)`}
        </button>
      </div>
      <ErrorNotice error={zipError} />
      <ErrorNotice error={pdfError} />

      {failed.length > 0 && (
        <Notice tone="warning" title={`${failed.length} image${failed.length === 1 ? '' : 's'} could not be analysed`}>
          <ul className="list-disc pl-5 space-y-0.5">
            {failed.map((f, i) => <li key={i}><strong>{f.name}</strong>: {f.message}</li>)}
          </ul>
        </Notice>
      )}

      <ul className="grid gap-4 sm:grid-cols-2" aria-label="Results">
        {entries.map((entry) => (
          <li key={entry.id} className="rounded-lg border border-border bg-card overflow-hidden flex flex-col">
            {entry.error ? (
              <div className="p-4 text-sm text-destructive-text">Result #{entry.id}: {messageFor(entry.error)}</div>
            ) : !entry.result ? (
              <div className="p-4 text-sm text-muted-foreground flex items-center gap-2">
                <Loader2 className="w-5 h-5 animate-spin" aria-hidden="true" /> Loading result #{entry.id}…
              </div>
            ) : (
              <ResultCard result={entry.result} busy={pdfBusy === entry.id} onPdf={() => void downloadPdf(entry.id)} />
            )}
          </li>
        ))}
      </ul>

      <p className="text-xs text-muted-foreground">
        Confidence is how far the combined score lies from the decision threshold, not a calibrated probability.
        Open a result for its scores in full, the explanation panels and the limitations that apply.
      </p>
    </div>
  );
};

const ResultCard: React.FC<{ result: ResultView; busy: boolean; onPdf: () => void }> = ({ result, busy, onPdf }) => {
  const ai = result.predicted_class === 'AI Generated';
  return (
    <>
      {result.original_available ? (
        <AuthImage src={result.original_image_url} alt={`Image for result #${result.prediction_id}`}
                   className="w-full h-48 object-contain bg-muted" />
      ) : (
        <div className="h-48 bg-muted flex items-center justify-center text-xs text-muted-foreground p-4 text-center">
          The original image is no longer stored.
        </div>
      )}
      <div className="p-4 space-y-3 flex-1 flex flex-col">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-xs text-muted-foreground">Result #{result.prediction_id}</p>
            <p className={`text-2xl font-bold ${ai ? 'text-destructive-text' : 'text-success-text'}`}>{result.predicted_class}</p>
          </div>
          <span className={`shrink-0 px-2.5 py-1 rounded-full border text-xs font-medium ${BAND_CHIP[result.confidence_band]}`}>
            {result.confidence_percentage.toFixed(1)}% · {result.confidence_band}
          </span>
        </div>
        <dl className="grid grid-cols-3 gap-2 text-xs">
          <Score label="Content" value={pct(result.semantic_score)} />
          <Score label="Frequency" value={result.frequency_score === null ? 'not measured' : pct(result.frequency_score)} />
          <Score label="Combined" value={pct(result.fusion_score)} />
        </dl>
        <div className="flex flex-wrap gap-2 pt-1 mt-auto">
          <Link to={`/results/${result.prediction_id}`} className="btn-secondary">Full result</Link>
          <button type="button" className="btn-secondary" onClick={onPdf} disabled={busy}>
            {busy ? <Loader2 className="w-5 h-5 animate-spin" aria-hidden="true" /> : <Download className="w-5 h-5" aria-hidden="true" />} PDF
          </button>
        </div>
      </div>
    </>
  );
};

const Score: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="rounded-md bg-muted px-2 py-1.5">
    <dt className="text-muted-foreground">{label}</dt>
    <dd className="font-semibold text-foreground">{value}</dd>
  </div>
);
