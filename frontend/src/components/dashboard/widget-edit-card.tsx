"use client";

import { type PointerEvent as ReactPointerEvent, useRef, useState } from "react";
import { Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import {
  nearestRows,
  nearestSpan,
  rowCount,
  spanCols,
  type LayoutEntry,
} from "@/lib/dashboard/layouts";
import type { Period } from "@/lib/dashboard/period";
import type { Rows, Span } from "@/lib/dashboard/registry";
import { cn } from "@/lib/utils";
import { WIDGET_COMPONENTS } from "./widgets";

interface WidgetEditCardProps {
  entry: LayoutEntry;
  /** The period filter, so the live card shows the same data as the page. */
  period: Period;
  /** This card is the one being dragged — dimmed while it is held. */
  dragging: boolean;
  /** A dragged card is over this one — ringed to show where a drop would land. */
  dropTarget: boolean;
  onResize: (span: Span, rows: Rows) => void;
  onRemove: () => void;
}

/**
 * One resize grip. `hx`/`hy` are the direction the grip pulls in — `1` grows,
 * `-1` shrinks, `0` leaves that axis alone — so an edge grip changes one
 * dimension and a corner grip changes both. `wrap` places the hit area over the
 * edge or corner; `corner` picks the marker shape.
 */
interface ResizeHandle {
  hx: -1 | 0 | 1;
  hy: -1 | 0 | 1;
  wrap: string;
  corner: boolean;
}

const RESIZE_HANDLES: ResizeHandle[] = [
  {
    hx: 0,
    hy: -1,
    wrap: "top-0 left-1/2 h-3 w-10 -translate-x-1/2 -translate-y-1/2 cursor-ns-resize",
    corner: false,
  },
  {
    hx: 0,
    hy: 1,
    wrap: "bottom-0 left-1/2 h-3 w-10 -translate-x-1/2 translate-y-1/2 cursor-ns-resize",
    corner: false,
  },
  {
    hx: -1,
    hy: 0,
    wrap: "top-1/2 left-0 h-10 w-3 -translate-x-1/2 -translate-y-1/2 cursor-ew-resize",
    corner: false,
  },
  {
    hx: 1,
    hy: 0,
    wrap: "top-1/2 right-0 h-10 w-3 translate-x-1/2 -translate-y-1/2 cursor-ew-resize",
    corner: false,
  },
  {
    hx: -1,
    hy: -1,
    wrap: "top-0 left-0 size-5 -translate-x-1/2 -translate-y-1/2 cursor-nwse-resize",
    corner: true,
  },
  {
    hx: 1,
    hy: -1,
    wrap: "top-0 right-0 size-5 translate-x-1/2 -translate-y-1/2 cursor-nesw-resize",
    corner: true,
  },
  {
    hx: -1,
    hy: 1,
    wrap: "bottom-0 left-0 size-5 -translate-x-1/2 translate-y-1/2 cursor-nesw-resize",
    corner: true,
  },
  {
    hx: 1,
    hy: 1,
    wrap: "bottom-0 right-0 size-5 translate-x-1/2 translate-y-1/2 cursor-nwse-resize",
    corner: true,
  },
];

/**
 * One placement in edit mode, rendered as the *real* widget with its live data
 * behind an editing overlay — arranging a dashboard you cannot see the contents
 * of is guesswork, so the card shows exactly what it will show once saved.
 *
 * There are no arranging buttons: the whole card is grabbed and dropped to
 * reorder, and eight grips — one per edge, one per corner — drag-resize it.
 * Both appear on hover; the card itself highlights and lifts (`dash-editable`)
 * so the grid reads as directly manipulable. The drag itself is owned by the
 * editor, delegated from the grid: the card only marks its grips `data-resize`
 * and its remove button `data-no-drag` so a press on either is not read as the
 * start of a reorder. While a grip is held a small size readout shows the
 * width×height it will snap to, and disappears on release.
 */
export function WidgetEditCard({
  entry,
  period,
  dragging,
  dropTarget,
  onResize,
  onRemove,
}: WidgetEditCardProps) {
  const t = useTranslations("dashboard");
  const rows = entry.rows ?? "r3";
  const title = t(`widgets.${entry.widget}.title`);
  const Widget = WIDGET_COMPONENTS[entry.widget];
  const cardRef = useRef<HTMLDivElement>(null);
  // The size a live resize will snap to, shown only while a grip is held.
  const [resizingTo, setResizingTo] = useState<{ span: Span; rows: Rows } | null>(null);

  // Pointer drag-resize from a grip. The card's own box maps its span and rows
  // to pixels, so a pointer delta becomes a column/row count and snaps to the
  // nearest allowed size. An axis the grip leaves alone (`hx`/`hy` of 0) keeps
  // its current size. `stopPropagation` keeps the grid's delegated drag from
  // also starting a reorder on the same press.
  const startResize = (hx: -1 | 0 | 1, hy: -1 | 0 | 1) => (event: ReactPointerEvent) => {
    event.preventDefault();
    event.stopPropagation();
    const box = cardRef.current;
    if (!box) return;
    const rect = box.getBoundingClientRect();
    const colPx = rect.width / spanCols(entry.span);
    const rowPx = rect.height / rowCount(rows);
    const startX = event.clientX;
    const startY = event.clientY;

    const move = (moveEvent: PointerEvent) => {
      const cols =
        hx === 0
          ? spanCols(entry.span)
          : Math.round((rect.width + hx * (moveEvent.clientX - startX)) / colPx);
      const rowUnits =
        hy === 0
          ? rowCount(rows)
          : Math.round((rect.height + hy * (moveEvent.clientY - startY)) / rowPx);
      const span = nearestSpan(cols);
      const nextRows = nearestRows(rowUnits);
      setResizingTo({ span, rows: nextRows });
      onResize(span, nextRows);
    };
    const up = () => {
      setResizingTo(null);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  return (
    <div
      ref={cardRef}
      className={cn(
        "dash-editable group relative h-full cursor-grab touch-none rounded-xl transition active:cursor-grabbing",
        dragging && "dash-dragging",
        dropTarget && "ring-brand ring-2 ring-offset-2",
      )}
    >
      {/* The live widget, inert while arranging. */}
      <div className="pointer-events-none h-full select-none">
        <Widget title={title} period={period} />
      </div>

      {/* Edit controls, above the widget and revealed on hover. */}
      <div className="pointer-events-none absolute inset-0 rounded-xl">
        <Button
          variant="outline"
          size="icon"
          data-no-drag
          className="bg-card/90 text-muted-foreground hover:text-destructive pointer-events-auto absolute top-2 right-2 size-7 opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
          aria-label={t("edit.hide", { title })}
          onClick={onRemove}
        >
          <Trash2 className="size-3.5" aria-hidden />
        </Button>

        {/* The size a live resize will snap to, shown only while a grip is held. */}
        {resizingTo ? (
          <span className="bg-brand text-brand-foreground pointer-events-none absolute top-2 left-2 rounded-md px-2 py-0.5 text-xs font-medium tabular-nums shadow-sm">
            {t("edit.sizeBadge", {
              cols: spanCols(resizingTo.span),
              rows: rowCount(resizingTo.rows),
            })}
          </span>
        ) : null}

        {RESIZE_HANDLES.map((handle) => (
          <span
            key={`${handle.hx}:${handle.hy}`}
            data-resize
            role="presentation"
            aria-hidden
            onPointerDown={startResize(handle.hx, handle.hy)}
            className={cn(
              "pointer-events-auto absolute z-10 flex items-center justify-center opacity-0 transition-opacity group-hover:opacity-100",
              handle.wrap,
            )}
          >
            <span
              className={cn(
                handle.corner
                  ? "border-brand bg-card size-2.5 rounded-sm border-2"
                  : "bg-brand/70 rounded-full",
                !handle.corner && (handle.hx === 0 ? "h-1 w-8" : "h-8 w-1"),
              )}
            />
          </span>
        ))}
      </div>
    </div>
  );
}
