"use client";

import { useState } from "react";
import type { DragEvent } from "react";

/**
 * Drag an item between kanban lanes.
 *
 * The design this issue's plan named reuses the hand-rolled pointer-event drag
 * `dashboard-editor.tsx` built for reordering dashboard widgets. That system
 * tracks a hit-tested drop target across `pointermove` because a dashboard grid
 * reorders items *within and across* free-form containers - there is no
 * "container" the browser already understands. A kanban lane is exactly what
 * the browser's own drag-and-drop model *is* for: one card moving into one of a
 * fixed set of drop targets. Native HTML5 drag-and-drop (`draggable`,
 * `dragstart`/`dragover`/`drop`) gets the same outcome - a card dropped in
 * another lane fires one callback - with less code and no pointer math to keep
 * in sync with a second implementation, at the cost of the dashboard editor's
 * live reordering preview while dragging, which a kanban board does not need:
 * the board asks only "which lane did this land in", never "where in the lane".
 *
 * Generic over the dragged item (a full `RecordRead`, not just its id) so the
 * drop handler always has the revision it needs to write with, without a
 * second lookup back into whichever lane's page happened to hold it.
 *
 * Every `draggable` card is also given a keyboard-reachable equivalent
 * elsewhere (`table-kanban-view.tsx`'s "Move to…" menu per card), since drag
 * itself has no keyboard affordance.
 */
export function useKanbanDrag<T>(onDrop: (item: T, targetOptionId: string | null) => void) {
  const [draggingItem, setDraggingItem] = useState<T | null>(null);

  function cardProps(item: T) {
    return {
      draggable: true,
      onDragStart: () => setDraggingItem(item),
      onDragEnd: () => setDraggingItem(null),
    };
  }

  /** `accepts=false` for the read-only archived catch-all lane: a drop there is refused before it fires. */
  function laneProps(targetOptionId: string | null, accepts: boolean) {
    return {
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

  return { draggingItem, cardProps, laneProps };
}
