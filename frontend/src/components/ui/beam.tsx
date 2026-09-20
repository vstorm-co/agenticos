"use client";

import { BorderBeam, type BorderBeamColorVariant, type BorderBeamSize } from "border-beam";
import type { ReactNode } from "react";

import { useResolvedTheme } from "@/hooks/use-resolved-theme";

export interface BeamProps {
  children: ReactNode;
  /**
   * Whether the beam is running. False leaves the children where they are and
   * stops the frame loop, rather than unmounting the wrapper - a beam that
   * mounts on hover would remount whatever it wraps on every pass of the mouse.
   */
  active?: boolean;
  /** `line` rides the bottom edge, `md` the whole border, `sm` a compact one. */
  size?: BorderBeamSize;
  colorVariant?: BorderBeamColorVariant;
  /** Matches the beam's corners to the element's own. */
  borderRadius?: number;
  /**
   * Hover, reported from the wrapper rather than from the element inside it -
   * a card that took mouse handlers of its own would be an interactive element
   * with no keyboard or role to match.
   */
  onHoverChange?: (hovered: boolean) => void;
  /**
   * Focus anywhere inside, which is `:focus-within` as a boolean - the beam is
   * drawn in JavaScript and cannot read a CSS pseudo-class. False is reported
   * only when focus actually leaves the wrapper, not when it moves between two
   * controls inside it.
   */
  onFocusChange?: (focused: boolean) => void;
  className?: string;
}

/**
 * A glow that rides an element's border while something is happening to it.
 *
 * The theme is resolved and passed rather than left to the library's `auto`,
 * which asks `prefers-color-scheme`: this application has a theme toggle of its
 * own, so a reader on light with a dark system would get a beam tuned for the
 * wrong stage. See `useResolvedTheme`.
 *
 * Monochrome by default. A rainbow on every lit border is a product that looks
 * like a demo of itself; the grey beam still reads as motion on the one element
 * it is running on, which is all it has to say. A caller with something to
 * celebrate asks for `colorful`.
 *
 * It says "in flight" and nothing else. Anything a reader has to act on - a
 * failure, a call waiting for approval - keeps saying so in words, because a
 * glow is not a message and cannot be read by someone who cannot see it.
 */
export function Beam({
  children,
  active = true,
  size = "md",
  colorVariant = "mono",
  borderRadius,
  onHoverChange,
  onFocusChange,
  className,
}: BeamProps) {
  const theme = useResolvedTheme();
  return (
    <BorderBeam
      active={active}
      size={size}
      colorVariant={colorVariant}
      theme={theme}
      borderRadius={borderRadius}
      // Pushed well past the library's defaults. The stock values are tuned for
      // a page that is mostly beam; on a console screen that is mostly content
      // they read as a smudge somebody left on the border.
      strength={1.6}
      brightness={1.35}
      saturation={1.4}
      onMouseEnter={onHoverChange && (() => onHoverChange(true))}
      onMouseLeave={onHoverChange && (() => onHoverChange(false))}
      onFocusCapture={onFocusChange && (() => onFocusChange(true))}
      onBlurCapture={
        onFocusChange &&
        ((event) => {
          // Only when focus leaves the wrapper. Tabbing from the textarea to the
          // send button is a blur too, and a beam that went out on it would
          // flicker its way across the composer.
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
            onFocusChange(false);
          }
        })
      }
      className={className}
    >
      {children}
    </BorderBeam>
  );
}
