import React, { useState, useRef } from 'react';
import {
  UploadCloud,
  FileCheck2,
  AlertCircle,
  Eye,
  ShieldCheck,
  Cpu,
  Layers,
  Sparkles,
  Info,
} from 'lucide-react';
import { apiRequest, ImageUploadResult } from '../../api/client';
import { useAuth } from '../../context/AuthContext';
import { ErrorBanner } from '../../components/ErrorBanner';

interface ImageUploadProps {
  onUploadSuccess?: (result: ImageUploadResult) => void;
  onRequestAuth: (mode?: 'login' | 'register') => void;
}

export const ImageUpload: React.FC<ImageUploadProps> = ({ onUploadSuccess, onRequestAuth }) => {
  const { isAuthenticated, token } = useAuth();
  const [dragOver, setDragOver] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [error, setError] = useState<any>(null);
  const [result, setResult] = useState<ImageUploadResult | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = (file: File) => {
    setError(null);
    setResult(null);

    // Client-side instant check for user comfort (PRD §3.3)
    const validExtensions = ['image/jpeg', 'image/jpg', 'image/png'];
    if (!validExtensions.includes(file.type) && !file.name.match(/\.(jpg|jpeg|png)$/i)) {
      setError({
        code: 'IMG_FORMAT_UNSUPPORTED',
        message: 'Only JPG, JPEG and PNG still images are supported.',
      });
      return;
    }

    if (file.size > 10 * 1024 * 1024) {
      setError({
        code: 'IMG_TOO_LARGE',
        message: `File size (${(file.size / (1024 * 1024)).toFixed(1)} MB) exceeds 10 MB limit.`,
      });
      return;
    }

    setSelectedFile(file);
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFileChange(e.dataTransfer.files[0]);
    }
  };

  const handleUpload = async () => {
    if (!selectedFile) return;
    if (!isAuthenticated) {
      onRequestAuth();
      return;
    }

    setUploading(true);
    setUploadProgress(20);
    setError(null);

    const formData = new FormData();
    formData.append('file', selectedFile);

    try {
      setUploadProgress(60);
      const res = await apiRequest<ImageUploadResult>(
        '/images',
        {
          method: 'POST',
          body: formData,
        },
        token
      );

      setUploadProgress(100);
      setResult(res);
      if (onUploadSuccess) {
        onUploadSuccess(res);
      }
    } catch (err: any) {
      setError(err);
    } finally {
      setUploading(false);
    }
  };

  const resetSelection = () => {
    setSelectedFile(null);
    setPreviewUrl(null);
    setResult(null);
    setError(null);
    setUploadProgress(0);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  return (
    <div className="w-full max-w-4xl mx-auto px-4 py-8">
      {/* Header */}
      <div className="text-center mb-8">
        <div className="inline-flex items-center gap-2 px-3.5 py-1 rounded-full bg-indigo-500/10 border border-indigo-500/30 text-indigo-400 text-xs font-semibold mb-3 shadow-inner">
          <ShieldCheck className="w-4 h-4" />
          <span>Image Authenticity & Integrity Pipeline</span>
        </div>
        <h1 className="text-3xl sm:text-4xl font-extrabold text-white tracking-tight">
          Verify Still Image Authenticity
        </h1>
        <p className="mt-2 text-sm text-slate-400 max-w-xl mx-auto">
          Uploaded images undergo 4-stage integrity validation, EXIF sanitization, and deterministic CLIP & Fourier preprocessing.
        </p>
      </div>

      <ErrorBanner error={error} onDismiss={() => setError(null)} />

      {/* Upload Box */}
      <div className="bg-slate-900/90 border border-slate-800 rounded-3xl p-6 sm:p-8 backdrop-blur-xl shadow-2xl relative overflow-hidden">
        <div className="absolute -top-24 -right-24 w-60 h-60 bg-indigo-600/10 rounded-full blur-3xl pointer-events-none" />

        {!isAuthenticated ? (
          /* Locked State for Unauthenticated Users (Constraint C.6) */
          <div className="border border-slate-800 rounded-2xl p-10 text-center bg-slate-950/60 backdrop-blur-md relative overflow-hidden">
            <div className="w-16 h-16 rounded-2xl bg-indigo-500/10 border border-indigo-500/30 flex items-center justify-center mx-auto mb-4 text-indigo-400 shadow-xl shadow-indigo-500/10">
              <ShieldCheck className="w-8 h-8" />
            </div>
            <h3 className="text-lg font-bold text-white mb-1.5">
              Authentication Required to Upload
            </h3>
            <p className="text-xs text-slate-400 max-w-md mx-auto mb-6 leading-relaxed">
              In accordance with access control constraint <strong>C.6</strong>, authenticity analysis and ingestion require a verified user account.
            </p>

            <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
              <button
                onClick={() => onRequestAuth('login')}
                className="w-full sm:w-auto px-5 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 font-semibold text-xs text-slate-200 transition-all"
              >
                Sign In
              </button>
              <button
                onClick={() => onRequestAuth('register')}
                className="w-full sm:w-auto px-6 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 font-semibold text-xs text-white shadow-lg shadow-indigo-600/30 transition-all flex items-center justify-center gap-2"
              >
                <span>Create Account</span>
              </button>
            </div>
          </div>
        ) : !selectedFile ? (
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`border-2 border-dashed rounded-2xl p-10 text-center cursor-pointer transition-all duration-200 ${
              dragOver
                ? 'border-indigo-500 bg-indigo-500/10 scale-[0.99]'
                : 'border-slate-800 hover:border-slate-700 bg-slate-950/50 hover:bg-slate-950/80'
            }`}
          >
            <input
              type="file"
              ref={fileInputRef}
              onChange={(e) => e.target.files && handleFileChange(e.target.files[0])}
              accept=".jpg,.jpeg,.png"
              className="hidden"
            />
            <div className="w-16 h-16 rounded-2xl bg-indigo-600/20 border border-indigo-500/30 flex items-center justify-center mx-auto mb-4 text-indigo-400 shadow-lg shadow-indigo-600/20">
              <UploadCloud className="w-8 h-8" />
            </div>
            <h3 className="text-base font-bold text-white mb-1">
              Drag & drop still image here, or browse
            </h3>
            <p className="text-xs text-slate-400 mb-4">
              Supported formats: <strong className="text-slate-200">JPG, JPEG, PNG</strong> (Max 10 MB, Min 64×64px)
            </p>

            <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-[11px] text-slate-400">
              <Info className="w-3.5 h-3.5 text-indigo-400" />
              <span>GPS and device EXIF metadata are automatically stripped for privacy</span>
            </div>
          </div>
        ) : (
          <div className="space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 items-center">
              {/* Image Preview */}
              <div className="relative rounded-2xl overflow-hidden bg-slate-950 border border-slate-800 aspect-video flex items-center justify-center group">
                <img
                  src={previewUrl!}
                  alt="Upload preview"
                  className="max-h-full max-w-full object-contain"
                />
                <button
                  onClick={resetSelection}
                  className="absolute top-3 right-3 px-2.5 py-1 rounded-lg bg-slate-900/90 hover:bg-rose-950 border border-slate-700 text-xs text-slate-300 hover:text-rose-300 backdrop-blur-md transition-all"
                >
                  Change Image
                </button>
              </div>

              {/* Validation Inspection Stats */}
              <div className="space-y-3.5">
                <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 space-y-2.5 text-xs">
                  <div className="flex justify-between items-center text-slate-300">
                    <span className="text-slate-500 font-medium">Filename</span>
                    <span className="font-mono text-slate-200 font-semibold truncate max-w-[180px]">
                      {selectedFile.name}
                    </span>
                  </div>
                  <div className="flex justify-between items-center text-slate-300">
                    <span className="text-slate-500 font-medium">Declared Size</span>
                    <span className="font-mono text-slate-200 font-semibold">
                      {(selectedFile.size / (1024 * 1024)).toFixed(2)} MB
                    </span>
                  </div>
                  <div className="flex justify-between items-center text-slate-300">
                    <span className="text-slate-500 font-medium">Client MIME Type</span>
                    <span className="font-mono text-slate-200 font-semibold">{selectedFile.type || 'image/jpeg'}</span>
                  </div>
                </div>

                {!result && (
                  <button
                    onClick={handleUpload}
                    disabled={uploading}
                    className="w-full py-3 px-5 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 font-bold text-sm text-white shadow-xl shadow-indigo-600/30 transition-all flex items-center justify-center gap-2.5"
                  >
                    {uploading ? (
                      <>
                        <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                        <span>Running 4-Stage Validation...</span>
                      </>
                    ) : (
                      <>
                        <ShieldCheck className="w-4 h-4" />
                        <span>Validate & Preprocess Image</span>
                      </>
                    )}
                  </button>
                )}
              </div>
            </div>

            {/* Validation & Preprocessing Result Card */}
            {result && (
              <div className="p-5 rounded-2xl bg-emerald-950/30 border border-emerald-500/40 text-emerald-200 space-y-4 animate-in fade-in duration-300">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <FileCheck2 className="w-5 h-5 text-emerald-400" />
                    <span className="font-bold text-sm text-emerald-100">
                      Validation Passed — Contract C1 Ready
                    </span>
                  </div>
                  <span className="text-[11px] font-mono font-bold px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                    IMAGE #{result.image_id}
                  </span>
                </div>

                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                  <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800">
                    <p className="text-slate-400 text-[10px] uppercase font-bold tracking-wider">Format</p>
                    <p className="font-mono text-slate-100 font-bold mt-0.5">{result.file_format}</p>
                  </div>
                  <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800">
                    <p className="text-slate-400 text-[10px] uppercase font-bold tracking-wider">Geometry</p>
                    <p className="font-mono text-slate-100 font-bold mt-0.5">{result.width}×{result.height} px</p>
                  </div>
                  <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800">
                    <p className="text-slate-400 text-[10px] uppercase font-bold tracking-wider">Tensor Shape</p>
                    <p className="font-mono text-indigo-300 font-bold mt-0.5">(3, 224, 224)</p>
                  </div>
                  <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800">
                    <p className="text-slate-400 text-[10px] uppercase font-bold tracking-wider">EXIF Privacy</p>
                    <p className="font-mono text-emerald-400 font-bold mt-0.5">Sanitized</p>
                  </div>
                </div>

                <div className="text-[11px] font-mono text-slate-400 break-all bg-slate-950/70 p-2.5 rounded-lg border border-slate-800">
                  <span className="text-slate-500">Content SHA256: </span>
                  <span className="text-indigo-300">{result.content_sha256}</span>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
