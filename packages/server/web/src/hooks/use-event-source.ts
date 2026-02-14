import { useEffect, useRef, useState } from "react";
import { getStoredApiKey } from "@/lib/auth";

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

/**
 * SSE hook backed by fetch() so we can send an Authorization header
 * instead of leaking tokens in query parameters.
 *
 * Drop-in replacement for the previous EventSource-based hook — same
 * callback surface and reconnect / idle behaviour.
 */
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
    let abortController: AbortController | null = null;
    let currentState: EventSourceConnectionState | null = null;

    const emitState = (state: EventSourceConnectionState) => {
      if (currentState === state) return;
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
          abortCurrent(false);
          scheduleReconnect();
        }
      }, idleTimeoutMs);
    };

    const abortCurrent = (emitClose: boolean) => {
      if (abortController) {
        abortController.abort();
        abortController = null;
      }
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
        connect(true);
      }, delay);
    };

    const connect = async (isReconnectAttempt: boolean) => {
      if (cancelled) return;
      clearReconnectTimer();
      emitState(isReconnectAttempt ? "reconnecting" : "connecting");

      const controller = new AbortController();
      abortController = controller;

      const headers: Record<string, string> = {
        Accept: "text/event-stream",
      };
      const apiKey = getStoredApiKey();
      if (apiKey) {
        headers["Authorization"] = `Bearer ${apiKey}`;
      }

      let response: Response;
      try {
        response = await fetch(url, { headers, signal: controller.signal });
      } catch {
        if (cancelled) return;
        onErrorRef.current?.(new Event("error"));
        abortCurrent(false);
        scheduleReconnect();
        return;
      }

      if (cancelled) {
        abortCurrent(false);
        return;
      }

      if (!response.ok || !response.body) {
        onErrorRef.current?.(new Event("error"));
        abortCurrent(false);
        scheduleReconnect();
        return;
      }

      // Connection established
      const reconnected = hasConnected;
      hasConnected = true;
      attempt = 0;
      emitState("open");
      scheduleIdleTimeout();
      onOpenRef.current?.(new Event("open"));
      if (reconnected) {
        onReconnectRef.current?.(new Event("open"));
      }

      // Read the SSE stream
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (cancelled || done) break;

          buffer += decoder.decode(value, { stream: true });

          // SSE events are separated by blank lines (\n\n)
          const parts = buffer.split("\n\n");
          buffer = parts.pop() ?? "";

          for (const part of parts) {
            if (!part.trim()) continue;

            let data = "";
            for (const line of part.split("\n")) {
              if (line.startsWith("data:")) {
                data += (data ? "\n" : "") + line.slice(5).trimStart();
              }
            }

            if (data) {
              scheduleIdleTimeout();
              onMessageRef.current?.(new MessageEvent("message", { data }));
            }
          }
        }
      } catch {
        // Stream read error (abort, network drop, etc.)
      }

      if (cancelled) return;

      // Stream ended — schedule reconnect
      onErrorRef.current?.(new Event("error"));
      abortCurrent(false);
      scheduleReconnect();
    };

    connect(false);

    return () => {
      cancelled = true;
      clearReconnectTimer();
      clearIdleTimer();
      abortCurrent(true);
      emitState("closed");
    };
  }, [
    effectiveEnabled,
    idleTimeoutMs,
    reconnectOnIdle,
    reconnectInitialDelayMs,
    reconnectMaxDelayMs,
    url,
  ]);
}
