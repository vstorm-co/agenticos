import { useRef } from "react";
import { act, fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useChatViewport } from "./use-chat-viewport";
import type { ChatMessage } from "@/types";
import { QuestionTurnCard } from "@/components/chat/question-turn-card";

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
  mounted = true,
  onChoose,
  pending,
}: {
  messages?: ChatMessage[];
  sentTurnId?: string;
  conversationId?: string | null;
  mounted?: boolean;
  onChoose?: () => void;
  pending?: boolean;
}) {
  const scroller = useRef<HTMLDivElement>(null),
    content = useRef<HTMLDivElement>(null),
    spacer = useRef<HTMLDivElement>(null),
    dock = useRef<HTMLDivElement>(null);
  const { bindScroller } = useChatViewport({
    conversationId,
    messages,
    sentTurnId,
    empty: messages.length === 0,
    scroller,
    content,
    spacer,
    dock,
  });
  if (!mounted) return <div>Loading transcript</div>;
  return (
    <>
      <div ref={bindScroller} data-testid="scroll">
        <div ref={content} data-testid="content">
          <div data-message-id="old" data-chat-message-key="old">
            <button>History control</button>
          </div>
          {messages.some((message) => message.id === "sent") && (
            <div data-message-id="sent" data-chat-message-key="sent">
              New question
            </div>
          )}
          {pending !== undefined ? (
            pending && (
              <QuestionTurnCard
                calls={[]}
                interaction={{
                  id: "live-question",
                  messageId: "reply",
                  toolCallIds: [],
                  questions: [
                    { question: "Which format?", options: [{ label: "Short" }], allowCustom: true },
                  ],
                  submitting: false,
                  disabled: false,
                  onAnswer: onChoose ?? (() => {}),
                }}
              />
            )
          ) : (
            <div data-question-pending data-chat-anchor="question">
              <div role="group" tabIndex={-1}>
                Question
                <button onClick={onChoose}>Short</button>
              </div>
            </div>
          )}
          <div ref={spacer} data-testid="space" />
        </div>
      </div>
      <div ref={dock} data-testid="dock">
        <input aria-label="Composer" />
      </div>
    </>
  );
}
/** Put the question in view by a native scroll gesture, without a product Reveal command. */
function readQuestion(view: ReturnType<typeof render>) {
  const card = view.container.querySelector<HTMLElement>("[data-question-pending]");
  if (!card) return;
  const scrolling = view.getByTestId("scroll");
  scrolling.scrollTop = questionTop - 24;
  fireEvent.wheel(scrolling, { deltaY: -1 });
  fireEvent.scroll(scrolling);
  card.querySelector<HTMLElement>('[role="group"]')?.focus({ preventScroll: true });
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
  fireEvent.click(view.getByText("History control"));
  bodyHeight += 400;
  act(() => resized?.());
  expect(scrolling.scrollTop).toBe(200);
});
it("allows a reader to focus a question without native focus scrolling", () => {
  const focus = vi.spyOn(HTMLElement.prototype, "focus");
  const view = render(<Harness messages={[old, sent]} />);
  readQuestion(view);
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
  fireEvent.pointerUp(window);
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
  readQuestion(view);
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
    useChatViewport({
      conversationId: "loading",
      messages: [sent],
      sentTurnId: "sent",
      empty: false,
      scroller: absent,
      content: absent,
      spacer: absent,
      dock: absent,
    });
    return null;
  }
  expect(() => render(<Loading />)).not.toThrow();
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
it("restores a locked reading anchor immediately when layout clamps the scrollbar", () => {
  const view = render(<Harness />);
  const scrolling = view.getByTestId("scroll");
  scrolling.scrollTop = 200;
  fireEvent.click(view.getByText("History control"));
  bodyHeight -= 400;
  scrolling.scrollTop = 150;
  fireEvent.scroll(scrolling);
  expect(scrolling.scrollTop).toBe(200);
  // Browsers can acknowledge the restored position more than once.
  fireEvent.scroll(scrolling);
  fireEvent.scroll(scrolling);
  bodyHeight += 100;
  act(() => resized?.());
  expect(scrolling.scrollTop).toBe(200);
});
it("allows Tab focus to scroll away from a locked reading anchor", () => {
  const view = render(<Harness />);
  const scrolling = view.getByTestId("scroll");
  scrolling.scrollTop = 200;
  fireEvent.click(view.getByText("History control"));
  fireEvent.keyDown(view.getByText("History control"), { key: "Tab" });
  scrolling.scrollTop = 250;
  fireEvent.scroll(scrolling);
  bodyHeight += 100;
  act(() => resized?.());
  expect(scrolling.scrollTop).toBe(250);
});
it("anchors the question being answered when preceding work also remains visible", () => {
  questionTop = 400;
  const view = render(<Harness />);
  const scrolling = view.getByTestId("scroll");
  const earlier = view.container.querySelector<HTMLElement>('[data-message-id="old"]')!;
  Object.defineProperty(earlier, "getBoundingClientRect", {
    value: () => new DOMRect(0, 100 - scrolling.scrollTop, 600, 60),
  });
  scrolling.scrollTop = 0;
  fireEvent.wheel(scrolling, { deltaY: -1 });
  fireEvent.click(view.getByText("Short"));
  questionTop += 8;
  bodyHeight += 8;
  act(() => resized?.());
  expect(scrolling.scrollTop).toBe(8);
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
it("preserves the chosen anchor after focus scrolling and control activation", () => {
  const view = render(<Harness />);
  const scrolling = view.getByTestId("scroll");
  scrolling.scrollTop = 200;
  fireEvent.click(view.getByText("History control"));
  scrolling.scrollTop = 150;
  fireEvent.scroll(scrolling);
  expect(scrolling.scrollTop).toBe(150);
  fireEvent.click(view.getByText("History control"));
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

it("attaches the viewport when a suspended transcript mounts after the conversation", () => {
  const view = render(<Harness mounted={false} />);
  expect(view.queryByTestId("scroll")).toBeNull();
  view.rerender(<Harness />);
  const scrolling = view.getByTestId("scroll");
  expect(scrolling.style.paddingBottom).toBe("144px");
  expect(scrolling.scrollTop).toBe(744);
  readQuestion(view);
  expect(scrolling.scrollTop).toBe(questionTop - 24);
  expect(view.getByRole("group")).toHaveFocus();
});

it("finishes a released pointer without a click and restores deferred dock measurements", () => {
  vi.useFakeTimers();
  try {
    const view = render(<Harness />);
    const scrolling = view.getByTestId("scroll");
    scrolling.scrollTop = 200;
    fireEvent.pointerDown(view.getByText("History control"));
    dockSize = 184;
    act(() => resized?.());
    expect(scrolling.style.paddingBottom).toBe("144px");
    fireEvent.pointerUp(window);
    act(() => vi.advanceTimersByTime(20));
    expect(scrolling.style.paddingBottom).toBe("184px");
    expect(scrolling.scrollTop).toBe(200);
  } finally {
    vi.useRealTimers();
  }
});

it("cancels a native pointer gesture without leaving the viewport frozen", () => {
  const view = render(<Harness />);
  const scrolling = view.getByTestId("scroll");
  scrolling.scrollTop = 200;
  fireEvent.scroll(scrolling);
  fireEvent.pointerDown(view.getByText("Short"));
  fireEvent.pointerCancel(window);
  expect(scrolling.scrollTop).toBe(200);
  dockSize = 180;
  act(() => resized?.());
  expect(scrolling.style.paddingBottom).toBe("180px");
});

it.each(["unmount", "conversation"])(
  "cancels the pending pointer release frame on %s",
  (change) => {
    vi.useFakeTimers();
    try {
      const cancel = vi.spyOn(window, "cancelAnimationFrame");
      const view = render(<Harness />);
      const scrolling = view.getByTestId("scroll");
      scrolling.scrollTop = 200;
      fireEvent.pointerDown(view.getByText("History control"));
      fireEvent.pointerUp(window);
      if (change === "unmount") view.unmount();
      else view.rerender(<Harness conversationId="other" />);
      expect(cancel).toHaveBeenCalled();
      const top = scrolling.scrollTop;
      act(() => vi.advanceTimersByTime(20));
      expect(scrolling.scrollTop).toBe(top);
    } finally {
      vi.useRealTimers();
    }
  },
);

it("does not jump to the bottom when a live question card first appears", () => {
  questionTop = 1200;
  const view = render(<Harness pending={false} />);
  const scrolling = view.getByTestId("scroll");
  const editor = view.getByRole("textbox", { name: "Composer" });
  editor.focus();
  expect(scrolling.scrollTop).toBe(744);
  bodyHeight += 550;
  view.rerender(<Harness pending />);
  expect(view.getByRole("group", { name: "Question from the assistant" })).toBeInTheDocument();
  act(() => resized?.());
  expect(scrolling.scrollTop).toBe(744);
  expect(editor).toHaveFocus();
  bodyHeight += 100;
  view.rerender(<Harness pending messages={[{ ...old, runWaitingFor: "answer" }]} />);
  act(() => resized?.());
  expect(scrolling.scrollTop).toBe(744);
  readQuestion(view);
  expect(scrolling.scrollTop).toBe(questionTop - 24);
  expect(view.getByRole("group", { name: "Question from the assistant" })).toHaveFocus();
});

it("keeps the sent turn stable when a large question exhausts its reserved space", () => {
  bodyHeight = 1300;
  const view = render(<Harness messages={[old, sent]} sentTurnId="sent" pending={false} />);
  const scrolling = view.getByTestId("scroll");
  expect(scrolling.scrollTop).toBe(1176);
  bodyHeight = 2000;
  view.rerender(<Harness messages={[old, sent]} sentTurnId="sent" pending />);
  act(() => resized?.());
  act(() => resized?.());
  expect(scrolling.scrollTop).toBe(1176);
});

it("opens a saved pending question at the bottom and follows ordinary later content", () => {
  bodyHeight = 1800;
  const view = render(<Harness pending />);
  expect(view.getByTestId("scroll").scrollTop).toBe(1344);
  bodyHeight += 100;
  act(() => resized?.());
  expect(view.getByTestId("scroll").scrollTop).toBe(1444);
});

it("preserves an intentional reader position when a real pending card is inserted", () => {
  const view = render(<Harness pending={false} />);
  const scrolling = view.getByTestId("scroll");
  fireEvent.wheel(scrolling, { deltaY: -10 });
  scrolling.scrollTop = 200;
  fireEvent.scroll(scrolling);
  bodyHeight += 550;
  view.rerender(<Harness pending />);
  act(() => resized?.());
  expect(scrolling.scrollTop).toBe(200);
  // Following can be resumed by deliberately scrolling back to the bottom.
  fireEvent.wheel(scrolling, { deltaY: 10 });
  scrolling.scrollTop = bodyHeight + dockSize - 600;
  fireEvent.scroll(scrolling);
  bodyHeight += 80;
  act(() => resized?.());
  expect(scrolling.scrollTop).toBe(bodyHeight + dockSize - 600);
});

it("does not mistake initial HTTP transcript hydration for a live question arrival", () => {
  const view = render(<Harness pending={false} messages={[]} />);
  bodyHeight = 1800;
  view.rerender(<Harness pending messages={[old]} />);
  act(() => resized?.());
  expect(view.getByTestId("scroll").scrollTop).toBe(1344);
});
