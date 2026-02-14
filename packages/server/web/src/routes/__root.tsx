import { createRootRoute, Outlet, useRouterState } from "@tanstack/react-router";
import { useMemo } from "react";
import {
  EventStreamProvider,
  type EventStreamSubscriptions,
} from "@/components/providers/event-stream-provider";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Sidebar } from "@/components/layout";
import { ErrorBoundary } from "@/components/shared";

export const Route = createRootRoute({
  component: RootLayout,
});

function RootLayout() {
  const router = useRouterState();
  const path = router.location.pathname;

  const streamSubscriptions = useMemo<EventStreamSubscriptions>(() => {
    if (path.startsWith("/dashboard")) {
      // Dashboard no longer hosts full live activity tables.
      // Keep only worker snapshots live for utilization cards.
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
    return { jobs: false, apis: false, apiEvents: false, workers: false };
  }, [path]);

  // Get page title from current path
  const getPageTitle = () => {
    if (path.startsWith("/dashboard")) return "Dashboard";
    if (path.startsWith("/activity")) return "Activity";
    if (path.startsWith("/workers")) return "Workers";
    if (path.startsWith("/apis")) return "APIs";
    if (path.startsWith("/functions")) return "Functions";
    if (path.startsWith("/jobs")) return "Jobs";
    return "Dashboard";
  };

  return (
    <TooltipProvider>
      <div className="app-root h-screen bg-background text-foreground flex overflow-hidden">
        <Sidebar />

        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Top Header */}
          <header className="h-14 border-b border-border flex items-center px-6 shrink-0">
            <h1 className="text-lg font-semibold text-foreground">{getPageTitle()}</h1>
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
