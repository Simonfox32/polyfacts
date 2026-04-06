"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

interface ApiUser {
  id: string;
  email: string;
  username: string;
  is_admin: boolean;
}

interface AuthResponse {
  access_token: string;
  user: ApiUser;
}

export interface User {
  user_id: string;
  email: string;
  username: string;
  is_admin: boolean;
}

interface AuthContextType {
  user: User | null;
  token: string | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, username: string, password: string) => Promise<void>;
  logout: () => void;
  isAdmin: boolean;
}

const TOKEN_STORAGE_KEY = "polyfacts_token";
const AuthContext = createContext<AuthContextType | null>(null);

function normalizeUser(user: ApiUser): User {
  return {
    user_id: user.id,
    email: user.email,
    username: user.username,
    is_admin: user.is_admin,
  };
}

async function parseError(response: Response, fallback: string) {
  try {
    const data = await response.json();
    return data.detail || fallback;
  } catch {
    return fallback;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const storedToken = window.localStorage.getItem(TOKEN_STORAGE_KEY);
    if (!storedToken) {
      setLoading(false);
      return;
    }

    let cancelled = false;
    setToken(storedToken);

    fetch("/api/auth/me", {
      headers: {
        Authorization: `Bearer ${storedToken}`,
      },
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(await parseError(response, "Session expired"));
        }
        return response.json();
      })
      .then((data: ApiUser) => {
        if (!cancelled) {
          setUser(normalizeUser(data));
        }
      })
      .catch(() => {
        if (!cancelled) {
          window.localStorage.removeItem(TOKEN_STORAGE_KEY);
          setToken(null);
          setUser(null);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const response = await fetch("/api/auth/login", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ email, password }),
    });

    if (!response.ok) {
      throw new Error(await parseError(response, "Login failed"));
    }

    const data: AuthResponse = await response.json();
    window.localStorage.setItem(TOKEN_STORAGE_KEY, data.access_token);
    setToken(data.access_token);
    setUser(normalizeUser(data.user));
  }, []);

  const register = useCallback(async (email: string, username: string, password: string) => {
    const response = await fetch("/api/auth/register", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ email, username, password }),
    });

    if (!response.ok) {
      throw new Error(await parseError(response, "Registration failed"));
    }

    const data: AuthResponse = await response.json();
    window.localStorage.setItem(TOKEN_STORAGE_KEY, data.access_token);
    setToken(data.access_token);
    setUser(normalizeUser(data.user));
  }, []);

  const logout = useCallback(() => {
    window.localStorage.removeItem(TOKEN_STORAGE_KEY);
    setToken(null);
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({
      user,
      token,
      loading,
      login,
      register,
      logout,
      isAdmin: user?.is_admin ?? false,
    }),
    [loading, login, logout, register, token, user]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
}
