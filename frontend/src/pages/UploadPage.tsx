import React, { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ImageUp, Loader2 } from 'lucide-react';
import { apiRequest, postJson } from '../api/client';
import type { PredictionResponse, UploadResponse } from '../api/types';
import { ErrorNotice, Notice } from '../components/Feedback';

// Mirrors the server's limits so obvious problems are caught before uploading.
// The server re-validates everything (magic bytes, integrity, pixel cap).
const MAX_BYTES = 10 * 1024 * 1024;
const MIN_SIDE = 64;
const ACCEPTED = ['image/jpeg', 'image/png'];

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

export const UploadPage: React.FC = () => {
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [xai, setXai] = useState(true);
  const [phase, setPhase] = useState<Phase>('idle');
  const [elapsed, setElapsed] = useState(0);
  const [problem, setProblem] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => () => abort.current?.abort(), []);
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);
  useEffect(() => {
    if (phase !== 'analysing') return;
    const started = Date.now();
    const timer = window.setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 500);
    return () => window.clearInterval(timer);
  }, [phase]);

  const choose = async (picked: File | null) => {
    setError(null);
    setProblem(null);
    setFile(null);
    setPreview(null);
    if (!picked) return;
    const issue = await checkLocally(picked);
    if (issue) {
      setProblem(issue);
      return;
    }
    setFile(picked);
    setPreview(URL.createObjectURL(picked));
  };

  const run = async () => {
    if (!file) return;
    setError(null);
    abort.current = new AbortController();
    const signal = abort.current.signal;
    try {
      setPhase('uploading');
      const form = new FormData();
      form.append('file', file);
      const upload = await apiRequest<UploadResponse>('/images', { method: 'POST', body: form, signal });
      setPhase('analysing');
      setElapsed(0);
      const prediction = await postJson<PredictionResponse>('/predictions', { image_id: upload.image_id, xai }, signal);
      navigate(`/results/${prediction.prediction_id}`, { state: { xaiStatus: prediction.xai_status,
        xaiReasons: prediction.xai_reasons } });
    } catch (err) {
      if ((err as Error).name !== 'AbortError') setError(err);
      setPhase('idle');
    }
  };

  const busy = phase !== 'idle';
  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Analyse an image</h1>
        <p className="text-sm text-slate-400 mt-1">
          JPG or PNG, up to 10 MB. Two detectors examine it - one for content, one for frequency patterns - and
          their scores are combined.
        </p>
      </div>

      {/* Drag-and-drop as in M1's original ImageUpload; a dropped file goes
          through exactly the same checks as one picked with the dialog. */}
      <label
        className={`flex flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed p-8 text-center cursor-pointer ${
          busy ? 'opacity-50 pointer-events-none'
            : dragOver ? 'border-indigo-400 bg-indigo-950/30' : 'border-slate-700 hover:border-indigo-500'
        }`}
        onDragOver={(e) => { e.preventDefault(); if (!busy) setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          if (!busy) void choose(e.dataTransfer.files?.[0] ?? null);
        }}
      >
        {preview ? (
          <img src={preview} alt="Selected image" className="max-h-64 rounded-lg object-contain" />
        ) : (
          <ImageUp className="w-10 h-10 text-slate-500" />
        )}
        <span className="text-sm text-slate-300">{file ? file.name : 'Choose an image or drop it here'}</span>
        <input type="file" accept=".jpg,.jpeg,.png,image/jpeg,image/png" className="sr-only" disabled={busy}
               onChange={(e) => void choose(e.target.files?.[0] ?? null)} />
      </label>

      {problem && <Notice tone="warning" title={problem} />}
      <ErrorNotice error={error} />

      <label className="flex items-start gap-2 text-sm text-slate-300">
        <input type="checkbox" className="mt-1" checked={xai} disabled={busy} onChange={(e) => setXai(e.target.checked)} />
        <span>
          Include explainability panels
          <span className="block text-xs text-slate-500">Adds roughly 1-4 seconds. The verdict is identical either way.</span>
        </span>
      </label>

      <button
        type="button" onClick={run} disabled={!file || busy}
        className="w-full flex items-center justify-center gap-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 px-4 py-3 font-semibold text-white"
      >
        {busy && <Loader2 className="w-4 h-4 animate-spin" />}
        {phase === 'uploading' ? 'Uploading and validating…' : phase === 'analysing' ? `Analysing… ${elapsed}s` : 'Analyse'}
      </button>
      {phase === 'analysing' && (
        <Notice tone="info">
          Large photos take longer: the frequency detector reads the image at full resolution (a 16-megapixel photo
          can take 10-15 seconds). You can stay on this page; leaving it cancels the wait, not the analysis.
        </Notice>
      )}
    </div>
  );
};
