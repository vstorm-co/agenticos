import { useRef } from "react";
import { act, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChatMessage } from "@/types";
import { useSentTurnAnchor } from "./use-sent-turn-anchor";

function Harness({ messages }: { messages: ChatMessage[] }) {
  const scroller = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const spacer = useRef<HTMLDivElement>(null);
  const anchored = useRef(false);
  useSentTurnAnchor(messages, scroller, content, spacer, anchored);
  return (
    <div ref={scroller} data-testid="scroller" style={{ paddingBottom: 100 }}>
      <div ref={content} data-testid="content">
        {messages.map((message) => (
          <div key={message.id} data-message-id={message.id}>
            {message.content}
          </div>
        ))}
        <div ref={spacer} data-testid="spacer" />
      </div>
    </div>
  );
}
function user(id: string, temporary = false): ChatMessage {
  return {
    id,
    clientMessageId: id,
    role: "user",
    content: "Question",
    timestamp: new Date(),
    isTemporaryId: temporary,
  };
}
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
describe("sent turn anchoring", () => {
  it("positions a newly sent question near the top and releases space as the reply grows", () => {
    let height = 80;
    let resized: (() => void) | undefined;
    vi.stubGlobal(
      "ResizeObserver",
      class implements ResizeObserver {
        constructor(callback: ResizeObserverCallback) {
          resized = () => callback([], this);
        }
        observe() {}
        unobserve() {}
        disconnect() {}
      },
    );
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(600);
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (
      this: HTMLElement,
    ) {
      const space =
        Number.parseFloat(
          document.querySelector<HTMLElement>('[data-testid="spacer"]')?.style.height ?? "0",
        ) || 0;
      if (this.dataset.testid === "content") return new DOMRect(0, 0, 400, 100 + height + space);
      if (this.dataset.testid === "spacer") return new DOMRect(0, 0, 400, space);
      if (this.dataset.messageId) return new DOMRect(0, 100, 400, 40);
      return new DOMRect(0, 0, 400, 600);
    });
    const view = render(<Harness messages={[user("old")]} />);
    const scroller = view.getByTestId("scroller");
    expect(scroller.scrollTop).toBe(0);
    const messages = [user("old"), user("sent", true)];
    view.rerender(<Harness messages={messages} />);
    expect(scroller.scrollTop).toBe(76);
    expect(view.getByTestId("spacer").style.height).toBe("396px");
    scroller.scrollTop = 20;
    view.rerender(<Harness messages={[...messages]} />);
    expect(scroller.scrollTop).toBe(20);
    height = 600;
    act(() => resized?.());
    expect(view.getByTestId("spacer").style.height).toBe("0px");
    expect(scroller.scrollTop).toBe(20);
  });
});
