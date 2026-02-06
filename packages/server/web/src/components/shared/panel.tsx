import { cn } from "@/lib/utils";

interface PanelProps {
  title?: string;
  titleRight?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  contentClassName?: string;
  noPadding?: boolean;
}

export function Panel({ title, titleRight, children, className, contentClassName, noPadding }: PanelProps) {
  return (
    <div className={cn("matrix-panel rounded", className)}>
      {title && (
        <div className="matrix-panel-header px-3 py-2 flex items-center justify-between">
          <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">{title}</span>
          {titleRight}
        </div>
      )}
      <div className={cn(!noPadding && "p-3", contentClassName)}>{children}</div>
    </div>
  );
}
