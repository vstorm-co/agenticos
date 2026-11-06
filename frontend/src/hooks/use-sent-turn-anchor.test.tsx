import { useRef } from "react";
import { act, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChatMessage } from "@/types";
vi.mock("@/lib/scroll-gently", () => ({
  scrollGently: (element: HTMLElement, top: number) => {
    element.scrollTop = top;
    return () => {};
  },
}));

import { useSentTurnAnchor } from "./use-sent-turn-anchor";

function Harness({
  messages,
  sentTurnId,
  topInset,
}: {
  messages: ChatMessage[];
  sentTurnId?: string;
  topInset?: number;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const spacer = useRef<HTMLDivElement>(null);
  const anchored = useRef(false);
  const readerScrolledUp = useRef(false);
  useSentTurnAnchor(messages, scroller, content, spacer, anchored, sentTurnId, readerScrolledUp);
  return (
    <div
      ref={scroller}
      data-testid="scroller"
      style={{ paddingBottom: 100, scrollPaddingTop: topInset }}
    >
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
  it.each([undefined, 80])(
    "anchors beneath the toolbar inset %s and releases space as the reply grows",
    (topInset) => {
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
      const view = render(<Harness topInset={topInset} messages={[user("old")]} />);
      const scroller = view.getByTestId("scroller");
      expect(scroller.scrollTop).toBe(0);
      const messages = [user("old"), user("sent", true)];
      view.rerender(<Harness topInset={topInset} messages={messages} sentTurnId="sent" />);
      expect(scroller.scrollTop).toBe(100 - (topInset ?? 24));
      expect(view.getByTestId("spacer").style.height).toBe(`${420 - (topInset ?? 24)}px`);
      scroller.scrollTop = 20;
      view.rerender(<Harness topInset={topInset} messages={[...messages]} sentTurnId="sent" />);
      expect(scroller.scrollTop).toBe(20);
      // The next outbox item is sent automatically, not a request to move the viewport.
      view.rerender(
        <Harness
          topInset={topInset}
          messages={[...messages, user("queued", true)]}
          sentTurnId="sent"
        />,
      );
      expect(scroller.scrollTop).toBe(20);
      expect(view.getByTestId("spacer").style.height).toBe(`${420 - (topInset ?? 24)}px`);
      // A persisted acknowledgement keeps the same anchor even if React batches it with send.
      view.rerender(
        <Harness
          topInset={topInset}
          messages={[user("old"), { ...user("saved"), clientMessageId: "sent" }]}
          sentTurnId="sent"
        />,
      );
      expect(scroller.scrollTop).toBe(20);
      height = 600;
      act(() => resized?.());
      expect(view.getByTestId("spacer").style.height).toBe("0px");
      expect(scroller.scrollTop).toBe(20);
    },
  );
});
