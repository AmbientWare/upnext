import { useEffect, useRef } from "react";

interface UseEventSourceOptions {
  enabled?: boolean;
  onMessage?: (event: MessageEvent) => void;
  onError?: (event: Event) => void;
}

export function useEventSource(url: string, options: UseEventSourceOptions = {}) {
  const { enabled = true } = options;
  const sourceRef = useRef<EventSource | null>(null);
  const onMessageRef = useRef(options.onMessage);
  const onErrorRef = useRef(options.onError);

  onMessageRef.current = options.onMessage;
  onErrorRef.current = options.onError;

  useEffect(() => {
    if (!enabled) {
      return;
    }

    const source = new EventSource(url);
    sourceRef.current = source;

    source.addEventListener("message", (e) => onMessageRef.current?.(e));
    source.addEventListener("error", (e) => onErrorRef.current?.(e));

    return () => {
      source.close();
      sourceRef.current = null;
    };
  }, [enabled, url]);

  return sourceRef;
}
