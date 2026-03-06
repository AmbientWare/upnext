import { createRootRoute, Outlet, useRouterState } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import {
  EventStreamProvider,
  type EventStreamSubscriptions,
} from "@/components/providers/event-stream-provider";
import { useAuth } from "@/components/providers/use-auth";
import { LoginPage } from "@/components/login-page";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Button } from "@/components/ui/button";
import { Sidebar } from "@/components/layout";
import { ErrorBoundary } from "@/components/shared";
import { env } from "@/lib/env";
import { clearRuntimeSession, verifyToken } from "@/lib/upnext-api";

type AuthStatus = {
  auth_enabled: boolean;
  runtime_mode: "self_hosted" | "cloud_runtime";
  default_session_available: boolean;
};

export const Route = createRootRoute({
  component: RootLayout,
});

async function fetchAuthStatus(): Promise<AuthStatus> {
  const response = await fetch(`${env.VITE_API_BASE_URL}/auth/status`, {
    credentials: "include",
  });
  if (!response.ok) {
    return {
      auth_enabled: true,
      runtime_mode: "self_hosted",
      default_session_available: false,
    };
  }
  return response.json();
}

function RootLayout() {
  const router = useRouterState();
  const path = router.location.pathname;
  const { isAuthenticated, logout } = useAuth();
  const { data: authStatus, isLoading: authLoading } = useQuery({
    queryKey: ["auth", "status"],
    queryFn: fetchAuthStatus,
    staleTime: 60_000,
    retry: 1,
  });
  const {
    data: verifiedSession,
    isLoading: verifyLoading,
    isError: verifyError,
    refetch: refetchVerify,
  } = useQuery({
    queryKey: ["auth", "verify", authStatus?.runtime_mode],
    queryFn: () => verifyToken(),
    enabled:
      !!authStatus?.auth_enabled && authStatus.runtime_mode === "cloud_runtime",
    retry: false,
    staleTime: 30_000,
  });

  const authEnabled = authStatus?.auth_enabled ?? true;
  const runtimeMode = authStatus?.runtime_mode ?? "self_hosted";
  const defaultSessionAvailable = authStatus?.default_session_available ?? false;

  if (authLoading || (runtimeMode === "cloud_runtime" && verifyLoading)) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" />
      </div>
    );
  }

  if (authEnabled && runtimeMode === "self_hosted" && !isAuthenticated) {
    return <LoginPage />;
  }

  if (authEnabled && runtimeMode === "cloud_runtime" && verifyError) {
    return (
      <LoginPage
        mode="cloud_runtime"
        defaultSessionAvailable={defaultSessionAvailable}
        onCloudAuthenticated={async () => {
          await refetchVerify();
        }}
      />
    );
  }

  const streamSubscriptions = getStreamSubscriptions(path);

  return (
    <TooltipProvider>
      <div className="app-root h-screen bg-background text-foreground flex overflow-hidden">
        <Sidebar />

        <div className="flex-1 flex flex-col overflow-hidden">
          <header className="h-14 border-b border-border flex items-center px-6 shrink-0">
            <h1 className="text-lg font-semibold text-foreground">{getPageTitle(path)}</h1>
            {authEnabled &&
            runtimeMode === "self_hosted" &&
            isAuthenticated ? (
              <Button variant="ghost" size="sm" className="ml-auto" onClick={logout}>
                Sign out
              </Button>
            ) : null}
            {authEnabled &&
            runtimeMode === "cloud_runtime" &&
            verifiedSession?.scope ? (
              <div className="ml-auto flex items-center gap-3">
                <div className="text-right text-sm">
                  <div className="font-medium text-foreground">
                    {verifiedSession.scope.name ?? verifiedSession.scope.subject ?? "User"}
                  </div>
                  <div className="text-muted-foreground">
                    {verifiedSession.scope.workspace_id}
                  </div>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={async () => {
                    await clearRuntimeSession();
                    await refetchVerify();
                  }}
                >
                  Sign out
                </Button>
              </div>
            ) : null}
          </header>

          <main className="flex-1 overflow-hidden">
            <ErrorBoundary>
              <EventStreamProvider streams={streamSubscriptions} pauseWhenHidden>
                <div key={router.location.pathname} className="route-fade h-full">
                  <Outlet />
                </div>
              </EventStreamProvider>
            </ErrorBoundary>
          </main>
        </div>
      </div>
    </TooltipProvider>
  );
}

function getStreamSubscriptions(path: string): EventStreamSubscriptions {
  if (path.startsWith("/dashboard")) {
    return { jobs: false, apis: false, apiEvents: false, workers: true };
  }
  if (path.startsWith("/activity")) {
    return { jobs: true, apis: false, apiEvents: true, workers: false };
  }
  if (path.startsWith("/workers")) {
    return { jobs: false, apis: false, apiEvents: false, workers: true };
  }
  if (path.startsWith("/apis")) {
    return { jobs: false, apis: true, apiEvents: true, workers: false };
  }
  if (path.startsWith("/functions")) {
    return { jobs: true, apis: false, apiEvents: false, workers: false };
  }
  if (path.startsWith("/jobs")) {
    return { jobs: true, apis: false, apiEvents: false, workers: false };
  }
  if (path.startsWith("/secrets")) {
    return { jobs: false, apis: false, apiEvents: false, workers: false };
  }
  return { jobs: false, apis: false, apiEvents: false, workers: false };
}

function getPageTitle(path: string): string {
  if (path.startsWith("/dashboard")) return "Dashboard";
  if (path.startsWith("/activity")) return "Activity";
  if (path.startsWith("/workers")) return "Workers";
  if (path.startsWith("/apis")) return "APIs";
  if (path.startsWith("/functions")) return "Functions";
  if (path.startsWith("/jobs")) return "Jobs";
  if (path.startsWith("/secrets")) return "Secrets";
  return "Dashboard";
}
