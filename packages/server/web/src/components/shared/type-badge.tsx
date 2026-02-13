import { cn } from "@/lib/utils";

interface TypeBadgeProps {
  label: string;
  color: "blue" | "violet" | "amber" | "cyan" | "emerald" | "red";
}

const colorStyles: Record<TypeBadgeProps["color"], string> = {
  blue: "bg-blue-500/15 text-blue-400 border-blue-500/25",
  violet: "bg-violet-500/15 text-violet-400 border-violet-500/25",
  amber: "bg-amber-500/15 text-amber-400 border-amber-500/25",
  cyan: "bg-cyan-500/15 text-cyan-400 border-cyan-500/25",
  emerald: "bg-emerald-500/15 text-emerald-400 border-emerald-500/25",
  red: "bg-red-500/15 text-red-400 border-red-500/25",
};

export function TypeBadge({ label, color }: TypeBadgeProps) {
  return (
    <span
      className={cn(
        "text-[10px] px-2 py-0.5 rounded border font-medium uppercase shrink-0",
        colorStyles[color]
      )}
    >
      {label}
    </span>
  );
}
