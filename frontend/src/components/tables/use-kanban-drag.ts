"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { DragEvent, PointerEvent } from "react";

/** Pointer capture keeps a card under the cursor; native events remain a fallback.
 * A move starts after six pixels so clicking a card still opens it. */
export function useKanbanDrag<T>(onDrop: (item: T, targetOptionId: string | null) => void) {
  const [draggingItem, setDraggingItem] = useState<T | null>(null);
  const [position, setPosition] = useState<{ x: number; y: number } | null>(null);
  const [overLane, setOverLane] = useState<string | null>(null);
  const pointer = useRef<{ id: number; item: T; x: number; y: number; active: boolean } | null>(
    null,
  );
  const suppressClick = useRef(false);
  const reset = useCallback(() => {
    pointer.current = null;
    setDraggingItem(null);
    setPosition(null);
    setOverLane(null);
  }, []);
  useEffect(() => {
    if (draggingItem === null) return;
    const cancel = (event: KeyboardEvent) => {
      if (event.key === "Escape") reset();
    };
    document.addEventListener("keydown", cancel);
    return () => document.removeEventListener("keydown", cancel);
  }, [draggingItem, reset]);
  const hitLane = (event: PointerEvent) =>
    document
      .elementFromPoint?.(event.clientX, event.clientY)
      ?.closest<HTMLElement>("[data-kanban-lane]") ?? null;

  function cardProps(item: T) {
    return {
      draggable: false,
      style: { opacity: draggingItem === item ? 0.35 : undefined },
      onPointerDown: (event: PointerEvent<HTMLDivElement>) => {
        if (
          event.button !== 0 ||
          (event.target instanceof Element && event.target.closest("[data-kanban-actions]"))
        )
          return;
        suppressClick.current = false;
        pointer.current = {
          id: event.pointerId,
          item,
          x: event.clientX,
          y: event.clientY,
          active: false,
        };
      },
      onPointerMove: (event: PointerEvent<HTMLDivElement>) => {
        const current = pointer.current;
        if (current === null || current.id !== event.pointerId) return;
        if (!current.active && Math.hypot(event.clientX - current.x, event.clientY - current.y) < 6)
          return;
        if (!current.active) event.currentTarget.setPointerCapture?.(event.pointerId);
        current.active = true;
        suppressClick.current = true;
        event.preventDefault();
        setDraggingItem(current.item);
        setPosition({ x: event.clientX, y: event.clientY });
        const lane = hitLane(event);
        setOverLane(
          lane?.dataset.kanbanAccepts === "true" ? (lane.dataset.kanbanLane ?? null) : null,
        );
        const board = event.currentTarget.closest<HTMLElement>("[data-kanban-board]");
        if (board) {
          const rect = board.getBoundingClientRect();
          if (event.clientX > rect.right - 60) board.scrollLeft += 18;
          else if (event.clientX < rect.left + 60) board.scrollLeft -= 18;
        }
      },
      onPointerUp: (event: PointerEvent<HTMLDivElement>) => {
        const current = pointer.current;
        if (current?.id !== event.pointerId) return;
        const lane = hitLane(event);
        if (current.active && lane?.dataset.kanbanAccepts === "true")
          onDrop(
            current.item,
            lane.dataset.kanbanLane === "__none__" ? null : (lane.dataset.kanbanLane ?? null),
          );
        reset();
      },
      onPointerCancel: reset,
      onClickCapture: (event: React.MouseEvent) => {
        if (suppressClick.current) {
          event.preventDefault();
          event.stopPropagation();
          suppressClick.current = false;
        }
      },
      onDragStart: (event: DragEvent) => {
        if (pointer.current !== null) {
          event.preventDefault();
          return;
        }
        // Firefox starts no drag from an element that is not a link or an image
        // unless the drag carries data. What it carries is never read: the drop
        // reads `draggingItem`.
        event.dataTransfer.setData("text/plain", "");
        event.dataTransfer.effectAllowed = "move";
        setDraggingItem(item);
      },
      onDragEnd: () => setDraggingItem(null),
    };
  }

  /** `accepts=false` for the read-only archived catch-all lane: a drop there is refused before it fires. */
  function laneProps(targetOptionId: string | null, accepts: boolean) {
    return {
      "data-kanban-lane": targetOptionId ?? "__none__",
      "data-kanban-accepts": String(accepts),
      "data-drag-over": overLane === (targetOptionId ?? "__none__") || undefined,
      onDragOver: (event: DragEvent) => {
        if (accepts) event.preventDefault();
      },
      onDrop: (event: DragEvent) => {
        event.preventDefault();
        if (accepts && draggingItem !== null) onDrop(draggingItem, targetOptionId);
        setDraggingItem(null);
      },
    };
  }

  return { draggingItem, position, cardProps, laneProps };
}
