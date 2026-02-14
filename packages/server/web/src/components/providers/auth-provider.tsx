import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  getStoredApiKey,
  setStoredApiKey,
  clearStoredApiKey,
} from "@/lib/auth";

interface AuthContextValue {
  /** The current API key, or null when not authenticated. */
  apiKey: string | null;
  /** Whether the user is currently authenticated. */
  isAuthenticated: boolean;
  /** Whether the current user is an admin. */
  isAdmin: boolean;
  /** Store API key and mark as authenticated. */
  login: (key: string) => void;
  /** Clear stored API key and mark as unauthenticated. */
  logout: () => void;
  /** Set admin status (called after verify). */
  setIsAdmin: (value: boolean) => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [apiKey, setApiKey] = useState<string | null>(getStoredApiKey);
  const [isAdmin, setIsAdmin] = useState(false);

  const login = useCallback((key: string) => {
    setStoredApiKey(key);
    setApiKey(key);
  }, []);

  const logout = useCallback(() => {
    clearStoredApiKey();
    setApiKey(null);
    setIsAdmin(false);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      apiKey,
      isAuthenticated: apiKey !== null,
      isAdmin,
      login,
      logout,
      setIsAdmin,
    }),
    [apiKey, isAdmin, login, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
