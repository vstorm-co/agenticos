"use client";

import { Blobatar } from "@blobatar/react";
import { thinking } from "blobatar/expression";

import "blobatar/motion.css";

import { avatarHue } from "@/lib/avatar-color";
import { cn } from "@/lib/utils";

export interface AvatarFaceProps {
  /** The stable id the face is generated from, so one entity keeps its face. */
  seed: string;
  /** The chosen colour slot (1..10); null or absent lets the seed pick the hue. */
  colorSlot?: number | null;
  /** Draws the face mid-thought, for an agent that is working right now. */
  thinking?: boolean;
  className?: string;
}

/**
 * The face somebody wears when they never uploaded a picture.
 *
 * Generated from the seed rather than stored, so the same id always draws the
 * same face and a person or an agent is recognisable across every screen
 * without a row, a request or an upload. A disc behind it, because every avatar
 * in this product is already a circle and a bare silhouette inside one leaves a
 * ring of empty space where the fill used to be.
 *
 * Alive, everywhere. Every face blinks, breathes and looks around, and that is
 * a deliberate trade rather than a free one: motion is CSS acting on the shapes,
 * a document inside an `<img>` is isolated and no stylesheet reaches into it, so
 * animating means rendering inline SVG - roughly a dozen nodes per face instead
 * of one image. The motion itself is seeded CSS with no timer per avatar, so it
 * is the node count that scales with a long list, not the work.
 *
 * Decorative, and deliberately: every one of these is drawn beside the name it
 * stands for, so a `<title>` on it would be the same words read twice - and it
 * would put them in the DOM as text, where a list that already renders the name
 * suddenly holds it twice.
 *
 * `thinking` is a change of expression on a creature already moving, which is
 * the whole reason it reads as one. `blobatar/motion.css` is imported here
 * rather than in a layout, so the stylesheet arrives with the only component
 * that can ask for it; it is also what honours `prefers-reduced-motion`, under
 * which every face here holds still.
 */
export function AvatarFace({ seed, colorSlot, thinking: isThinking, className }: AvatarFaceProps) {
  return (
    <Blobatar
      name={seed}
      hue={avatarHue(colorSlot)}
      background="circle"
      animate="always"
      expression={isThinking ? thinking : undefined}
      className={cn("h-full w-full", className)}
    />
  );
}
