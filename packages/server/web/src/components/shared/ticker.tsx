import { TrendingUp, TrendingDown, Minus } from "lucide-react";
import { cn } from "@/lib/utils";

export interface TickerItem {
  label: string;
  value: string;
  trend?: "up" | "down" | "neutral";
}

interface TickerProps {
  items: TickerItem[];
  className?: string;
}

export function Ticker({ items, className }: TickerProps) {
  return (
    <div className={cn("bg-background border-b border-input py-1 overflow-hidden", className)}>
      <div className="ticker whitespace-nowrap">
        {[...Array(2)].map((_, i) => (
          <span key={i} className="inline-flex items-center gap-8 mr-8">
            {items.map((item, j) => (
              <span key={j} className="inline-flex items-center gap-2">
                <span className="text-muted-foreground">{item.label}</span>
                <span
                  className={cn(
                    "font-medium mono",
                    item.trend === "up"
                      ? "text-emerald-400"
                      : item.trend === "down"
                        ? "text-red-400"
                        : "text-foreground"
                  )}
                >
                  {item.value}
                </span>
                {item.trend === "up" && <TrendingUp className="w-3 h-3 text-emerald-400" />}
                {item.trend === "down" && <TrendingDown className="w-3 h-3 text-red-400" />}
                {item.trend === "neutral" && <Minus className="w-3 h-3 text-muted-foreground" />}
              </span>
            ))}
          </span>
        ))}
      </div>
    </div>
  );
}
