import { createContext } from "react";

export interface AuthContextValue {
  authToken: string | null;
  isAuthenticated: boolean;
  login: (token: string) => void;
  logout: () => void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);
