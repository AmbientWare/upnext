import {
  useCallback,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  getStoredApiKey,
  setStoredApiKey,
  clearStoredApiKey,
} from "@/lib/auth";
import { AuthContext, type AuthContextValue } from "./auth-context";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [apiKey, setApiKey] = useState<string | null>(getStoredApiKey);

  const login = useCallback((key: string) => {
    setStoredApiKey(key);
    setApiKey(key);
  }, []);

  const logout = useCallback(() => {
    clearStoredApiKey();
    setApiKey(null);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      apiKey,
      isAuthenticated: apiKey !== null,
      login,
      logout,
    }),
    [apiKey, login, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
