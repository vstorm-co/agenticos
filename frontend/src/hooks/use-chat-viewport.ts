"use client";

import { useCallback, useLayoutEffect, useRef, useState, type RefObject } from "react";
import type { ChatMessage } from "@/types";

interface ViewportOptions {
  conversationId: string | null;
  messages: readonly ChatMessage[];
  sentTurnId: string | null | undefined;
  empty: boolean;
  scroller: RefObject<HTMLDivElement | null>;
  content: RefObject<HTMLDivElement | null>;
  spacer: RefObject<HTMLDivElement | null>;
  dock: RefObject<HTMLDivElement | null>;
}
type Anchor = { element: HTMLElement; offset: number };
type Mode = "following" | "reading" | "sent";

/** One owner for following, intentional sends, reading anchors and dock resizing. */
export function useChatViewport(options: ViewportOptions) {
  const [dockHeight, setDockHeight] = useState(0);
  const [mountedScroller, setMountedScroller] = useState<HTMLDivElement | null>(null);
  const current = useRef(options);
  useLayoutEffect(() => {
    current.current = options;
  });
  // A suspended child can attach its DOM after this hook's first layout effect.
  // Ref attachment, rather than a conversation change, starts the controller.
  const bindScroller = useCallback((element: HTMLDivElement | null) => {
    current.current.scroller.current = element;
    setMountedScroller(element);
  }, []);
  const controller = useRef<{ sent: (id: string) => void } | null>(null);
  const previousSent = useRef<string | null>(null);
  const previousConversation = useRef(options.conversationId);

  useLayoutEffect(() => {
    const { scroller, content, spacer, dock } = current.current;
    const scrolling = scroller.current;
    const transcript = content.current;
    const space = spacer.current;
    const docking = dock.current;
    if (!mountedScroller || !scrolling || !transcript || !space || !docking) return;
    const initialSent = current.current.sentTurnId;
    const oldConversation = previousConversation.current;
    const conversation = current.current.conversationId;
    previousConversation.current = conversation;
    const preserveSent =
      oldConversation === conversation || (oldConversation === null && conversation !== null);
    const ownsSent =
      preserveSent &&
      initialSent &&
      current.current.messages.some(
        (message) =>
          message.role === "user" &&
          [message.id, message.clientMessageId, message.renderKey].includes(initialSent),
      );
    let mode: Mode = ownsSent ? "sent" : "following";
    let anchor: Anchor | null = null;
    let sentKey: string | null = ownsSent ? initialSent : null;
    let writtenTop: number | null = null;
    let lastTop = scrolling.scrollTop;
    let writtenExtent = scrolling.scrollHeight;
    let touchY: number | null = null;
    let preserveAnchor = false;
    let pointerActive = false;
    let nativeControlScroll = false;
    let releaseFrame: number | null = null;
    let questionPending = !!transcript.querySelector("[data-question-pending]");
    let hasTranscript = current.current.messages.length > 0;
    let pausedForQuestion = false;
    const viewportTop = () => scrolling.getBoundingClientRect().top;
    const remember = () => {
      const top = viewportTop();
      const bottom = top + scrolling.clientHeight;
      const rows = [
        ...transcript.querySelectorAll<HTMLElement>("[data-chat-anchor], [data-message-id]"),
      ].map((element) => ({ element, rect: element.getBoundingClientRect() }));
      const visible = rows.find(
        ({ rect }) => rect.top >= top - 1 && rect.top < bottom && rect.bottom > top,
      );
      const containing = rows.findLast(({ rect }) => rect.top < top && rect.bottom > top);
      const row = visible ?? containing;
      anchor = row ? { element: row.element, offset: row.rect.top - top } : null;
    };
    const write = (top: number) => {
      writtenTop = Math.max(0, top);
      scrolling.scrollTop = writtenTop;
      lastTop = scrolling.scrollTop;
      writtenTop = lastTop;
      writtenExtent = scrolling.scrollHeight;
    };
    const read = () => {
      mode = "reading";
      writtenExtent = scrolling.scrollHeight;
      remember();
    };
    const resize = () => {
      // Native scrollIntoView may run before pointerdown. Moving the viewport
      // again before click changes the hit target between press and release.
      if (pointerActive || nativeControlScroll) return;
      const pending = !!transcript.querySelector("[data-question-pending]");
      // An incoming form can add a whole viewport at once. Keep the place the
      // person was reading rather than moving their draft out from under them.
      // An already-pending question on initial history load is not a live arrival.
      if (pending && !questionPending && hasTranscript) {
        pausedForQuestion = true;
        if (mode === "following") {
          write(lastTop);
          read();
        }
      }
      questionPending = pending;
      hasTranscript = current.current.messages.length > 0;
      const height = docking.offsetHeight;
      setDockHeight((previous) => (previous === height ? previous : height));
      scrolling.style.paddingBottom = `${height}px`;
      if (current.current.empty) {
        space.style.height = "0px";
        write(0);
        return;
      }
      if (mode === "sent" && sentKey) {
        const row = [...transcript.querySelectorAll<HTMLElement>("[data-message-id]")].find(
          (row) => row.dataset.chatMessageKey === sentKey || row.dataset.messageId === sentKey,
        );
        if (row) {
          const inset = Number.parseFloat(getComputedStyle(scrolling).scrollPaddingTop) || 24;
          const contentBelow =
            transcript.getBoundingClientRect().bottom -
            row.getBoundingClientRect().top -
            space.offsetHeight;
          const reserve = Math.max(
            0,
            Math.round(scrolling.clientHeight - height - contentBelow - inset),
          );
          space.style.height = `${reserve}px`;
          write(scrolling.scrollTop + row.getBoundingClientRect().top - viewportTop() - inset);
          if (reserve === 0) {
            mode = pausedForQuestion ? "reading" : "following";
            remember();
          }
          return;
        }
        mode = "reading";
      }
      if (mode === "following") {
        space.style.height = "0px";
        write(scrolling.scrollHeight - scrolling.clientHeight);
      } else if (anchor?.element.isConnected) {
        const desired =
          scrolling.scrollTop +
          anchor.element.getBoundingClientRect().top -
          viewportTop() -
          anchor.offset;
        // Collapsing a card must not clamp away the reader's existing position.
        const withoutReserve = scrolling.scrollHeight - space.offsetHeight - scrolling.clientHeight;
        space.style.height = `${Math.max(0, Math.ceil(desired - withoutReserve))}px`;
        write(desired);
      }
    };
    const lockReadingAnchor = (target: Element, restore = true) => {
      // Pointer/click may arrive after the browser scrolls a focused control.
      // Keep an existing lock until a deliberate reader gesture releases it.
      if (!preserveAnchor || !anchor?.element.isConnected) {
        read();
        const question = target.closest<HTMLElement>(
          "[data-chat-question], [data-question-pending]",
        );
        if (question)
          anchor = {
            element: question,
            offset: question.getBoundingClientRect().top - viewportTop(),
          };
      }
      preserveAnchor = true;
      if (restore) resize();
    };
    const cancelRelease = () => {
      if (releaseFrame !== null) cancelAnimationFrame(releaseFrame);
      releaseFrame = null;
    };
    const finishPointer = () => {
      cancelRelease();
      pointerActive = false;
      nativeControlScroll = false;
      resize();
    };
    const onPointerUp = () => {
      if (pointerActive) {
        cancelRelease();
        releaseFrame = requestAnimationFrame(finishPointer);
      }
    };
    const onScroll = () => {
      const top = scrolling.scrollTop;
      if (writtenTop !== null && Math.abs(top - writtenTop) < 1) {
        writtenTop = null;
        return;
      }
      if (Math.abs(top - lastTop) < 1) return;
      // Layout can clamp scrollTop before ResizeObserver restores the reading anchor.
      // That synthetic scroll must not replace the anchor with the clamped position.
      if (preserveAnchor) {
        if (scrolling.scrollHeight === writtenExtent) nativeControlScroll = true;
        else resize();
        return;
      }
      if (scrolling.scrollHeight !== writtenExtent) return;
      if (scrolling.scrollHeight - scrolling.clientHeight - top <= 8 && mode !== "sent") {
        mode = "following";
      } else if (top < lastTop - 1) mode = "reading";
      lastTop = top;
      remember();
    };
    const onWheel = (event: WheelEvent) => {
      cancelRelease();
      nativeControlScroll = false;
      pointerActive = false;
      preserveAnchor = false;
      if (event.deltaY < 0 || (event.deltaY > 0 && mode === "sent")) read();
    };
    const onTouchStart = (event: TouchEvent) => {
      touchY = event.touches[0]?.clientY ?? null;
    };
    const onTouchMove = (event: TouchEvent) => {
      cancelRelease();
      nativeControlScroll = false;
      pointerActive = false;
      preserveAnchor = false;
      const y = event.touches[0]?.clientY;
      if (touchY !== null && y !== undefined && (y > touchY || (y !== touchY && mode === "sent")))
        read();
    };
    const onKey = (event: KeyboardEvent) => {
      cancelRelease();
      nativeControlScroll = false;
      pointerActive = false;
      if (event.key === "Tab" && preserveAnchor) {
        preserveAnchor = false;
        read();
        return;
      }
      if (["ArrowDown", "PageDown", "End"].includes(event.key)) {
        preserveAnchor = false;
        if (mode === "sent") read();
        return;
      }
      if (["ArrowUp", "PageUp", "Home"].includes(event.key)) {
        preserveAnchor = false;
        read();
      } else if (
        ["Enter", " "].includes(event.key) &&
        event.target instanceof Element &&
        event.target.closest("button, summary")
      ) {
        lockReadingAnchor(event.target);
      }
    };
    const onPointer = (event: MouseEvent) => {
      if (event.target === scrolling) {
        cancelRelease();
        nativeControlScroll = false;
        pointerActive = false;
        preserveAnchor = false;
        if (mode === "sent") read();
        return;
      }
      if (
        event.target instanceof Element &&
        ((event.type === "pointerdown" && transcript.contains(event.target)) ||
          event.target.closest("button, summary, input, textarea"))
      ) {
        if (event.type === "pointerdown") {
          pointerActive = true;
          lockReadingAnchor(event.target, false);
        } else {
          // Click's target is already fixed; restoring now cannot retarget it.
          lockReadingAnchor(event.target, false);
          finishPointer();
        }
      }
    };
    const observer = new ResizeObserver(resize);
    observer.observe(transcript);
    observer.observe(scrolling);
    observer.observe(docking);
    scrolling.addEventListener("scroll", onScroll, { passive: true });
    scrolling.addEventListener("wheel", onWheel, { passive: true });
    scrolling.addEventListener("touchstart", onTouchStart, { passive: true });
    scrolling.addEventListener("touchmove", onTouchMove, { passive: true });
    scrolling.addEventListener("keydown", onKey);
    scrolling.addEventListener("pointerdown", onPointer, true);
    transcript.addEventListener("click", onPointer, true);
    window.addEventListener("pointerup", onPointerUp, true);
    window.addEventListener("pointercancel", finishPointer, true);
    controller.current = {
      sent: (id) => {
        cancelRelease();
        pointerActive = false;
        nativeControlScroll = false;
        preserveAnchor = false;
        sentKey = id;
        pausedForQuestion = false;
        mode = "sent";
        resize();
      },
    };
    remember();
    resize();
    return () => {
      observer.disconnect();
      scrolling.removeEventListener("scroll", onScroll);
      scrolling.removeEventListener("wheel", onWheel);
      scrolling.removeEventListener("touchstart", onTouchStart);
      scrolling.removeEventListener("touchmove", onTouchMove);
      scrolling.removeEventListener("keydown", onKey);
      scrolling.removeEventListener("pointerdown", onPointer, true);
      transcript.removeEventListener("click", onPointer, true);
      window.removeEventListener("pointerup", onPointerUp, true);
      window.removeEventListener("pointercancel", finishPointer, true);
      cancelRelease();
      controller.current = null;
    };
  }, [options.conversationId, mountedScroller]);

  useLayoutEffect(() => {
    if (!options.sentTurnId || previousSent.current === options.sentTurnId) return;
    const sentId = options.sentTurnId;
    const exists = options.messages.some(
      (message) =>
        message.role === "user" &&
        [message.id, message.clientMessageId, message.renderKey].includes(sentId),
    );
    if (exists) {
      previousSent.current = options.sentTurnId;
      controller.current?.sent(options.sentTurnId);
    }
  }, [options.messages, options.sentTurnId]);

  return { dockHeight, bindScroller };
}
