import React, { createContext, useContext, useState, useEffect } from 'react';
import { apiRequest, UserSession } from '../api/client';

interface AuthContextType {
  token: string | null;
  user: UserSession | null;
  isAuthenticated: boolean;
  isAdmin: boolean;
  login: (token: string) => Promise<void>;
  logout: () => void;
  refreshProfile: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [token, setToken] = useState<string | null>(localStorage.getItem('tp_token'));
  const [user, setUser] = useState<UserSession | null>(null);

  const fetchProfile = async (authToken: string) => {
    try {
      const data = await apiRequest<UserSession>('/auth/me', {}, authToken);
      setUser(data);
    } catch (err) {
      console.error('Failed to load user profile:', err);
      logout();
    }
  };

  useEffect(() => {
    if (token) {
      fetchProfile(token);
    } else {
      setUser(null);
    }
  }, [token]);

  const login = async (newToken: string) => {
    localStorage.setItem('tp_token', newToken);
    setToken(newToken);
    await fetchProfile(newToken);
  };

  const logout = () => {
    localStorage.removeItem('tp_token');
    setToken(null);
    setUser(null);
  };

  const refreshProfile = async () => {
    if (token) {
      await fetchProfile(token);
    }
  };

  return (
    <AuthContext.Provider
      value={{
        token,
        user,
        isAuthenticated: !!token && !!user,
        isAdmin: user?.role === 'Admin',
        login,
        logout,
        refreshProfile,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
