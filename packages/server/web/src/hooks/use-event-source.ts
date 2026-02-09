import { useEffect, useRef } from "react";

export type EventSourceConnectionState =
  | "connecting"
  | "open"
  | "reconnecting"
  | "closed";

interface UseEventSourceOptions {
  enabled?: boolean;
  onMessage?: (event: MessageEvent) => void;
  onError?: (event: Event) => void;
  onOpen?: (event: Event) => void;
  onReconnect?: (event: Event) => void;
  onClose?: () => void;
  onStateChange?: (state: EventSourceConnectionState) => void;
  reconnectInitialDelayMs?: number;
  reconnectMaxDelayMs?: number;
}

export function useEventSource(url: string, options: UseEventSourceOptions = {}) {
  const {
    enabled = true,
    reconnectInitialDelayMs = 1_000,
    reconnectMaxDelayMs = 30_000,
  } = options;
  const sourceRef = useRef<EventSource | null>(null);
  const onMessageRef = useRef(options.onMessage);
  const onErrorRef = useRef(options.onError);
  const onOpenRef = useRef(options.onOpen);
  const onReconnectRef = useRef(options.onReconnect);
  const onCloseRef = useRef(options.onClose);
  const onStateChangeRef = useRef(options.onStateChange);

  useEffect(() => {
    onMessageRef.current = options.onMessage;
    onErrorRef.current = options.onError;
    onOpenRef.current = options.onOpen;
    onReconnectRef.current = options.onReconnect;
    onCloseRef.current = options.onClose;
    onStateChangeRef.current = options.onStateChange;
  }, [
    options.onClose,
    options.onError,
    options.onMessage,
    options.onOpen,
    options.onReconnect,
    options.onStateChange,
  ]);

  useEffect(() => {
    if (!enabled) {
      onStateChangeRef.current?.("closed");
      return;
    }

    let cancelled = false;
    let attempt = 0;
    let hasConnected = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let currentSource: EventSource | null = null;
    let currentState: EventSourceConnectionState | null = null;

    const emitState = (state: EventSourceConnectionState) => {
      if (currentState === state) {
        return;
      }
      currentState = state;
      onStateChangeRef.current?.(state);
    };

    const clearReconnectTimer = () => {
      if (!reconnectTimer) return;
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    };

    const closeCurrentSource = (emitClose: boolean) => {
      if (!currentSource) return;
      currentSource.close();
      currentSource = null;
      sourceRef.current = null;
      if (emitClose) {
        onCloseRef.current?.();
      }
    };

    const scheduleReconnect = () => {
      if (cancelled || reconnectTimer) return;
      const baseDelay = Math.min(
        reconnectInitialDelayMs * 2 ** attempt,
        reconnectMaxDelayMs
      );
      const jitterFactor = 0.85 + Math.random() * 0.3;
      const delay = Math.max(Math.round(baseDelay * jitterFactor), 0);
      attempt += 1;
      emitState("reconnecting");
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        createSource(true);
      }, delay);
    };

    const createSource = (isReconnectAttempt: boolean) => {
      if (cancelled) return;
      clearReconnectTimer();
      emitState(isReconnectAttempt ? "reconnecting" : "connecting");

      const source = new EventSource(url);
      currentSource = source;
      sourceRef.current = source;

      source.addEventListener("open", (event) => {
        if (cancelled) return;
        const reconnected = hasConnected;
        hasConnected = true;
        attempt = 0;
        emitState("open");
        onOpenRef.current?.(event);
        if (reconnected) {
          onReconnectRef.current?.(event);
        }
      });
      source.addEventListener("message", (event) =>
        onMessageRef.current?.(event as MessageEvent)
      );
      source.addEventListener("error", (event) => {
        onErrorRef.current?.(event);
        if (cancelled) return;
        closeCurrentSource(false);
        scheduleReconnect();
      });
    };

    createSource(false);

    return () => {
      cancelled = true;
      clearReconnectTimer();
      closeCurrentSource(true);
      emitState("closed");
      sourceRef.current = null;
    };
  }, [enabled, reconnectInitialDelayMs, reconnectMaxDelayMs, url]);

  return sourceRef;
}
