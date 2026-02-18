import { createContext } from "react";

export interface AuthContextValue {
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

export const AuthContext = createContext<AuthContextValue | null>(null);
