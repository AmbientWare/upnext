import { useState, type FormEvent } from "react";

import { useAuth } from "@/components/providers/use-auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { createDefaultRuntimeSession, verifyToken } from "@/lib/upnext-api";

interface LoginPageProps {
  mode?: "self_hosted" | "cloud_runtime";
  defaultSessionAvailable?: boolean;
  onCloudAuthenticated?: () => Promise<void> | void;
}

export function LoginPage({
  mode = "self_hosted",
  defaultSessionAvailable = false,
  onCloudAuthenticated,
}: LoginPageProps) {
  const { login } = useAuth();
  const [key, setKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const trimmed = key.trim();
    if (!trimmed) {
      return;
    }

    setLoading(true);
    setError(null);

    try {
      await verifyToken(trimmed);
      login(trimmed);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Invalid authentication token");
    } finally {
      setLoading(false);
    }
  };

  const handleCloudContinue = async () => {
    setLoading(true);
    setError(null);
    try {
      await createDefaultRuntimeSession();
      await onCloudAuthenticated?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create runtime session");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background p-8">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center">
          <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-upnext-400 to-upnext-600 shadow-2xl shadow-upnext-500/25">
            <svg
              className="h-10 w-10 text-white"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path d="M12 2L2 7l10 5 10-5-10-5z" />
              <path d="M2 17l10 5 10-5" />
              <path d="M2 12l10 5 10-5" />
            </svg>
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">UpNext</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {mode === "cloud_runtime"
              ? "Create a runtime session for the selected workspace"
              : "Enter the configured self-hosted token to continue"}
          </p>
        </div>

        {mode === "cloud_runtime" ? (
          <div className="space-y-4">
            {error ? <p className="text-sm text-destructive">{error}</p> : null}
            <Button
              type="button"
              className="w-full"
              disabled={loading || !defaultSessionAvailable}
              onClick={handleCloudContinue}
            >
              {loading ? "Connecting..." : "Continue"}
            </Button>
            {!defaultSessionAvailable ? (
              <p className="text-sm text-muted-foreground">
                Default runtime sessions are disabled for this environment.
              </p>
            ) : null}
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <Input
                type="password"
                placeholder="Authentication token"
                value={key}
                onChange={(event) => setKey(event.target.value)}
                autoFocus
                autoComplete="off"
              />
              {error ? <p className="mt-2 text-sm text-destructive">{error}</p> : null}
            </div>
            <Button type="submit" className="w-full" disabled={loading || !key.trim()}>
              {loading ? "Verifying..." : "Sign in"}
            </Button>
          </form>
        )}
      </div>
    </div>
  );
}
