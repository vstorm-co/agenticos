"use client";

import { useState } from "react";

import { Separator } from "@/components/ui/separator";

export const CHAT_PANEL_INITIAL_WIDTH = 55;
const MIN_WIDTH = 35;
const MAX_WIDTH = 65;
const bounded = (width: number) => Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, width));

/** A chat pane's pointer-captured boundary, also adjustable with the keyboard. */
export function ChatPanelResize({
  label,
  controls,
  width,
  onWidthChange,
  getBounds,
  className,
}: {
  label: string;
  controls: string;
  width: number;
  onWidthChange: (width: number) => void;
  getBounds: () => DOMRect | undefined;
  className?: string;
}) {
  const [dragging, setDragging] = useState(false);
  return (
    <>
      <Separator
        decorative={false}
        orientation="vertical"
        tabIndex={0}
        aria-label={label}
        aria-controls={controls}
        aria-valuemin={MIN_WIDTH}
        aria-valuemax={MAX_WIDTH}
        aria-valuenow={Math.round(width)}
        className={className}
        onKeyDown={(event) => {
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
          event.preventDefault();
          onWidthChange(
            event.key === "Home"
              ? MIN_WIDTH
              : event.key === "End"
                ? MAX_WIDTH
                : bounded(width + (event.key === "ArrowLeft" ? 2 : -2)),
          );
        }}
        onPointerDown={(event) => {
          if (event.button !== 0) return;
          event.preventDefault();
          event.currentTarget.setPointerCapture(event.pointerId);
          setDragging(true);
        }}
        onPointerMove={(event) => {
          if (!dragging) return;
          const bounds = getBounds();
          if (bounds && bounds.width > 0)
            onWidthChange(bounded(((bounds.right - event.clientX) / bounds.width) * 100));
        }}
        onPointerUp={() => setDragging(false)}
        onPointerCancel={() => setDragging(false)}
        onLostPointerCapture={() => setDragging(false)}
        onDoubleClick={() => onWidthChange(CHAT_PANEL_INITIAL_WIDTH)}
      />
      {dragging && (
        <div data-native-browser-blocked className="fixed inset-0 z-40 cursor-col-resize" />
      )}
    </>
  );
}
