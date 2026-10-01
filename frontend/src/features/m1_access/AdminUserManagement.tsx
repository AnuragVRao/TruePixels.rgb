import React, { useState, useEffect } from 'react';
import { 
  Users, 
  ShieldCheck, 
  UserX, 
  UserCheck, 
  Trash2, 
  AlertTriangle, 
  RefreshCw, 
  KeyRound, 
  CheckCircle2, 
  ShieldAlert 
} from 'lucide-react';
import { apiRequest } from '../../api/client';
import { useAuth } from '../../context/AuthContext';
import { ErrorBanner } from '../../components/ErrorBanner';

interface UserItem {
  user_id: number;
  full_name: string;
  email: string;
  role: 'User' | 'Admin';
  account_status: 'active' | 'disabled' | 'removed';
  registered_at: string;
  is_email_verified: boolean;
}

export const AdminUserManagement: React.FC = () => {
  const { user, isAdmin } = useAuth();
  const [users, setUsers] = useState<UserItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<any>(null);
  const [actionLoadingId, setActionLoadingId] = useState<number | null>(null);
  const [feedbackMsg, setFeedbackMsg] = useState<string | null>(null);

  const fetchUsers = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiRequest<UserItem[]>('/users');
      setUsers(data);
    } catch (err: any) {
      setError(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isAdmin) {
      fetchUsers();
    }
  }, [isAdmin]);

  if (!isAdmin) {
    return null;
  }

  const handleStatusChange = async (userId: number, action: 'enable' | 'disable' | 'remove') => {
    setError(null);
    setFeedbackMsg(null);
    setActionLoadingId(userId);

    try {
      const res = await apiRequest<{ user_id: number; account_status: string }>(
        `/users/${userId}/status`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action }),
        }
      );

      setFeedbackMsg(`Successfully updated user #${userId} status to '${res.account_status}'.`);
      await fetchUsers();
    } catch (err: any) {
      setError(err);
    } finally {
      setActionLoadingId(null);
    }
  };

  const totalUsers = users.length;
  const activeUsers = users.filter((u) => u.account_status === 'active').length;
  const disabledUsers = users.filter((u) => u.account_status === 'disabled').length;
  const adminCount = users.filter((u) => u.role === 'Admin').length;

  return (
    <div className="mt-10 bg-slate-900/90 border border-amber-500/30 rounded-3xl p-6 sm:p-8 shadow-2xl shadow-amber-950/20">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-6 border-b border-slate-800">
        <div className="flex items-center gap-3.5">
          <div className="w-12 h-12 rounded-2xl bg-amber-500/10 border border-amber-500/30 flex items-center justify-center text-amber-400">
            <ShieldAlert className="w-6 h-6" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-xl font-bold text-white tracking-tight">Admin Console & User Control</h2>
              <span className="px-2.5 py-0.5 rounded-full bg-amber-500/20 border border-amber-500/40 text-[11px] font-mono font-bold text-amber-300">
                F.17 Admin Access
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-0.5">
              Live user directory, account deactivation controls, and access authorization oversight
            </p>
          </div>
        </div>

        <button
          onClick={fetchUsers}
          disabled={loading}
          className="flex items-center gap-2 px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-slate-200 border border-slate-700 transition-colors self-start sm:self-auto"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          <span>Refresh Directory</span>
        </button>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 my-6">
        <div className="p-4 rounded-2xl bg-slate-950/80 border border-slate-800/80">
          <span className="text-[11px] font-semibold text-slate-400">Total Users</span>
          <p className="text-2xl font-black text-white mt-1">{totalUsers}</p>
        </div>
        <div className="p-4 rounded-2xl bg-slate-950/80 border border-slate-800/80">
          <span className="text-[11px] font-semibold text-emerald-400">Active Accounts</span>
          <p className="text-2xl font-black text-emerald-400 mt-1">{activeUsers}</p>
        </div>
        <div className="p-4 rounded-2xl bg-slate-950/80 border border-slate-800/80">
          <span className="text-[11px] font-semibold text-amber-400">Disabled / Blocked</span>
          <p className="text-2xl font-black text-amber-400 mt-1">{disabledUsers}</p>
        </div>
        <div className="p-4 rounded-2xl bg-slate-950/80 border border-slate-800/80">
          <span className="text-[11px] font-semibold text-indigo-400">System Admins</span>
          <p className="text-2xl font-black text-indigo-400 mt-1">{adminCount}</p>
        </div>
      </div>

      <ErrorBanner error={error} onDismiss={() => setError(null)} />

      {feedbackMsg && (
        <div className="mb-4 p-3 rounded-xl bg-emerald-950/40 border border-emerald-800/40 text-xs text-emerald-300 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            <span>{feedbackMsg}</span>
          </div>
          <button onClick={() => setFeedbackMsg(null)} className="text-xs text-slate-400 hover:text-white">✕</button>
        </div>
      )}

      {/* Users Table */}
      <div className="overflow-x-auto rounded-2xl border border-slate-800 bg-slate-950/60">
        <table className="w-full text-left text-xs">
          <thead className="bg-slate-900/80 text-slate-400 uppercase font-mono text-[10px] tracking-wider border-b border-slate-800">
            <tr>
              <th className="py-3 px-4">User ID</th>
              <th className="py-3 px-4">Account</th>
              <th className="py-3 px-4">Role</th>
              <th className="py-3 px-4">Status</th>
              <th className="py-3 px-4">2FA Status</th>
              <th className="py-3 px-4 text-right">Admin Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60 text-slate-200">
            {users.map((u) => {
              const isSelf = u.user_id === user?.user_id;
              const isActionLoading = actionLoadingId === u.user_id;

              return (
                <tr key={u.user_id} className="hover:bg-slate-900/40 transition-colors">
                  <td className="py-3.5 px-4 font-mono text-slate-400">#{u.user_id}</td>
                  <td className="py-3.5 px-4">
                    <div className="font-semibold text-white">{u.full_name}</div>
                    <div className="text-[11px] text-slate-400 font-mono">{u.email}</div>
                  </td>
                  <td className="py-3.5 px-4">
                    <span
                      className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold ${
                        u.role === 'Admin'
                          ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                          : 'bg-indigo-500/10 text-indigo-300 border border-indigo-500/20'
                      }`}
                    >
                      {u.role}
                    </span>
                  </td>
                  <td className="py-3.5 px-4">
                    <span
                      className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-bold ${
                        u.account_status === 'active'
                          ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                          : u.account_status === 'disabled'
                          ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
                          : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                      }`}
                    >
                      <span className={`w-1.5 h-1.5 rounded-full ${
                        u.account_status === 'active' ? 'bg-emerald-400' : u.account_status === 'disabled' ? 'bg-amber-400' : 'bg-rose-400'
                      }`} />
                      {u.account_status}
                    </span>
                  </td>
                  <td className="py-3.5 px-4">
                    {u.is_email_verified ? (
                      <span className="text-emerald-400 flex items-center gap-1 text-[11px]">
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        <span>Verified</span>
                      </span>
                    ) : (
                      <span className="text-slate-500 text-[11px]">Unverified</span>
                    )}
                  </td>
                  <td className="py-3.5 px-4 text-right">
                    {isSelf ? (
                      <span className="text-[11px] text-slate-500 italic px-2 py-1 bg-slate-900 rounded-lg border border-slate-800">
                        Self (Protected)
                      </span>
                    ) : (
                      <div className="flex items-center justify-end gap-1.5">
                        {u.account_status === 'active' ? (
                          <button
                            onClick={() => handleStatusChange(u.user_id, 'disable')}
                            disabled={isActionLoading}
                            title="Disable account (blocks login & uploads)"
                            className="px-2.5 py-1 rounded-lg bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 border border-amber-500/30 text-[11px] font-medium transition-colors flex items-center gap-1 disabled:opacity-50"
                          >
                            <UserX className="w-3 h-3" />
                            <span>Disable</span>
                          </button>
                        ) : (
                          <button
                            onClick={() => handleStatusChange(u.user_id, 'enable')}
                            disabled={isActionLoading}
                            title="Re-enable active account status"
                            className="px-2.5 py-1 rounded-lg bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 text-[11px] font-medium transition-colors flex items-center gap-1 disabled:opacity-50"
                          >
                            <UserCheck className="w-3 h-3" />
                            <span>Enable</span>
                          </button>
                        )}

                        {u.account_status !== 'removed' && (
                          <button
                            onClick={() => {
                              if (confirm(`Are you sure you want to permanently remove user #${u.user_id} (${u.email})?`)) {
                                handleStatusChange(u.user_id, 'remove');
                              }
                            }}
                            disabled={isActionLoading}
                            title="Mark account as removed"
                            className="p-1 rounded-lg bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 border border-rose-500/30 transition-colors disabled:opacity-50"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="mt-4 p-3 rounded-xl bg-slate-950 border border-slate-800 text-[11px] text-slate-400 leading-relaxed flex items-center gap-2">
        <ShieldCheck className="w-4 h-4 text-amber-400 shrink-0" />
        <span>
          <strong>Admin Rule (PRD §5.1.5 / F.17):</strong> Disabling an account immediately prevents that user from logging in or uploading images. Admins cannot alter their own account status (self-modification guard).
        </span>
      </div>
    </div>
  );
};
