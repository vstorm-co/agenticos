import { useRef } from "react";
import { act, fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useChatViewport } from "./use-chat-viewport";
import type { ChatMessage } from "@/types";

let resized: (() => void) | undefined;
let bodyHeight = 1200;
let dockSize = 144;
let questionTop = 1260;
const old: ChatMessage = {
  id: "old",
  role: "assistant",
  content: "History",
  timestamp: new Date(),
};
const sent: ChatMessage = {
  id: "sent",
  clientMessageId: "sent",
  role: "user",
  content: "New question",
  timestamp: new Date(),
};
function Harness({
  messages = [old],
  sentTurnId,
  conversationId = "c",
}: {
  messages?: ChatMessage[];
  sentTurnId?: string;
  conversationId?: string | null;
}) {
  const scroller = useRef<HTMLDivElement>(null),
    content = useRef<HTMLDivElement>(null),
    spacer = useRef<HTMLDivElement>(null),
    dock = useRef<HTMLDivElement>(null);
  const { revealQuestion } = useChatViewport({
    conversationId,
    messages,
    sentTurnId,
    empty: messages.length === 0,
    scroller,
    content,
    spacer,
    dock,
  });
  return (
    <>
      <div ref={scroller} data-testid="scroll">
        <div ref={content} data-testid="content">
          <div data-message-id="old" data-chat-message-key="old">
            <button>History control</button>
          </div>
          {messages.some((message) => message.id === "sent") && (
            <div data-message-id="sent" data-chat-message-key="sent">
              New question
            </div>
          )}
          <div data-question-pending data-chat-anchor="question">
            <div role="group" tabIndex={-1}>
              Question
            </div>
          </div>
          <div ref={spacer} data-testid="space" />
        </div>
      </div>
      <div ref={dock} data-testid="dock" />
      <button onClick={revealQuestion}>Reveal</button>
    </>
  );
}
beforeEach(() => {
  bodyHeight = 1200;
  dockSize = 144;
  questionTop = 1260;
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(callback: () => void) {
        resized = callback;
      }
      observe() {}
      disconnect() {}
    },
  );
  vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockImplementation(function (
    this: HTMLElement,
  ) {
    return this.dataset.testid === "scroll" ? 600 : 0;
  });
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockImplementation(function (
    this: HTMLElement,
  ) {
    return this.dataset.testid === "dock" ? dockSize : Number.parseFloat(this.style.height) || 0;
  });
  vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockImplementation(function (
    this: HTMLElement,
  ) {
    return (
      bodyHeight +
      (Number.parseFloat(this.style.paddingBottom) || 0) +
      (Number.parseFloat(
        document.querySelector<HTMLElement>('[data-testid="space"]')?.style.height ?? "0",
      ) || 0)
    );
  });
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (
    this: HTMLElement,
  ) {
    const top = document.querySelector<HTMLElement>('[data-testid="scroll"]')?.scrollTop ?? 0;
    if (this.dataset.testid === "content")
      return new DOMRect(
        0,
        -top,
        600,
        bodyHeight +
          (Number.parseFloat(
            document.querySelector<HTMLElement>('[data-testid="space"]')?.style.height ?? "0",
          ) || 0),
      );
    if (this.dataset.messageId === "old") return new DOMRect(0, -top, 600, 600);
    if (this.dataset.messageId === "sent") return new DOMRect(0, 1200 - top, 600, 60);
    if (this.dataset.chatAnchor)
      return new DOMRect(0, questionTop - top, 600, Math.max(0, bodyHeight - questionTop));
    return new DOMRect(0, 0, 600, 600);
  });
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("follows growth at the bottom using one resize policy, including dock changes", () => {
  const view = render(<Harness />);
  const scrolling = view.getByTestId("scroll");
  expect(scrolling.scrollTop).toBe(744);
  bodyHeight += 200;
  dockSize += 40;
  act(() => resized?.());
  expect(scrolling.scrollTop).toBe(984);
  expect(scrolling.style.paddingBottom).toBe("184px");
});
it("does not move a reader when a question appears, changes step or submits", () => {
  const view = render(<Harness />);
  const scrolling = view.getByTestId("scroll");
  scrolling.scrollTop = 200;
  fireEvent.wheel(scrolling, { deltaY: -10 });
  fireEvent.scroll(scrolling);
  for (const height of [1500, 1600, 1300]) {
    bodyHeight = height;
    act(() => resized?.());
    expect(scrolling.scrollTop).toBe(200);
  }
});
it("keeps an explicitly sent message anchored through question and receipt resizing", () => {
  const view = render(<Harness />);
  bodyHeight = 1300;
  view.rerender(<Harness messages={[old, sent]} sentTurnId="sent" />);
  const scrolling = view.getByTestId("scroll");
  expect(scrolling.scrollTop).toBe(1176);
  for (const height of [1540, 1500, 1380]) {
    bodyHeight = height;
    act(() => resized?.());
    expect(scrolling.scrollTop).toBe(1176);
  }
});
it("does not follow incoming content after the reader opens a historical disclosure", () => {
  const view = render(<Harness />);
  const scrolling = view.getByTestId("scroll");
  scrolling.scrollTop = 200;
  fireEvent.pointerDown(view.getByText("History control"));
  bodyHeight += 400;
  act(() => resized?.());
  expect(scrolling.scrollTop).toBe(200);
});
it("reveals a pending question only on explicit action and focuses without scrolling", () => {
  const focus = vi.spyOn(HTMLElement.prototype, "focus");
  const view = render(<Harness messages={[old, sent]} />);
  fireEvent.click(view.getByText("Reveal"));
  expect(view.getByTestId("scroll").scrollTop).toBe(1236);
  expect(focus).toHaveBeenCalledWith({ preventScroll: true });
});

it("starts an empty chat at its welcome and follows after the first message", () => {
  const view = render(<Harness messages={[]} />);
  expect(view.getByTestId("scroll").scrollTop).toBe(0);
  view.rerender(<Harness messages={[old]} />);
  act(() => resized?.());
  expect(view.getByTestId("scroll").scrollTop).toBe(744);
});
it("keeps the anchor across first-save identity and hands following back when the answer fills the viewport", () => {
  bodyHeight = 1300;
  const view = render(<Harness messages={[old, sent]} sentTurnId="sent" conversationId={null} />);
  expect(view.getByTestId("scroll").scrollTop).toBe(1176);
  view.rerender(<Harness messages={[old, sent]} sentTurnId="sent" conversationId="saved" />);
  expect(view.getByTestId("scroll").scrollTop).toBe(1176);
  bodyHeight = 2000;
  act(() => resized?.());
  act(() => resized?.());
  expect(view.getByTestId("scroll").scrollTop).toBe(1544);
});
it.each(["ArrowUp", "PageUp", "Home", "Enter", " "])(
  "honors keyboard reading intent from %s",
  (key) => {
    const view = render(<Harness />);
    const scrolling = view.getByTestId("scroll");
    scrolling.scrollTop = 200;
    fireEvent.keyDown(view.getByText("History control"), { key });
    bodyHeight += 300;
    act(() => resized?.());
    expect(scrolling.scrollTop).toBe(200);
  },
);
it("lets touch readers move up and resume following at the bottom", () => {
  const view = render(<Harness />);
  const scrolling = view.getByTestId("scroll");
  fireEvent.scroll(scrolling); // The programmatic initial position is not reader intent.
  fireEvent.touchStart(scrolling, { touches: [{ clientY: 100 }] });
  scrolling.scrollTop = 200;
  fireEvent.touchMove(scrolling, { touches: [{ clientY: 150 }] });
  fireEvent.scroll(scrolling);
  bodyHeight += 200;
  act(() => resized?.());
  expect(scrolling.scrollTop).toBe(200);
  scrolling.scrollTop = bodyHeight + 144 - 600;
  fireEvent.scroll(scrolling);
  bodyHeight += 200;
  act(() => resized?.());
  expect(scrolling.scrollTop).toBe(1144);
});
it("ignores aborted touches and non-scrolling keys without releasing following", () => {
  const view = render(<Harness />);
  const scrolling = view.getByTestId("scroll");
  fireEvent.touchStart(scrolling, { touches: [] });
  fireEvent.touchMove(scrolling, { touches: [] });
  fireEvent.touchStart(scrolling, { touches: [{ clientY: 150 }] });
  fireEvent.touchMove(scrolling, { touches: [{ clientY: 100 }] });
  fireEvent.wheel(scrolling, { deltaY: 10 });
  fireEvent.keyDown(scrolling, { key: "Tab" });
  fireEvent.keyDown(scrolling, { key: "Enter" });
  fireEvent.pointerDown(scrolling);
  bodyHeight += 100;
  act(() => resized?.());
  expect(scrolling.scrollTop).toBe(844);
});
it("leaves a detached anchor alone and ignores a question that has already settled", () => {
  const view = render(<Harness />);
  const scrolling = view.getByTestId("scroll");
  scrolling.scrollTop = 200;
  fireEvent.wheel(scrolling, { deltaY: -1 });
  view.container.querySelector("[data-message-id]")?.remove();
  view.container.querySelector("[data-question-pending]")?.remove();
  act(() => resized?.());
  fireEvent.click(view.getByText("Reveal"));
  expect(scrolling.scrollTop).toBe(200);
});
it("releases an explicitly sent anchor whose message was removed", () => {
  bodyHeight = 1300;
  const view = render(<Harness messages={[old, sent]} sentTurnId="sent" />);
  view.container.querySelector('[data-message-id="sent"]')?.remove();
  expect(() => act(() => resized?.())).not.toThrow();
});
it("does not require attached DOM while a transcript is still loading", () => {
  function Loading() {
    const absent = useRef<HTMLDivElement>(null);
    const { revealQuestion } = useChatViewport({
      conversationId: "loading",
      messages: [sent],
      sentTurnId: "sent",
      empty: false,
      scroller: absent,
      content: absent,
      spacer: absent,
      dock: absent,
    });
    return <button onClick={revealQuestion}>Reveal loading</button>;
  }
  const view = render(<Loading />);
  expect(() => fireEvent.click(view.getByText("Reveal loading"))).not.toThrow();
});

it("tracks the visible message rather than an offscreen question when content is inserted below the reader", () => {
  const view = render(<Harness />);
  const scrolling = view.getByTestId("scroll");
  scrolling.scrollTop = 200;
  fireEvent.wheel(scrolling, { deltaY: -1 });
  questionTop += 300;
  bodyHeight += 300;
  act(() => resized?.());
  expect(scrolling.scrollTop).toBe(200);
});

it("restores the reading anchor when layout clamps scrolling before resize delivery", () => {
  const view = render(<Harness />);
  const scrolling = view.getByTestId("scroll");
  scrolling.scrollTop = 200;
  fireEvent.wheel(scrolling, { deltaY: -1 });
  bodyHeight -= 400;
  scrolling.scrollTop = 150;
  fireEvent.scroll(scrolling);
  act(() => resized?.());
  expect(scrolling.scrollTop).toBe(200);
});

it("treats a scrollbar move upward as reading and leaves unrelated pointer events alone", () => {
  const view = render(<Harness />);
  const scrolling = view.getByTestId("scroll");
  fireEvent.scroll(scrolling);
  scrolling.scrollTop = 200;
  fireEvent.scroll(scrolling);
  fireEvent.pointerDown(view.getByTestId("content"));
  bodyHeight += 100;
  act(() => resized?.());
  expect(scrolling.scrollTop).toBe(200);
});
it("preserves the chosen anchor against focus scrolling during question activation", () => {
  const view = render(<Harness />);
  const scrolling = view.getByTestId("scroll");
  scrolling.scrollTop = 200;
  fireEvent.click(view.getByText("History control"));
  scrolling.scrollTop = 150;
  fireEvent.scroll(scrolling);
  expect(scrolling.scrollTop).toBe(200);
});
it("releases the reader lock for a real wheel gesture", () => {
  const view = render(<Harness />);
  const scrolling = view.getByTestId("scroll");
  scrolling.scrollTop = 200;
  fireEvent.click(view.getByText("History control"));
  fireEvent.wheel(scrolling, { deltaY: 20 });
  scrolling.scrollTop = 230;
  fireEvent.scroll(scrolling);
  bodyHeight += 100;
  act(() => resized?.());
  expect(scrolling.scrollTop).toBe(230);
});

it("pauses following while a reader selects transcript text", () => {
  const view = render(<Harness />);
  const scrolling = view.getByTestId("scroll");
  scrolling.scrollTop = 200;
  fireEvent.pointerDown(view.container.querySelector('[data-message-id="old"]')!);
  bodyHeight += 100;
  act(() => resized?.());
  expect(scrolling.scrollTop).toBe(200);
});
it.each(["ArrowDown", "PageDown", "End"])(
  "allows intentional keyboard scroll with %s after using a question",
  (key) => {
    const view = render(<Harness />);
    const scrolling = view.getByTestId("scroll");
    scrolling.scrollTop = 200;
    fireEvent.click(view.getByText("History control"));
    fireEvent.keyDown(scrolling, { key });
    scrolling.scrollTop = 250;
    fireEvent.scroll(scrolling);
    bodyHeight += 100;
    act(() => resized?.());
    expect(scrolling.scrollTop).toBe(250);
  },
);

it("opens another conversation at its history rather than reusing the previous sent anchor", () => {
  bodyHeight = 1300;
  const view = render(<Harness messages={[old, sent]} sentTurnId="sent" conversationId="first" />);
  expect(view.getByTestId("scroll").scrollTop).toBe(1176);
  view.rerender(<Harness messages={[old, sent]} sentTurnId="sent" conversationId="second" />);
  expect(view.getByTestId("scroll").scrollTop).toBe(844);
  bodyHeight = 1200;
  view.rerender(<Harness messages={[old]} sentTurnId="sent" conversationId="second" />);
  act(() => resized?.());
  expect(view.getByTestId("scroll").scrollTop).toBe(744);
});

it.each(["wheel", "touch", "PageDown", "End", "scrollbar"])(
  "releases a sent-turn anchor for deliberate downward %s scrolling",
  (method) => {
    bodyHeight = 1300;
    const view = render(<Harness messages={[old, sent]} sentTurnId="sent" />);
    const scrolling = view.getByTestId("scroll");
    // The answer grew before the browser delivers the next ResizeObserver callback.
    bodyHeight = 2000;
    if (method === "wheel") fireEvent.wheel(scrolling, { deltaY: 80 });
    else if (method === "touch") {
      fireEvent.touchStart(scrolling, { touches: [{ clientY: 150 }] });
      fireEvent.touchMove(scrolling, { touches: [{ clientY: 100 }] });
    } else if (method === "scrollbar") fireEvent.pointerDown(scrolling);
    else fireEvent.keyDown(scrolling, { key: method });
    scrolling.scrollTop += 80;
    fireEvent.scroll(scrolling);
    const chosen = scrolling.scrollTop;
    bodyHeight += 100;
    act(() => resized?.());
    expect(scrolling.scrollTop).toBe(chosen);
  },
);

it("anchors the revealed question before focus can trigger a resize", () => {
  const view = render(<Harness messages={[old, sent]} />);
  const original = HTMLElement.prototype.focus;
  vi.spyOn(HTMLElement.prototype, "focus").mockImplementation(function (
    this: HTMLElement,
    options,
  ) {
    original.call(this, options);
    if (this.getAttribute("role") === "group") resized?.();
  });
  fireEvent.click(view.getByText("Reveal"));
  expect(view.getByTestId("scroll").scrollTop).toBe(1236);
});
it("reveals below the phone toolbar's scroll inset", () => {
  const view = render(<Harness messages={[old, sent]} />);
  view.getByTestId("scroll").style.scrollPaddingTop = "80px";
  fireEvent.click(view.getByText("Reveal"));
  expect(view.getByTestId("scroll").scrollTop).toBe(1180);
});
