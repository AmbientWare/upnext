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
    if (path.startsWith("/jobs")) return "Jobs";
    if (path.startsWith("/functions")) return "Functions";
    if (path.startsWith("/workers")) return "Workers";
    if (path.startsWith("/apis")) return "APIs";
    return "Dashboard";
  };

  return (
    <TooltipProvider>
      <div className="app-root h-screen bg-[#0c0c0c] text-[#e0e0e0] flex overflow-hidden">
        <style>{`
          @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap');

          .app-root {
            font-family: 'IBM Plex Sans', sans-serif;
            font-size: 13px;
          }

          .app-root code, .app-root .mono {
            font-family: 'IBM Plex Mono', monospace;
          }

          .matrix-panel {
            background: #141414;
            border: 1px solid #2a2a2a;
          }

          .matrix-panel-header {
            background: linear-gradient(180deg, #1a1a1a 0%, #141414 100%);
            border-bottom: 1px solid #2a2a2a;
          }

          .matrix-cell {
            border-right: 1px solid #1e1e1e;
            border-bottom: 1px solid #1e1e1e;
          }

          .matrix-row:hover {
            background: #1a1a1a;
          }

          .spark-line {
            stroke-dasharray: 100;
            stroke-dashoffset: 100;
            animation: drawLine 1s ease-out forwards;
          }

          @keyframes drawLine {
            to { stroke-dashoffset: 0; }
          }

          .heat-cell {
            transition: all 0.2s ease;
          }

          .heat-cell:hover {
            transform: scale(1.1);
            z-index: 10;
          }
        `}</style>

        <Sidebar />

        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Top Header */}
          <header className="h-14 border-b border-[#1e1e1e] flex items-center px-6 shrink-0">
            <h1 className="text-lg font-semibold text-[#e0e0e0]">{getPageTitle()}</h1>
          </header>

          {/* Main Content */}
          <main className="flex-1 overflow-hidden">
            <Outlet />
          </main>
        </div>
      </div>
    </TooltipProvider>
  );
}
