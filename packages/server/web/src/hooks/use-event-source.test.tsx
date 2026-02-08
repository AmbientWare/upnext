import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

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

describe("useEventSource", () => {
  it("registers handlers and closes source on unmount", () => {
    vi.stubGlobal("EventSource", MockEventSource as unknown as typeof EventSource);

    const onMessage = vi.fn();
    const view = render(<Harness onMessage={onMessage} />);

    expect(MockEventSource.instances).toHaveLength(1);
    const source = MockEventSource.instances[0];

    source.emit("message", new MessageEvent("message", { data: "x" }));
    expect(onMessage).toHaveBeenCalledTimes(1);

    view.unmount();
    expect(source.closed).toBe(true);
  });
});
