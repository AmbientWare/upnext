import { useEffect } from "react";
import { createRootRoute, Link, Outlet, useRouterState } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import {
  EventStreamProvider,
  type EventStreamSubscriptions,
} from "@/components/providers/event-stream-provider";
import { useAuth } from "@/components/providers/auth-provider";
import { LoginPage } from "@/components/login-page";
import { verifyAuth } from "@/lib/upnext-api";
import { env } from "@/lib/env";
import { TooltipProvider } from "@/components/ui/tooltip";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { Sidebar } from "@/components/layout";
import { ErrorBoundary } from "@/components/shared";
import { CircleUserIcon, LogOutIcon, ShieldCheckIcon } from "lucide-react";

export const Route = createRootRoute({
  component: RootLayout,
});

/** Check whether the server has auth enabled (unauthenticated endpoint). */
async function fetchAuthStatus(): Promise<{ auth_enabled: boolean }> {
  const res = await fetch(`${env.VITE_API_BASE_URL}/auth/status`);
  if (!res.ok) {
    // If endpoint doesn't exist yet or server is down, assume auth enabled
    return { auth_enabled: true };
  }
  return res.json();
}

function RootLayout() {
  const router = useRouterState();
  const path = router.location.pathname;
  const { isAuthenticated, isAdmin, logout, setIsAdmin } = useAuth();

  const { data: authStatus, isLoading: authLoading } = useQuery({
    queryKey: ["auth", "status"],
    queryFn: fetchAuthStatus,
    staleTime: 60_000,
    retry: 1,
  });

  // Fetch user info (including isAdmin) when authenticated
  const { data: verifyData } = useQuery({
    queryKey: ["auth", "verify"],
    queryFn: verifyAuth,
    enabled: isAuthenticated,
    staleTime: 5 * 60_000,
    retry: 1,
  });

  useEffect(() => {
    if (verifyData?.user) {
      setIsAdmin(verifyData.user.is_admin);
    }
  }, [verifyData, setIsAdmin]);

  const authEnabled = authStatus?.auth_enabled ?? true;

  // Show login page if auth is enabled and user is not authenticated
  if (authLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" />
      </div>
    );
  }

  if (authEnabled && !isAuthenticated) {
    return <LoginPage />;
  }

  const streamSubscriptions = getStreamSubscriptions(path);

  return (
    <TooltipProvider>
      <div className="app-root h-screen bg-background text-foreground flex overflow-hidden">
        <Sidebar />

        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Top Header */}
          <header className="h-14 border-b border-border flex items-center px-6 shrink-0">
            <h1 className="text-lg font-semibold text-foreground">{getPageTitle(path)}</h1>
            <div className="ml-auto">
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="icon" className="rounded-full">
                    <CircleUserIcon className="h-5 w-5" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  {isAdmin && (
                    <>
                      <DropdownMenuItem asChild>
                        <Link to="/admin">
                          <ShieldCheckIcon className="mr-2 h-4 w-4" />
                          Admin
                        </Link>
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                    </>
                  )}
                  <DropdownMenuItem onClick={logout}>
                    <LogOutIcon className="mr-2 h-4 w-4" />
                    Logout
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </header>

          {/* Main Content */}
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
  if (path.startsWith("/admin")) {
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
  if (path.startsWith("/admin")) return "Admin";
  return "Dashboard";
}
