import { cn } from "@/lib/utils";

interface DetailPageLayoutProps {
  children: React.ReactNode;
  className?: string;
}

export function DetailPageLayout({ children, className }: DetailPageLayoutProps) {
  return (
    <div className={cn("p-4 flex flex-col gap-3 h-full overflow-auto xl:overflow-hidden", className)}>
      {children}
    </div>
  );
}
