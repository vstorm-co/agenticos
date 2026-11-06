"use client";

import { useLayoutEffect, useRef, type RefObject } from "react";
import { scrollGently } from "@/lib/scroll-gently";
import type { ChatMessage } from "@/types";

/** Leave room for the reply so a newly sent message can sit near the top. */
export function replySpace(viewport: number, dock: number, turnHeight: number): number {
  return Math.max(0, Math.round(viewport - dock - turnHeight - 24));
}

export function useSentTurnAnchor(
  messages: ChatMessage[],
  scrollerRef: RefObject<HTMLDivElement | null>,
  contentRef: RefObject<HTMLDivElement | null>,
  spacerRef: RefObject<HTMLDivElement | null>,
  anchoredRef: RefObject<boolean>,
  sentTurnId: string | null | undefined,
  readerScrolledUpRef: RefObject<boolean>,
): void {
  const previous = useRef<string | null>(null);
  // Only an explicit send owns the viewport. Draining the outbox must not
  // repeatedly pull the reader away from an earlier answer.
  const sent = messages.find(
    (message) =>
      sentTurnId != null &&
      message.role === "user" &&
      (message.clientMessageId === sentTurnId ||
        message.renderKey === sentTurnId ||
        message.id === sentTurnId),
  );
  const key = sent ? (sentTurnId ?? null) : null;
  const current = useRef(sent);
  useLayoutEffect(() => {
    current.current = sent;
  }, [sent]);
  useLayoutEffect(() => {
    const element = scrollerRef.current;
    const transcript = contentRef.current;
    const space = spacerRef.current;
    if (!element || !transcript || !space) return;
    const changed = previous.current !== key;
    previous.current = key;
    if (changed) {
      anchoredRef.current = false;
      space.style.height = "0px";
    }
    if (!changed || !current.current) return;
    const row = Array.from(transcript.querySelectorAll<HTMLElement>("[data-message-id]")).find(
      (candidate) => candidate.dataset.messageId === current.current?.id,
    );
    if (!row) return;
    anchoredRef.current = true;
    readerScrolledUpRef.current = false;
    const size = () => {
      const turnHeight =
        transcript.getBoundingClientRect().bottom -
        row.getBoundingClientRect().top -
        space.getBoundingClientRect().height;
      const remaining = replySpace(
        element.clientHeight,
        parseFloat(getComputedStyle(element).paddingBottom) || 0,
        turnHeight,
      );
      space.style.height = `${remaining}px`;
      if (remaining === 0) anchoredRef.current = false;
    };
    size();
    const stopScrolling = scrollGently(
      element,
      element.scrollTop +
        row.getBoundingClientRect().top -
        element.getBoundingClientRect().top -
        24,
    );
    const observer = new ResizeObserver(size);
    observer.observe(transcript);
    observer.observe(element);
    return () => {
      stopScrolling();
      observer.disconnect();
    };
  }, [key, scrollerRef, contentRef, spacerRef, anchoredRef, readerScrolledUpRef]);
}
