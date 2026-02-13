import { cn } from "@/lib/utils";

interface PanelProps {
  title?: string;
  titleCenter?: React.ReactNode;
  titleRight?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  contentClassName?: string;
  noPadding?: boolean;
}

export function Panel({
  title,
  titleCenter,
  titleRight,
  children,
  className,
  contentClassName,
  noPadding,
}: PanelProps) {
  return (
    <div className={cn("matrix-panel rounded", className)}>
      {title && (
        <div
          className={cn(
            "matrix-panel-header px-3 py-1.5 min-h-11",
            titleCenter ? "grid grid-cols-[1fr_auto_1fr] items-center gap-2" : "flex items-center justify-between"
          )}
        >
          <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">{title}</span>
          {titleCenter ? <div className="justify-self-center">{titleCenter}</div> : null}
          {titleRight ? <div className={cn(titleCenter && "justify-self-end")}>{titleRight}</div> : null}
        </div>
      )}
      <div className={cn(!noPadding && "p-3", contentClassName)}>{children}</div>
    </div>
  );
}
