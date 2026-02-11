import { useEffect, useRef, useState } from "react";

export type EventSourceConnectionState =
  | "connecting"
  | "open"
  | "reconnecting"
  | "closed";

interface UseEventSourceOptions {
  enabled?: boolean;
  pauseWhenHidden?: boolean;
  onMessage?: (event: MessageEvent) => void;
  onError?: (event: Event) => void;
  onOpen?: (event: Event) => void;
  onReconnect?: (event: Event) => void;
  onClose?: () => void;
  onStateChange?: (state: EventSourceConnectionState) => void;
  onIdle?: () => void;
  reconnectInitialDelayMs?: number;
  reconnectMaxDelayMs?: number;
  idleTimeoutMs?: number;
  reconnectOnIdle?: boolean;
}

export function useEventSource(url: string, options: UseEventSourceOptions = {}) {
  const {
    enabled = true,
    pauseWhenHidden = false,
    reconnectInitialDelayMs = 1_000,
    reconnectMaxDelayMs = 30_000,
    idleTimeoutMs = 0,
    reconnectOnIdle = true,
  } = options;
  const [isPageVisible, setIsPageVisible] = useState(() =>
    typeof document === "undefined" ? true : document.visibilityState === "visible"
  );
  const sourceRef = useRef<EventSource | null>(null);
  const onMessageRef = useRef(options.onMessage);
  const onErrorRef = useRef(options.onError);
  const onOpenRef = useRef(options.onOpen);
  const onReconnectRef = useRef(options.onReconnect);
  const onCloseRef = useRef(options.onClose);
  const onStateChangeRef = useRef(options.onStateChange);
  const onIdleRef = useRef(options.onIdle);

  useEffect(() => {
    onMessageRef.current = options.onMessage;
    onErrorRef.current = options.onError;
    onOpenRef.current = options.onOpen;
    onReconnectRef.current = options.onReconnect;
    onCloseRef.current = options.onClose;
    onStateChangeRef.current = options.onStateChange;
    onIdleRef.current = options.onIdle;
  }, [
    options.onClose,
    options.onError,
    options.onIdle,
    options.onMessage,
    options.onOpen,
    options.onReconnect,
    options.onStateChange,
  ]);

  useEffect(() => {
    if (!pauseWhenHidden || typeof document === "undefined") {
      return;
    }

    const handleVisibilityChange = () => {
      setIsPageVisible(document.visibilityState === "visible");
    };
    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [pauseWhenHidden]);

  const effectiveEnabled = enabled && (!pauseWhenHidden || isPageVisible);

  useEffect(() => {
    if (!effectiveEnabled) {
      onStateChangeRef.current?.("closed");
      return;
    }

    let cancelled = false;
    let attempt = 0;
    let hasConnected = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let idleTimer: ReturnType<typeof setTimeout> | null = null;
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

    const clearIdleTimer = () => {
      if (!idleTimer) return;
      clearTimeout(idleTimer);
      idleTimer = null;
    };

    const scheduleIdleTimeout = () => {
      clearIdleTimer();
      if (idleTimeoutMs <= 0) return;
      idleTimer = setTimeout(() => {
        if (cancelled) return;
        onIdleRef.current?.();
        if (reconnectOnIdle) {
          closeCurrentSource(false);
          scheduleReconnect();
        }
      }, idleTimeoutMs);
    };

    const closeCurrentSource = (emitClose: boolean) => {
      if (!currentSource) return;
      currentSource.close();
      currentSource = null;
      sourceRef.current = null;
      if (emitClose) {
        onCloseRef.current?.();
      }
      clearIdleTimer();
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
        scheduleIdleTimeout();
        onOpenRef.current?.(event);
        if (reconnected) {
          onReconnectRef.current?.(event);
        }
      });
      source.addEventListener("message", (event) => {
        scheduleIdleTimeout();
        onMessageRef.current?.(event as MessageEvent);
      });
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
      clearIdleTimer();
      closeCurrentSource(true);
      emitState("closed");
      sourceRef.current = null;
    };
  }, [
    effectiveEnabled,
    idleTimeoutMs,
    reconnectOnIdle,
    reconnectInitialDelayMs,
    reconnectMaxDelayMs,
    url,
  ]);

  return sourceRef;
}
