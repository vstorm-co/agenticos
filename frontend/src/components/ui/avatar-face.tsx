"use client";

import { Blobatar } from "@blobatar/react";
import { thinking } from "blobatar/expression";

import "blobatar/motion.css";

import { AVATAR_TRAITS } from "@/lib/avatar-policy";
import { avatarHue } from "@/lib/avatar-color";
import { cn } from "@/lib/utils";

export interface AvatarFaceProps {
  /** The stable id the face is generated from, so one entity keeps its face. */
  seed: string;
  /** The chosen colour slot (1..10); null or absent lets the seed pick the hue. */
  colorSlot?: number | null;
  /** Draws the face mid-thought, for an agent that is working right now. */
  thinking?: boolean;
  /** Omit the backdrop for compact agent portraits in chat. */
  background?: boolean;
  className?: string;
}

/**
 * The face somebody wears when they never uploaded a picture.
 *
 * Generated from the seed rather than stored, so the same id always draws the
 * same face and a person or an agent is recognisable across every screen
 * without a row, a request or an upload. A disc behind it, because every avatar
 * normally sits in a circle. Chat omits the disc and enlarges the face to use
 * the portrait area without another frame.
 *
 * Idle faces animate on hover; only an agent doing work moves continuously.
 * Seeded CSS needs no timer per avatar and respects reduced motion.
 *
 * Decorative, and deliberately: every one of these is drawn beside the name it
 * stands for, so a `<title>` on it would be the same words read twice - and it
 * would put them in the DOM as text, where a list that already renders the name
 * suddenly holds it twice.
 *
 * `thinking` activates continuous motion and a thinking expression.
 * The motion stylesheet honours `prefers-reduced-motion`, under which every
 * face holds still.
 */
export function AvatarFace({
  seed,
  colorSlot,
  thinking: isThinking,
  background = true,
  className,
}: AvatarFaceProps) {
  return (
    <Blobatar
      name={seed}
      hue={avatarHue(colorSlot)}
      background={background ? "circle" : false}
      traits={AVATAR_TRAITS}
      animate={isThinking ? "always" : "hover"}
      expression={isThinking ? thinking : undefined}
      className={cn("h-full w-full", className)}
    />
  );
}
