import React, { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertCircle, ArrowRight, CheckCircle2, CloudUpload, Images, Loader2, Lock, ScanLine, ShieldCheck, Upload, X,
} from 'lucide-react';
import { apiRequest, messageFor, postJson } from '../api/client';
import type { PredictionResponse, UploadResponse } from '../api/types';
import { ErrorNotice, Notice } from '../components/Feedback';

// Mirrors the server's limits so obvious problems are caught before uploading.
// The server re-validates everything (magic bytes, integrity, pixel cap).
const MAX_BYTES = 10 * 1024 * 1024;
const MIN_SIDE = 64;
const ACCEPTED = ['image/jpeg', 'image/png'];
/** Images per batch; the server's ZIP endpoint (POST /reports/zip) takes no more. */
export const MAX_FILES = 10;

async function checkLocally(file: File): Promise<string | null> {
  if (!ACCEPTED.includes(file.type)) return 'Only JPG, JPEG and PNG images are accepted.';
  if (file.size > MAX_BYTES) return `The file is ${(file.size / 2 ** 20).toFixed(1)} MB; the limit is 10 MB.`;
  const url = URL.createObjectURL(file);
  try {
    const size = await new Promise<{ w: number; h: number }>((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve({ w: img.naturalWidth, h: img.naturalHeight });
      img.onerror = () => reject(new Error('unreadable'));
      img.src = url;
    });
    if (Math.min(size.w, size.h) < MIN_SIDE) {
      return `The image is ${size.w}×${size.h}; both sides must be at least ${MIN_SIDE} px.`;
    }
  } catch {
    return 'The file could not be read as an image.';
  } finally {
    URL.revokeObjectURL(url);
  }
  return null;
}

type Phase = 'idle' | 'uploading' | 'analysing';
type ItemStatus = 'ready' | 'invalid' | 'queued' | 'uploading' | 'analysing' | 'done' | 'failed';

interface Item {
  key: string;
  file: File;
  preview: string | null;
  status: ItemStatus;
  /** Why the file was refused locally, or why its upload / analysis failed. */
  message: string | null;
  predictionId?: number;
}

/** A failure carried to the batch results page, so it is not lost on navigation. */
export interface BatchFailure { name: string; message: string }

export const UploadPage: React.FC = () => {
  const navigate = useNavigate();
  const [items, setItems] = useState<Item[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [xai, setXai] = useState(true);
  const [phase, setPhase] = useState<Phase>('idle');
  const [batchRunning, setBatchRunning] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [problem, setProblem] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const abort = useRef<AbortController | null>(null);
  const previews = useRef<string[]>([]);

  useEffect(() => () => {
    abort.current?.abort();
    previews.current.forEach((url) => URL.revokeObjectURL(url));
  }, []);
  useEffect(() => {
    if (phase !== 'analysing') return;
    const started = Date.now();
    const timer = window.setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 500);
    return () => window.clearInterval(timer);
  }, [phase]);

  const update = (key: string, patch: Partial<Item>) =>
    setItems((current) => current.map((item) => (item.key === key ? { ...item, ...patch } : item)));

  const choose = async (picked: FileList | File[] | null) => {
    setError(null);
    setProblem(null);
    previews.current.forEach((url) => URL.revokeObjectURL(url));
    previews.current = [];
    setItems([]);
    const files = Array.from(picked ?? []);
    if (files.length === 0) return;
    if (files.length > MAX_FILES) {
      setProblem(`You chose ${files.length} images; up to ${MAX_FILES} can be analysed at once. The first ${MAX_FILES} were kept.`);
    }
    const kept = files.slice(0, MAX_FILES);
    const issues = await Promise.all(kept.map(checkLocally));
    const next = kept.map((file, i): Item => {
      const preview = issues[i] ? null : URL.createObjectURL(file);
      if (preview) previews.current.push(preview);
      return {
        key: `${i}-${file.name}-${file.size}-${file.lastModified}`,
        file, preview,
        status: issues[i] ? 'invalid' : 'ready',
        message: issues[i],
      };
    });
    // One file that fails the local check is reported as before, without a list.
    if (next.length === 1 && next[0].status === 'invalid') {
      setProblem(next[0].message);
      return;
    }
    setItems(next);
  };

  const remove = (key: string) => setItems((current) => current.filter((item) => item.key !== key));

  const analyseOne = async (file: File, signal: AbortSignal, onAnalysing: () => void) => {
    const form = new FormData();
    form.append('file', file);
    const upload = await apiRequest<UploadResponse>('/images', { method: 'POST', body: form, signal });
    onAnalysing();
    return postJson<PredictionResponse>('/predictions', { image_id: upload.image_id, xai }, signal);
  };

  const runSingle = async (item: Item) => {
    setError(null);
    abort.current = new AbortController();
    const signal = abort.current.signal;
    try {
      setPhase('uploading');
      const prediction = await analyseOne(item.file, signal, () => { setPhase('analysing'); setElapsed(0); });
      navigate(`/results/${prediction.prediction_id}`, { state: { xaiStatus: prediction.xai_status,
        xaiReasons: prediction.xai_reasons } });
    } catch (err) {
      if ((err as Error).name !== 'AbortError') setError(err);
      setPhase('idle');
    }
  };

  // One image at a time: the detectors share one GPU, and parallel analyses
  // risk the WDDM memory stall (CLAUDE.md §4). A failure does not stop the rest.
  const runBatch = async (queue: Item[]) => {
    setError(null);
    setBatchRunning(true);
    abort.current = new AbortController();
    const signal = abort.current.signal;
    queue.forEach((item) => update(item.key, { status: 'queued', message: null }));
    const done: number[] = [];
    const failed: BatchFailure[] = [];
    for (const item of queue) {
      if (signal.aborted) break;
      update(item.key, { status: 'uploading' });
      setPhase('uploading');
      try {
        const prediction = await analyseOne(item.file, signal, () => {
          update(item.key, { status: 'analysing' });
          setPhase('analysing');
          setElapsed(0);
        });
        done.push(prediction.prediction_id);
        update(item.key, { status: 'done', predictionId: prediction.prediction_id });
      } catch (err) {
        if ((err as Error).name === 'AbortError') break;
        const message = messageFor(err);
        failed.push({ name: item.file.name, message });
        update(item.key, { status: 'failed', message });
      }
    }
    setPhase('idle');
    setBatchRunning(false);
    if (done.length > 0) {
      navigate(`/batch?ids=${done.join(',')}`, { state: { failed } });
    } else if (!signal.aborted) {
      setProblem('None of the images could be analysed. The reason is shown under each one.');
    }
  };

  const ready = items.filter((item) => item.status === 'ready' || item.status === 'failed');
  const single = items.length === 1 ? items[0] : null;
  const busy = phase !== 'idle' || batchRunning;
  const run = () => {
    if (single && single.status === 'ready') void runSingle(single);
    else if (ready.length > 0) void runBatch(ready);
  };
  const cancel = () => abort.current?.abort();
  const runnable = items.filter((item) => item.status !== 'invalid');
  const position = runnable.findIndex((item) => item.status === 'uploading' || item.status === 'analysing') + 1;
  const toRun = runnable.length;

  let label = 'Analyse Image';
  if (phase === 'uploading') label = 'Uploading and validating…';
  if (phase === 'analysing') label = `Analysing… ${elapsed}s`;
  if (batchRunning && position > 0) label = `${phase === 'uploading' ? 'Uploading' : 'Analysing'} image ${position} of ${toRun}…`;
  if (!busy && items.length > 1) label = `Analyse ${ready.length} Image${ready.length === 1 ? '' : 's'}`;

  return (
    <div className="max-w-3xl mx-auto space-y-6 sm:space-y-8 sm:pt-4">
      <div className="text-center space-y-4">
        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-primary/10 border border-primary/30 text-primary text-xs font-medium">
          <ScanLine className="w-5 h-5" aria-hidden="true" /> AI Image Detection
        </span>
        <h1 className="text-4xl sm:text-5xl font-bold text-primary">
          Analyse an Image
        </h1>
        <p className="text-sm sm:text-base text-muted-foreground max-w-xl mx-auto leading-relaxed">
          Upload a JPG or PNG image (up to 10 MB), or up to {MAX_FILES} images at once.
        </p>
      </div>

      {/* Drag-and-drop as in M1's original ImageUpload; dropped files go
          through exactly the same checks as ones picked with the dialog. */}
      <label
        className={`relative flex flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed p-6 sm:p-10 text-center cursor-pointer bg-card transition-colors ${
          busy ? 'opacity-50 pointer-events-none'
            : dragOver ? 'border-primary bg-primary/10' : 'border-primary/70 hover:border-primary'
        }`}
        onDragOver={(e) => { e.preventDefault(); if (!busy) setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          if (!busy) void choose(e.dataTransfer.files ?? null);
        }}
      >
        {single?.preview ? (
          <>
            <img src={single.preview} alt={`Preview of ${single.file.name}`} className="max-h-64 rounded-lg object-contain" />
            <span className="text-sm text-foreground">{single.file.name}</span>
            <span className="text-xs text-primary">Click or drop other images to replace it</span>
          </>
        ) : items.length > 1 ? (
          <>
            <Images className="w-8 h-8 text-primary" aria-hidden="true" />
            <span className="text-sm font-semibold text-foreground">{items.length} images chosen</span>
            <span className="text-xs text-primary">Click or drop other images to replace them</span>
          </>
        ) : (
          <>
            <div className="w-16 h-16 rounded-full bg-gradient-to-br from-primary to-secondary flex items-center justify-center">
              <CloudUpload className="w-8 h-8 text-white" aria-hidden="true" />
            </div>
            <span className="hidden sm:block text-lg font-semibold text-primary">Drag &amp; drop images here</span>
            <span className="hidden sm:block text-xs text-muted-foreground">or</span>
            <span className="btn-primary px-6">
              <Upload className="w-5 h-5" aria-hidden="true" /> Choose images
            </span>
            <span className="text-xs text-muted-foreground">Supports JPG, PNG (max 10 MB each, up to {MAX_FILES} at once)</span>
          </>
        )}
        <input type="file" multiple accept=".jpg,.jpeg,.png,image/jpeg,image/png" className="sr-only" disabled={busy}
               onChange={(e) => { void choose(e.target.files); e.target.value = ''; }} />
      </label>

      {(items.length > 1 || single?.status === 'invalid') && (
        <ul className="grid gap-3 sm:grid-cols-2" aria-label="Chosen images">
          {items.map((item) => (
            <li key={item.key} className="flex items-center gap-3 rounded-lg border border-border bg-card p-2.5">
              {item.preview ? (
                <img src={item.preview} alt="" className="w-14 h-14 rounded-md object-cover bg-muted shrink-0" />
              ) : (
                <div className="w-14 h-14 rounded-md bg-muted flex items-center justify-center shrink-0">
                  <AlertCircle className="w-5 h-5 text-destructive-text" aria-hidden="true" />
                </div>
              )}
              <div className="min-w-0 flex-1 space-y-0.5">
                <p className="text-sm font-medium text-foreground truncate" title={item.file.name}>{item.file.name}</p>
                <StatusLine item={item} />
              </div>
              {!busy && item.status !== 'done' && (
                <button type="button" onClick={() => remove(item.key)} className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted"
                        aria-label={`Remove ${item.file.name}`}>
                  <X className="w-5 h-5" aria-hidden="true" />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {problem && <Notice tone="warning" title={problem} />}
      <ErrorNotice error={error} />

      <label className="flex items-start gap-3 text-sm text-foreground max-w-xl mx-auto">
        <input type="checkbox" className="mt-0.5 w-5 h-5 accent-primary" checked={xai} disabled={busy}
               onChange={(e) => setXai(e.target.checked)} />
        <span className="font-medium">
          Include explainability panels
          <span className="block text-xs font-normal text-muted-foreground">
            Adds roughly 1-4 seconds per image. The verdict is identical either way.
          </span>
        </span>
      </label>

      <div className="max-w-xl mx-auto space-y-3">
        <button
          type="button" onClick={run} disabled={ready.length === 0 || busy}
          className="btn-primary flex w-full py-3 text-base"
        >
          {busy ? <Loader2 className="w-5 h-5 animate-spin" aria-hidden="true" /> : <ScanLine className="w-5 h-5" aria-hidden="true" />}
          {label}
          {!busy && <ArrowRight className="w-5 h-5" aria-hidden="true" />}
        </button>
        {batchRunning && (
          <button type="button" onClick={cancel} className="btn-secondary flex w-full">
            Stop
          </button>
        )}
      </div>
      {batchRunning && (
        <p className="text-xs text-muted-foreground text-center max-w-xl mx-auto">
          Images are analysed one at a time. Stopping skips the rest; an image already being analysed still finishes
          and appears in your history.
        </p>
      )}
      {phase === 'analysing' && (
        <Notice tone="info">
          Large photos take longer: the frequency detector reads the image at full resolution (a 16-megapixel photo
          can take 10-15 seconds). You can stay on this page; leaving it cancels the wait, not the analysis.
        </Notice>
      )}

      <div className="grid sm:grid-cols-3 gap-4 pt-2">
        <Feature icon={<Images className="w-6 h-6" />} title="Two independent detectors">
          One for image content (Community Forensics) and one for frequency patterns (SPAI).
        </Feature>
        <Feature icon={<ShieldCheck className="w-6 h-6" />} title="Explainable results">
          See attention maps, the frequency spectrum and an interpretable verdict.
        </Feature>
        <Feature icon={<Lock className="w-6 h-6" />} title="Your images are private">
          Only you can see your images and results. Administrators see metadata, never your images.
        </Feature>
      </div>
    </div>
  );
};

const StatusLine: React.FC<{ item: Item }> = ({ item }) => {
  switch (item.status) {
    case 'invalid':
    case 'failed':
      return <p className="text-xs text-destructive-text">{item.message}</p>;
    case 'queued':
      return <p className="text-xs text-muted-foreground">Waiting…</p>;
    case 'uploading':
      return <p className="text-xs text-primary flex items-center gap-1"><Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" /> Uploading…</p>;
    case 'analysing':
      return <p className="text-xs text-primary flex items-center gap-1"><Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" /> Analysing…</p>;
    case 'done':
      return <p className="text-xs text-success-text flex items-center gap-1"><CheckCircle2 className="w-3.5 h-3.5" aria-hidden="true" /> Done</p>;
    default:
      return <p className="text-xs text-muted-foreground">{(item.file.size / 2 ** 20).toFixed(1)} MB · ready</p>;
  }
};

const Feature: React.FC<{ icon: React.ReactNode; title: string; children: React.ReactNode }> = ({ icon, title, children }) => (
  <div className="rounded-lg border border-border bg-card p-5 space-y-2">
    <div className="text-primary">{icon}</div>
    <h3 className="font-semibold text-foreground">{title}</h3>
    <p className="text-sm text-muted-foreground leading-relaxed">{children}</p>
  </div>
);
