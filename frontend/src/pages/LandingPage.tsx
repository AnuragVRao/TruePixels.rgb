import React from 'react';
import { Link } from 'react-router-dom';
import { Binary, Eye, Lock, ScanSearch, ShieldAlert, ShieldCheck } from 'lucide-react';

/**
 * The signed-out start page, after M1's original landing view (ImageUpload's
 * locked state + the navbar's three entry points). Wording updated to what the
 * system really does: M1's copy still described a CLIP pipeline.
 */
const Feature: React.FC<{ icon: React.ReactNode; title: string; children: React.ReactNode }> = ({ icon, title, children }) => (
  <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5 space-y-2">
    <div className="w-9 h-9 rounded-xl bg-indigo-500/10 border border-indigo-500/30 flex items-center justify-center text-indigo-400">
      {icon}
    </div>
    <h3 className="font-semibold text-white">{title}</h3>
    <p className="text-sm text-slate-400 leading-relaxed">{children}</p>
  </div>
);

export const LandingPage: React.FC = () => (
  <div className="max-w-4xl mx-auto space-y-10">
    <div className="text-center space-y-3">
      <div className="inline-flex items-center gap-2 px-3.5 py-1 rounded-full bg-indigo-500/10 border border-indigo-500/30 text-indigo-400 text-xs font-semibold">
        <ShieldCheck className="w-4 h-4" />
        <span>Image Authenticity &amp; Integrity Pipeline</span>
      </div>
      <h1 className="text-3xl sm:text-4xl font-extrabold text-white tracking-tight">Verify Still Image Authenticity</h1>
      <p className="text-sm text-slate-400 max-w-xl mx-auto">
        Uploaded images are validated, then examined by two independent detectors - one reading what the picture
        shows, one reading its frequency patterns - and their evidence is combined into one verdict.
      </p>
    </div>

    <div className="bg-slate-900/90 border border-slate-800 rounded-3xl p-6 sm:p-8 relative overflow-hidden">
      <div className="absolute -top-24 -right-24 w-60 h-60 bg-indigo-600/10 rounded-full blur-3xl pointer-events-none" />
      <div className="border border-slate-800 rounded-2xl p-10 text-center bg-slate-950/60 relative">
        <div className="w-16 h-16 rounded-2xl bg-indigo-500/10 border border-indigo-500/30 flex items-center justify-center mx-auto mb-4 text-indigo-400">
          <Lock className="w-8 h-8" />
        </div>
        <h2 className="text-lg font-bold text-white mb-1.5">Authentication Required to Upload</h2>
        <p className="text-xs text-slate-400 max-w-md mx-auto mb-6 leading-relaxed">
          In accordance with access control constraint <strong>C.6</strong>, analysing images requires a verified
          user account. Your images and results are visible only to you.
        </p>
        <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
          <Link to="/login"
                className="w-full sm:w-auto px-5 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 font-semibold text-sm text-slate-200">
            Sign In
          </Link>
          <Link to="/register"
                className="w-full sm:w-auto px-6 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 font-semibold text-sm text-white shadow-lg shadow-indigo-600/30">
            Create Account
          </Link>
        </div>
        <p className="mt-5 text-xs text-slate-500">
          Administrator?{' '}
          <Link to="/admin/login" className="text-amber-400 hover:underline inline-flex items-center gap-1">
            <ShieldAlert className="w-3.5 h-3.5" /> Use the Administrator Portal
          </Link>
        </p>
      </div>
    </div>

    <div className="grid sm:grid-cols-3 gap-4">
      <Feature icon={<ScanSearch className="w-5 h-5" />} title="Two kinds of evidence">
        A semantic detector (SigLIP 2) and a frequency-domain detector (SPAI) judge each image independently.
      </Feature>
      <Feature icon={<Eye className="w-5 h-5" />} title="Explainable results">
        See where the semantic model looked and what the image&apos;s spectrum contains, plus a PDF report.
      </Feature>
      <Feature icon={<Binary className="w-5 h-5" />} title="Honest about limits">
        A result is a model&apos;s estimate, not proof. Confidence is reported for the verdict it was given for.
      </Feature>
    </div>
  </div>
);
