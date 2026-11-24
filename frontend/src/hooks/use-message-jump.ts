"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";

export type MessageJumpStatus = "idle" | "loading" | "found" | "unavailable" | "failed";

export interface MessageJumpState {
  status: MessageJumpStatus;
  retry: () => void;
  cancel: () => void;
}

/** Search only the authorized transcript supplied by the caller, including merged segments. */
export function findMessageAnchor(container: HTMLElement, id: string): HTMLElement | undefined {
  return [
    ...container.querySelectorAll<HTMLElement>(
      "[data-message-id], [data-message-ids], [data-thread-root]",
    ),
  ].find(
    (element) =>
      element.dataset.messageId === id ||
      element.dataset.threadRoot === id ||
      element.dataset.messageIds?.split(" ").includes(id),
  );
}

export function revealMessageAnchor(target: HTMLElement): void {
  target
    .querySelectorAll<HTMLButtonElement>('button[data-message-disclosure][aria-expanded="false"]')
    .forEach((toggle) => toggle.click());
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  target.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "center" });
  target.tabIndex = -1;
  target.focus({ preventScroll: true });
  if (!reduced)
    target.animate?.(
      [
        { backgroundColor: "var(--reply-flash, rgb(127 127 127 / 0.14))" },
        { backgroundColor: "transparent" },
      ],
      { duration: 1400, easing: "ease-out" },
    );
}

/** Walk the existing authorized cursor one page at a time; a failed/no-op read stops the walk. */
export function useMessageJump({
  messageId,
  scope,
  revision = 0,
  ready,
  messageIds,
  firstMessageId,
  hasEarlier,
  loadingEarlier,
  loadEarlier,
  container,
  beforeJump,
}: {
  messageId: string | null;
  /** Account, tenant, conversation, selection version and optional thread root. */
  scope: string;
  revision?: number;
  ready: boolean;
  messageIds: readonly string[];
  firstMessageId: string | null;
  hasEarlier: boolean;
  loadingEarlier: boolean;
  loadEarlier: () => Promise<unknown>;
  container: RefObject<HTMLElement | null>;
  beforeJump: () => void;
}): MessageJumpState {
  const key = JSON.stringify([scope, messageId, revision]);
  const current = useRef(key);
  const alive = useRef(true);
  const requested = useRef<string | null>(null);
  const prepared = useRef<string | null>(null);
  const revealed = useRef<string | null>(null);
  const [attempt, setAttempt] = useState<{
    key: string;
    cursor: string | null;
    failed: boolean;
  } | null>(null);
  const [cancelled, setCancelled] = useState<string | null>(null);
  const found = messageId !== null && messageIds.includes(messageId);
  const stopped = cancelled === key;
  const failed =
    attempt?.key === key &&
    (attempt.failed || (!loadingEarlier && attempt.cursor === firstMessageId && !found));
  useLayoutEffect(() => {
    current.current = key;
  }, [key]);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useLayoutEffect(() => {
    if (messageId === null || !ready || stopped) return;
    if (prepared.current !== key) {
      beforeJump();
      prepared.current = key;
    }
    if (!found || revealed.current === key || container.current === null) return;
    const target = findMessageAnchor(container.current, messageId);
    if (target !== undefined) {
      revealMessageAnchor(target);
      revealed.current = key;
    }
  });
  useEffect(() => {
    if (messageId === null || !ready || stopped || found || failed || !hasEarlier || loadingEarlier)
      return;
    const cursor = JSON.stringify([key, firstMessageId]);
    if (requested.current === cursor) return;
    requested.current = cursor;
    void loadEarlier().then(
      () => {
        if (alive.current && current.current === key)
          setAttempt({ key, cursor: firstMessageId, failed: false });
      },
      () => {
        if (alive.current && current.current === key)
          setAttempt({ key, cursor: firstMessageId, failed: true });
      },
    );
  }, [
    messageId,
    ready,
    stopped,
    found,
    failed,
    hasEarlier,
    loadingEarlier,
    key,
    firstMessageId,
    loadEarlier,
  ]);

  const retry = useCallback(() => {
    beforeJump();
    requested.current = null;
    setAttempt(null);
    setCancelled(null);
  }, [beforeJump]);
  const cancel = useCallback(() => {
    setCancelled(key);
  }, [key]);
  const status: MessageJumpStatus =
    messageId === null || stopped
      ? "idle"
      : !ready || loadingEarlier
        ? "loading"
        : found
          ? "found"
          : failed
            ? "failed"
            : !hasEarlier
              ? "unavailable"
              : "loading";
  return { status, retry, cancel };
}
