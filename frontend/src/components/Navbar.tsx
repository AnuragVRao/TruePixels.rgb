import React from 'react';
import { ShieldCheck, User as UserIcon, ShieldAlert, LogOut, Sparkles } from 'lucide-react';
import { useAuth } from '../context/AuthContext';

interface NavbarProps {
  onOpenAuth: (mode: 'login' | 'register') => void;
  onOpenAdminLogin: () => void;
}

export const Navbar: React.FC<NavbarProps> = ({ onOpenAuth, onOpenAdminLogin }) => {
  const { isAuthenticated, user, isAdmin, logout } = useAuth();

  return (
    <header className="sticky top-0 z-40 w-full border-b border-slate-800/80 bg-slate-950/80 backdrop-blur-xl">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        {/* Brand Logo */}
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-600 via-indigo-500 to-purple-500 flex items-center justify-center shadow-lg shadow-indigo-500/20 ring-1 ring-white/20">
            <ShieldCheck className="w-6 h-6 text-white" />
          </div>
          <div>
            <div className="flex items-center gap-1.5">
              <span className="font-extrabold text-xl tracking-tight text-white">TruePixels</span>
              <span className="text-xs px-1.5 py-0.5 rounded-md font-mono font-bold bg-indigo-500/20 text-indigo-400 border border-indigo-500/30">.rgb</span>
            </div>
            <p className="text-[10px] text-slate-400 tracking-wider font-medium uppercase">AI Image Detection System</p>
          </div>
        </div>

        {/* Navigation Actions */}
        <div className="flex items-center gap-3">
          {isAuthenticated ? (
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2.5 px-3 py-1.5 rounded-xl bg-slate-900 border border-slate-800">
                <div className={`w-2 h-2 rounded-full ${isAdmin ? 'bg-amber-400 animate-pulse' : 'bg-emerald-400'}`} />
                <span className="text-xs font-medium text-slate-300">{user?.email}</span>
                <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-md ${
                  isAdmin ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30' : 'bg-slate-800 text-slate-400'
                }`}>
                  {user?.role}
                </span>
              </div>

              <button
                onClick={logout}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium text-slate-400 hover:text-slate-100 hover:bg-slate-900 border border-transparent hover:border-slate-800 transition-all"
              >
                <LogOut className="w-3.5 h-3.5" />
                <span>Logout</span>
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <button
                onClick={onOpenAdminLogin}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium text-amber-400 hover:text-amber-300 hover:bg-amber-950/40 border border-amber-900/40 transition-all"
              >
                <ShieldAlert className="w-3.5 h-3.5" />
                <span>Admin Login</span>
              </button>

              <button
                onClick={() => onOpenAuth('login')}
                className="px-3.5 py-1.5 rounded-xl text-xs font-medium text-slate-200 hover:text-white hover:bg-slate-900 border border-slate-800 transition-all"
              >
                Sign In
              </button>

              <button
                onClick={() => onOpenAuth('register')}
                className="px-4 py-1.5 rounded-xl text-xs font-semibold text-white bg-indigo-600 hover:bg-indigo-500 shadow-md shadow-indigo-600/30 transition-all"
              >
                Create Account
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
};
