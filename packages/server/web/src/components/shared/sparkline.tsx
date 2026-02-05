interface SparklineProps {
  data: number[];
  color?: string;
  height?: number;
  className?: string;
  showLabels?: boolean;
  labelStart?: string;
  labelEnd?: string;
}

export function Sparkline({
  data,
  color = "#10b981",
  height = 48,
  className,
  showLabels = true,
  labelStart = "-24h",
  labelEnd = "now",
}: SparklineProps) {
  const max = Math.max(...data);
  const points = data
    .map((d, i) => {
      const x = (i / (data.length - 1)) * 100;
      const y = 28 - (d / max) * 26;
      return `${x},${y}`;
    })
    .join(" ");

  return (
    <div className={className}>
      <svg viewBox="0 0 100 30" style={{ height }} className="w-full">
        <polyline fill="none" stroke={color} strokeWidth="1.5" className="spark-line" points={points} />
      </svg>
      {showLabels && (
        <div className="flex justify-between text-[9px] text-[#555] mono mt-1">
          <span>{labelStart}</span>
          <span>{labelEnd}</span>
        </div>
      )}
    </div>
  );
}
