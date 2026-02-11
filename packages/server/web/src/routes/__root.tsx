import { createRootRoute, Outlet, useRouterState } from "@tanstack/react-router";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Sidebar } from "@/components/layout";

export const Route = createRootRoute({
  component: RootLayout,
});

function RootLayout() {
  const router = useRouterState();

  // Get page title from current path
  const getPageTitle = () => {
    const path = router.location.pathname;
    if (path.startsWith("/dashboard")) return "Dashboard";
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
            <div key={router.location.pathname} className="route-fade h-full">
              <Outlet />
            </div>
          </main>
        </div>
      </div>
    </TooltipProvider>
  );
}
