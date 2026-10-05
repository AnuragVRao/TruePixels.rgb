import React, { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowRight, CloudUpload, Images, Loader2, Lock, ScanLine, ShieldCheck, Upload } from 'lucide-react';
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
    <div className="max-w-3xl mx-auto space-y-8 pt-4">
      <div className="text-center space-y-4">
        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-indigo-500/10 border border-indigo-500/30 text-indigo-300 text-xs font-medium">
          <ScanLine className="w-3.5 h-3.5" /> AI Image Detection
        </span>
        <h1 className="text-4xl sm:text-5xl font-extrabold tracking-tight text-white">
          Analyse{' '}
          <span className="bg-gradient-to-r from-sky-400 to-violet-500 bg-clip-text text-transparent">an Image</span>
        </h1>
        <p className="text-sm sm:text-base text-slate-400 max-w-xl mx-auto leading-relaxed">
          Upload a JPG or PNG image (up to 10 MB). Two independent detectors examine it - one for content, one for
          frequency patterns - and their scores are combined to detect AI-generated images.
        </p>
      </div>

      {/* Drag-and-drop as in M1's original ImageUpload; a dropped file goes
          through exactly the same checks as one picked with the dialog. */}
      <label
        className={`relative flex flex-col items-center justify-center gap-3 rounded-3xl border-2 border-dashed p-10 text-center cursor-pointer bg-slate-900/50 transition-colors ${
          busy ? 'opacity-50 pointer-events-none'
            : dragOver ? 'border-indigo-400 bg-indigo-950/40' : 'border-indigo-500/50 hover:border-indigo-400'
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
          <>
            <img src={preview} alt="Selected image" className="max-h-64 rounded-xl object-contain" />
            <span className="text-sm text-slate-200">{file?.name}</span>
            <span className="text-xs text-indigo-300">Click or drop another image to replace it</span>
          </>
        ) : (
          <>
            <div className="w-16 h-16 rounded-full bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center shadow-lg shadow-indigo-600/40">
              <CloudUpload className="w-8 h-8 text-white" />
            </div>
            <span className="text-lg font-semibold text-white">Drag &amp; drop an image here</span>
            <span className="text-xs text-slate-500">or</span>
            <span className="flex items-center gap-2 px-6 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 font-semibold text-sm text-white shadow-lg shadow-indigo-600/30">
              <Upload className="w-4 h-4" /> Choose an image
            </span>
            <span className="text-xs text-slate-500">Supports JPG, PNG (max 10 MB)</span>
          </>
        )}
        <input type="file" accept=".jpg,.jpeg,.png,image/jpeg,image/png" className="sr-only" disabled={busy}
               onChange={(e) => void choose(e.target.files?.[0] ?? null)} />
      </label>

      {problem && <Notice tone="warning" title={problem} />}
      <ErrorNotice error={error} />

      <label className="flex items-start gap-3 text-sm text-slate-200 max-w-xl mx-auto">
        <input type="checkbox" className="mt-0.5 w-4 h-4 accent-indigo-500" checked={xai} disabled={busy}
               onChange={(e) => setXai(e.target.checked)} />
        <span className="font-medium">
          Include explainability panels
          <span className="block text-xs font-normal text-slate-500">Adds roughly 1-4 seconds. The verdict is identical either way.</span>
        </span>
      </label>

      <button
        type="button" onClick={run} disabled={!file || busy}
        className="w-full max-w-xl mx-auto flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500 disabled:opacity-50 px-4 py-3.5 font-semibold text-white shadow-lg shadow-indigo-600/30"
      >
        {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <ScanLine className="w-4 h-4" />}
        {phase === 'uploading' ? 'Uploading and validating…' : phase === 'analysing' ? `Analysing… ${elapsed}s` : 'Analyse Image'}
        {!busy && <ArrowRight className="w-4 h-4" />}
      </button>
      {phase === 'analysing' && (
        <Notice tone="info">
          Large photos take longer: the frequency detector reads the image at full resolution (a 16-megapixel photo
          can take 10-15 seconds). You can stay on this page; leaving it cancels the wait, not the analysis.
        </Notice>
      )}

      <div className="grid sm:grid-cols-3 gap-4 pt-2">
        <Feature icon={<Images className="w-6 h-6" />} title="Two independent detectors">
          One for semantic content (SigLIP 2) and one for frequency patterns (SPAI).
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

const Feature: React.FC<{ icon: React.ReactNode; title: string; children: React.ReactNode }> = ({ icon, title, children }) => (
  <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5 space-y-2">
    <div className="text-indigo-400">{icon}</div>
    <h3 className="font-semibold text-white">{title}</h3>
    <p className="text-sm text-slate-400 leading-relaxed">{children}</p>
  </div>
);
