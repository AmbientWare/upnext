import { useEffect, useMemo, useRef, useState } from "react";

const DEFAULT_DURATION = 500;

type ParsedValue = {
  value: number;
  decimals: number;
  prefix: string;
  suffix: string;
};

const parseValue = (input: string | number): ParsedValue | null => {
  if (typeof input === "number") {
    const stringValue = input.toString();
    const decimals = stringValue.includes(".")
      ? stringValue.split(".")[1]?.length ?? 0
      : 0;
    return { value: input, decimals, prefix: "", suffix: "" };
  }

  const trimmed = input.trim();
  if (!trimmed) return null;
  const matches = trimmed.match(/-?\d+(\.\d+)?/g);
  if (!matches || matches.length !== 1) {
    return null;
  }
  const match = matches[0];
  const index = trimmed.indexOf(match);
  const prefix = trimmed.slice(0, index);
  const suffix = trimmed.slice(index + match.length);
  const decimals = match.includes(".") ? match.split(".")[1]?.length ?? 0 : 0;
  const value = Number.parseFloat(match);
  if (Number.isNaN(value)) return null;

  return { value, decimals, prefix, suffix };
};

const easeOutCubic = (t: number) => 1 - Math.pow(1 - t, 3);

export function useAnimatedNumber(value: string | number, duration = DEFAULT_DURATION) {
  const fallbackDisplay = typeof value === "number" ? value.toString() : value;
  const parsedValue = useMemo(() => parseValue(value), [value]);
  const [display, setDisplay] = useState<string>(fallbackDisplay);
  const previous = useRef<ParsedValue | null>(parseValue(value));
  const frame = useRef<number | null>(null);

  useEffect(() => {
    if (!parsedValue) {
      previous.current = null;
      return;
    }

    const startParsed = previous.current ?? parsedValue;
    const startValue = startParsed.value;
    const endValue = parsedValue.value;
    const decimals = parsedValue.decimals;

    if (frame.current) {
      cancelAnimationFrame(frame.current);
    }

    const start = performance.now();

    const tick = (now: number) => {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      const eased = easeOutCubic(progress);
      const currentValue = startValue + (endValue - startValue) * eased;
      const formatted = currentValue.toFixed(decimals);
      setDisplay(`${parsedValue.prefix}${formatted}${parsedValue.suffix}`);
      if (progress < 1) {
        frame.current = requestAnimationFrame(tick);
      }
    };

    frame.current = requestAnimationFrame(tick);
    previous.current = parsedValue;

    return () => {
      if (frame.current) {
        cancelAnimationFrame(frame.current);
      }
    };
  }, [duration, parsedValue]);

  return parsedValue ? display : fallbackDisplay;
}
