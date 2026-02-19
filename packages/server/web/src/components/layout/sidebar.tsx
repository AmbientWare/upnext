import { Link, useRouterState } from "@tanstack/react-router";
import { cn } from "@/lib/utils";
import { Activity, LayoutDashboard, Code2, Lock, Server, Globe } from "lucide-react";

const navItems = [
  { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
  { label: "Activity", href: "/activity", icon: Activity },
  { label: "APIs", href: "/apis", icon: Globe },
  { label: "Workers", href: "/workers", icon: Server },
  { label: "Functions", href: "/functions", icon: Code2 },
  { label: "Secrets", href: "/secrets", icon: Lock },
];

export function Sidebar() {
  const router = useRouterState();
  const currentPath = router.location.pathname;

  return (
    <aside className="w-48 bg-background border-r border-border flex flex-col">
      {/* Logo */}
      <div className="h-14 flex items-center gap-2 px-4 border-b border-border">
        <img src="/upnext-logo.png" alt="UpNext" className="size-7" />
        <span className="text-base font-bold inline-flex">
          <span className="text-upnext">Up</span>
          <span className="text-foreground">Next</span>
        </span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-3 px-2">
        {navItems.map((item) => {
          const isActive = currentPath.startsWith(item.href);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              to={item.href}
              className={cn(
                "flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors mb-1",
                isActive
                  ? "bg-upnext-500/15 text-upnext"
                  : "text-muted-foreground hover:text-foreground hover:bg-accent"
              )}
            >
              <Icon className="w-4 h-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
