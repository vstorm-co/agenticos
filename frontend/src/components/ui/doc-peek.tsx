import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface DocPeekProps {
  /**
   * How many pages to draw behind the front one - the rest of a skill's files,
   * an artifact's earlier versions. Capped at two: past that a stack is a
   * texture, not a count, and the corner `badge` says the number.
   */
  sheets?: number;
  /** A small label in the well's top-right corner - "+3 files", "v7". */
  badge?: ReactNode;
  /** The front page's content, laid out on the paper. */
  children: ReactNode;
  /** Sizes the well; the paper and the stack fill it. */
  className?: string;
  /** Padding inside the paper, for content that should bleed to its edges. */
  paperClassName?: string;
  /** `compact` tucks the page closer to the well's edges, for a small file tile. */
  size?: "default" | "compact";
}

/**
 * A card's content as a sheet of paper resting in a well, with the rest of it
 * stacked behind.
 *
 * One shape for every card that stands for a document - a skill, a context
 * file, an artifact, a file in a workspace - so the same idea looks the same on
 * every screen. The page's top is shown and the rest fades out, which says
 * "this is the start of something longer" without a "read more". Hovering the
 * card that holds it (a `group`) lifts the page and fans the stack; the motion
 * is in `globals.css` beside the reduced-motion rule that removes it.
 *
 * Decorative by construction: the stack is `aria-hidden`, and the card around
 * it carries the name and description a screen reader announces.
 */
export function DocPeek({
  sheets = 0,
  badge,
  children,
  className,
  paperClassName,
  size = "default",
}: DocPeekProps) {
  const behind = Math.max(0, Math.min(2, sheets));
  return (
    <div
      className={cn(
        "bg-peek-well relative overflow-hidden",
        size === "compact" && "peek-compact",
        className,
      )}
    >
      {behind >= 2 && <span aria-hidden className="peek-sheet peek-sheet-2 bg-peek-sheet" />}
      {behind >= 1 && <span aria-hidden className="peek-sheet peek-sheet-1 bg-peek-sheet" />}
      <div
        className={cn(
          "peek-paper bg-peek-paper",
          size === "compact" ? "px-2.5 py-2" : "px-4 py-3.5",
          paperClassName,
        )}
      >
        {children}
      </div>
      {badge != null && (
        <span className="bg-foreground/85 text-background absolute top-2.5 right-2.5 rounded-full px-2 py-0.5 font-mono text-[10px] leading-4 tracking-wide backdrop-blur-sm">
          {badge}
        </span>
      )}
    </div>
  );
}
