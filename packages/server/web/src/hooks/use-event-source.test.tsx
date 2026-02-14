import { act, render } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import { useEventSource } from "./use-event-source";

/** Helper to create a controllable SSE stream via fetch mock. */
function createMockSSEStream() {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
    },
  });

  return {
    response: new Response(stream, {
      status: 200,
      headers: { "Content-Type": "text/event-stream" },
    }),
    /** Push an SSE data frame into the stream. */
    push(data: string) {
      controller.enqueue(encoder.encode(`data: ${data}\n\n`));
    },
    /** Close the stream (simulates server hangup). */
    close() {
      try {
        controller.close();
      } catch {
        // already closed
      }
    },
    /** Signal an error on the stream. */
    error(err?: unknown) {
      try {
        controller.error(err ?? new Error("stream error"));
      } catch {
        // already errored
      }
    },
  };
}

type MockStream = ReturnType<typeof createMockSSEStream>;

function Harness({ onMessage }: { onMessage: (event: MessageEvent) => void }) {
  useEventSource("/events", { onMessage });
  return null;
}

function LifecycleHarness(props: {
  onOpen: (event: Event) => void;
  onReconnect: (event: Event) => void;
  onClose: () => void;
  onStateChange: (state: string) => void;
  onError: (event: Event) => void;
  onIdle?: () => void;
  idleTimeoutMs?: number;
  reconnectOnIdle?: boolean;
}) {
  useEventSource("/events", props);
  return null;
}

function VisibilityHarness() {
  useEventSource("/events", { pauseWhenHidden: true });
  return null;
}

describe("useEventSource", () => {
  let streams: MockStream[];
  let fetchSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    streams = [];
    fetchSpy = vi.fn().mockImplementation(() => {
      const mock = createMockSSEStream();
      streams.push(mock);
      return Promise.resolve(mock.response);
    });
    vi.stubGlobal("fetch", fetchSpy);
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("registers handlers and closes source on unmount", async () => {
    const onMessage = vi.fn();
    const view = render(<Harness onMessage={onMessage} />);

    // Let the async connect() resolve
    await act(async () => {
      await Promise.resolve();
    });

    expect(streams).toHaveLength(1);
    streams[0].push("x");

    // Let the stream read loop process
    await act(async () => {
      await Promise.resolve();
    });
    expect(onMessage).toHaveBeenCalledTimes(1);
    expect(onMessage.mock.calls[0][0].data).toBe("x");

    view.unmount();
  });

  it("reconnects after errors and emits lifecycle callbacks", async () => {
    const onOpen = vi.fn();
    const onReconnect = vi.fn();
    const onClose = vi.fn();
    const onError = vi.fn();
    const onStateChange = vi.fn();

    const view = render(
      <LifecycleHarness
        onOpen={onOpen}
        onReconnect={onReconnect}
        onClose={onClose}
        onError={onError}
        onStateChange={onStateChange}
      />
    );

    // First connection
    await act(async () => {
      await Promise.resolve();
    });
    expect(streams).toHaveLength(1);
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onReconnect).toHaveBeenCalledTimes(0);

    // Close the stream to trigger reconnect
    await act(async () => {
      streams[0].close();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(onError).toHaveBeenCalledTimes(1);

    // Advance past reconnect delay
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1200);
      await Promise.resolve();
    });
    expect(streams).toHaveLength(2);
    expect(onOpen).toHaveBeenCalledTimes(2);
    expect(onReconnect).toHaveBeenCalledTimes(1);

    view.unmount();
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onStateChange).toHaveBeenCalledWith("open");
    expect(onStateChange).toHaveBeenCalledWith("closed");
  });

  it("reconnects after idle timeout", async () => {
    const onOpen = vi.fn();
    const onReconnect = vi.fn();
    const onClose = vi.fn();
    const onError = vi.fn();
    const onStateChange = vi.fn();
    const onIdle = vi.fn();

    render(
      <LifecycleHarness
        onOpen={onOpen}
        onReconnect={onReconnect}
        onClose={onClose}
        onError={onError}
        onStateChange={onStateChange}
        onIdle={onIdle}
        idleTimeoutMs={60_000}
        reconnectOnIdle
      />
    );

    // First connection
    await act(async () => {
      await Promise.resolve();
    });
    expect(streams).toHaveLength(1);
    expect(onOpen).toHaveBeenCalledTimes(1);

    // Advance to idle timeout
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(onIdle).toHaveBeenCalledTimes(1);

    // Advance past reconnect delay
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_000);
      await Promise.resolve();
    });
    expect(streams).toHaveLength(2);
    expect(onReconnect).toHaveBeenCalledTimes(1);
  });

  it("pauses connection while tab is hidden when configured", async () => {
    let visibilityState: DocumentVisibilityState = "visible";
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => visibilityState,
    });

    render(<VisibilityHarness />);

    await act(async () => {
      await Promise.resolve();
    });
    expect(streams).toHaveLength(1);

    visibilityState = "hidden";
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await Promise.resolve();
    });

    // Connection should be aborted (cleanup runs)
    const streamCountAfterHide = streams.length;

    visibilityState = "visible";
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await Promise.resolve();
      await Promise.resolve();
    });

    // A new connection should have been created
    expect(streams.length).toBeGreaterThan(streamCountAfterHide);
  });
});
