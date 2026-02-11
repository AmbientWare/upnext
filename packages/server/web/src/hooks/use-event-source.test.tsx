import { act, render } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import { useEventSource } from "./use-event-source";

class MockEventSource {
  static instances: MockEventSource[] = [];

  url: string;
  listeners = new Map<string, ((event: Event) => void)[]>();
  closed = false;

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (event: Event) => void) {
    const existing = this.listeners.get(type) ?? [];
    existing.push(listener);
    this.listeners.set(type, existing);
  }

  emit(type: string, event: Event) {
    for (const listener of this.listeners.get(type) ?? []) {
      listener(event);
    }
  }

  close() {
    this.closed = true;
  }
}

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
  beforeEach(() => {
    MockEventSource.instances = [];
    vi.useFakeTimers();
    vi.stubGlobal("EventSource", MockEventSource as unknown as typeof EventSource);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("registers handlers and closes source on unmount", () => {
    const onMessage = vi.fn();
    const view = render(<Harness onMessage={onMessage} />);

    expect(MockEventSource.instances).toHaveLength(1);
    const source = MockEventSource.instances[0];

    source.emit("message", new MessageEvent("message", { data: "x" }));
    expect(onMessage).toHaveBeenCalledTimes(1);

    view.unmount();
    expect(source.closed).toBe(true);
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

    expect(MockEventSource.instances).toHaveLength(1);
    const first = MockEventSource.instances[0];
    first.emit("open", new Event("open"));

    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onReconnect).toHaveBeenCalledTimes(0);

    first.emit("error", new Event("error"));
    expect(onError).toHaveBeenCalledTimes(1);
    expect(first.closed).toBe(true);

    await vi.advanceTimersByTimeAsync(1200);
    expect(MockEventSource.instances).toHaveLength(2);

    const second = MockEventSource.instances[1];
    second.emit("open", new Event("open"));
    expect(onOpen).toHaveBeenCalledTimes(2);
    expect(onReconnect).toHaveBeenCalledTimes(1);

    view.unmount();
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(second.closed).toBe(true);
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

    expect(MockEventSource.instances).toHaveLength(1);
    const first = MockEventSource.instances[0];
    first.emit("open", new Event("open"));

    await vi.advanceTimersByTimeAsync(60_000);
    expect(onIdle).toHaveBeenCalledTimes(1);
    expect(first.closed).toBe(true);

    await vi.advanceTimersByTimeAsync(2_000);
    expect(MockEventSource.instances).toHaveLength(2);

    const second = MockEventSource.instances[1];
    second.emit("open", new Event("open"));
    expect(onReconnect).toHaveBeenCalledTimes(1);
  });

  it("pauses connection while tab is hidden when configured", async () => {
    let visibilityState: DocumentVisibilityState = "visible";
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => visibilityState,
    });

    render(<VisibilityHarness />);
    expect(MockEventSource.instances).toHaveLength(1);
    const first = MockEventSource.instances[0];

    visibilityState = "hidden";
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await Promise.resolve();
    });
    expect(first.closed).toBe(true);

    visibilityState = "visible";
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await Promise.resolve();
    });
    expect(MockEventSource.instances).toHaveLength(2);
  });
});
