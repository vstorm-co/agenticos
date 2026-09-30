"use client";

import { useEffect, useRef, type FocusEvent, type KeyboardEvent } from "react";

import { RecordCellEditor } from "./record-cell-editor";
import type { CellValue, ColumnDef } from "@/types/tables";

// A select's list, a popover: rendered in a portal, but still this cell's own.
const POPUP = '[data-radix-popper-content-wrapper], [role="listbox"], [role="dialog"]';

/**
 * One grid cell being edited in place: the column's own control, focused as it
 * opens.
 *
 * A text or number field commits as it loses focus, so Enter commits by
 * blurring it. Escape leaves without writing - the cancel is remembered, so a
 * blur the unmount itself causes cannot commit what was being thrown away.
 * Focus leaving the cell for anything but its own popup ends the edit, and a
 * single choice ends it at once: there is nothing left to do in the cell.
 */
export function InlineCell({
  column,
  value,
  onCommit,
  onDone,
}: {
  column: ColumnDef;
  value: CellValue;
  onCommit: (value: CellValue) => void;
  onDone: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const cancelled = useRef(false);

  useEffect(() => {
    ref.current?.querySelector<HTMLElement>("input, textarea, button")?.focus();
  }, []);

  const change = (next: CellValue) => {
    if (cancelled.current) return;
    onCommit(next);
    if (column.type === "single_select" || column.type === "boolean") onDone();
  };

  const keyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      cancelled.current = true;
      onDone();
      return;
    }
    const target = event.target;
    const submits =
      event.key === "Enter" &&
      (target instanceof HTMLInputElement ||
        (target instanceof HTMLTextAreaElement && (event.metaKey || event.ctrlKey)));
    if (submits) {
      event.preventDefault();
      (target as HTMLElement).blur();
    }
  };

  const focusOut = (event: FocusEvent<HTMLDivElement>) => {
    const next = event.relatedTarget;
    if (next instanceof Element && (event.currentTarget.contains(next) || next.closest(POPUP))) {
      return;
    }
    onDone();
  };

  return (
    // Keys and focus bubble here from the control; the cell itself takes neither.
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions
    <div
      ref={ref}
      // No width of its own, so opening the editor never resizes the column
      // under the pointer; it fills the cell it was opened in instead.
      className="-mx-2 -my-1.5 w-0 min-w-[calc(100%+1rem)]"
      onClick={(event) => event.stopPropagation()}
      onKeyDown={keyDown}
      onBlur={focusOut}
    >
      <RecordCellEditor column={column} value={value} onChange={change} />
    </div>
  );
}
