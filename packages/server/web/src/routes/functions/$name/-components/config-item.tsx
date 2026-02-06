import { cn } from "@/lib/utils";

interface ConfigItemProps {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string | null | undefined;
  mono?: boolean;
}

export function ConfigItem({ icon: Icon, label, value, mono }: ConfigItemProps) {
  return (
    <div>
      <div className="flex items-center gap-1.5 mb-0.5">
        <Icon className="w-3 h-3 text-muted-foreground" />
        <span className="text-[10px] text-muted-foreground uppercase tracking-wider">{label}</span>
      </div>
      <span className={cn("text-sm text-foreground", mono && "mono text-xs")}>
        {value ?? <span className="text-muted-foreground/60">{"\u2014"}</span>}
      </span>
    </div>
  );
}
