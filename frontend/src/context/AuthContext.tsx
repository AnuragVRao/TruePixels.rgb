import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { ApiError, apiRequest, getToken, onUnauthorized, setToken } from '../api/client';
import type { Me } from '../api/types';

interface AuthContextType {
  user: Me | null;
  loading: boolean;
  isAuthenticated: boolean;
  isAdmin: boolean;
  /** Store a token from login / OTP verification and load the profile. */
  signIn: (token: string) => Promise<void>;
  signOut: () => Promise<void>;
  /** @deprecated M1's original components (no longer rendered) - use signIn / signOut. */
  login: (token: string) => Promise<void>;
  /** @deprecated */
  logout: () => Promise<void>;
  /** @deprecated read the session token through api/client instead. */
  token: string | null;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode; onExpired?: () => void }> = ({
  children,
  onExpired,
}) => {
  const [user, setUser] = useState<Me | null>(null);
  const [loading, setLoading] = useState<boolean>(() => getToken() !== null);

  const loadProfile = useCallback(async () => {
    if (!getToken()) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      setUser(await apiRequest<Me>('/auth/me'));
    } catch (err) {
      // Only a 401 means the session is gone. A request aborted by a page
      // reload/navigation, or a network blip, must NOT sign the user out
      // (found by the browser run: a reload mid-request deleted the token).
      if (err instanceof ApiError && err.status === 401) setToken(null);
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  // Latest callback in a ref: the router's navigate (inside onExpired) changes
  // on every navigation, and must not re-run the session check each time.
  const expiredRef = useRef(onExpired);
  expiredRef.current = onExpired;

  useEffect(() => {
    onUnauthorized(() => {
      setUser(null);
      expiredRef.current?.();
    });
    void loadProfile();
    return () => onUnauthorized(null);
  }, [loadProfile]);

  const signIn = useCallback(async (token: string) => {
    setToken(token);
    setLoading(true);
    await loadProfile();
  }, [loadProfile]);

  const signOut = useCallback(async () => {
    try {
      if (getToken()) await apiRequest('/auth/logout', { method: 'POST' });
    } catch {
      /* the session is dropped locally either way */
    }
    setToken(null);
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        isAuthenticated: user !== null,
        isAdmin: user?.role === 'Admin',
        signIn,
        signOut,
        login: signIn,
        logout: signOut,
        token: getToken(),
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = (): AuthContextType => {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within an AuthProvider');
  return context;
};
