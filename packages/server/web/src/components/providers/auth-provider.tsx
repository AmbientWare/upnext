import { useCallback, useMemo, useState, type ReactNode } from "react";

import {
  clearStoredAuthToken,
  getStoredAuthToken,
  setStoredAuthToken,
} from "@/lib/auth";

import { AuthContext, type AuthContextValue } from "./auth-context";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [authToken, setAuthToken] = useState<string | null>(() =>
    getStoredAuthToken()
  );

  const login = useCallback((token: string) => {
    setStoredAuthToken(token);
    setAuthToken(token);
  }, []);

  const logout = useCallback(() => {
    clearStoredAuthToken();
    setAuthToken(null);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      authToken,
      isAuthenticated: authToken !== null,
      login,
      logout,
    }),
    [authToken, login, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
