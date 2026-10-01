import React, { useState } from 'react';
import { AuthProvider, useAuth } from './context/AuthContext';
import { Navbar } from './components/Navbar';
import { ImageUpload } from './features/m1_access/ImageUpload';
import { AdminUserManagement } from './features/m1_access/AdminUserManagement';
import { InvigilatorPanel } from './features/m1_access/InvigilatorPanel';
import { AuthModal } from './features/m1_access/AuthModal';
import { AdminLoginModal } from './features/m1_access/AdminLoginModal';
import { OTPModal } from './features/m1_access/OTPModal';
import { ShieldCheck, Cpu, BarChart3, Binary, Lock, Sparkles } from 'lucide-react';

const MainContent: React.FC = () => {
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login');
  const [adminLoginOpen, setAdminLoginOpen] = useState(false);
  const [otpModalOpen, setOtpModalOpen] = useState(false);
  const [otpEmail, setOtpEmail] = useState('');

  const openAuth = (mode: 'login' | 'register') => {
    setAuthMode(mode);
    setAuthModalOpen(true);
  };

  const handleTriggerOTP = (email: string) => {
    setOtpEmail(email);
    setOtpModalOpen(true);
  };

  return (
    <div className="min-h-screen flex flex-col bg-slate-950 text-slate-100">
      <Navbar
        onOpenAuth={openAuth}
        onOpenAdminLogin={() => setAdminLoginOpen(true)}
      />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-10">
        {/* Core M1 Image Upload Component */}
        <ImageUpload
          onRequestAuth={(mode = 'login') => openAuth(mode)}
          onUploadSuccess={(result) => {
            console.log('Image preprocessed for inference:', result);
          }}
        />

        {/* Dedicated Admin Management Console (F.17 - Admin Role Exclusive) */}
        <AdminUserManagement />

        {/* Live Invigilator & Evaluation Test Bench */}
        <InvigilatorPanel />
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-800/80 bg-slate-950 py-6 text-center text-xs text-slate-500">
        <p>TruePixels.rgb — AI-Generated Image Detection System</p>
      </footer>

      {/* Modals */}
      <AuthModal
        isOpen={authModalOpen}
        initialMode={authMode}
        onClose={() => setAuthModalOpen(false)}
        onTriggerOTP={handleTriggerOTP}
      />

      <AdminLoginModal
        isOpen={adminLoginOpen}
        onClose={() => setAdminLoginOpen(false)}
        onTriggerOTP={handleTriggerOTP}
      />

      <OTPModal
        isOpen={otpModalOpen}
        email={otpEmail}
        onClose={() => setOtpModalOpen(false)}
      />
    </div>
  );
};

export function App() {
  return (
    <AuthProvider>
      <MainContent />
    </AuthProvider>
  );
}

export default App;
