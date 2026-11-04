"use client";

import { Blobatar } from "@blobatar/react";
import { useGaze } from "@blobatar/react/gaze";
import { happy, love, sleepy, surprised, thinking } from "blobatar/expression";

import "blobatar/motion.css";
import "blobatar/gaze.css";

import type { Expression } from "@/lib/desktop/blobby-engine";
import type { Face } from "@/lib/desktop/blobby-cast";

const EXPRESSIONS = { happy, love, sleepy, surprised, thinking } as const;

interface BlobbyFaceProps {
  face: Face;
  expression: Expression;
  /** Where to look, in this page's coordinates; `null` hands the eyes back to their own idle glance. */
  gaze: { x: number; y: number } | null;
  size: number;
}

/**
 * Blobby's face: a `blobatar`, alive, wearing whatever expression the moment
 * calls for, with its eyes on the cursor when it is standing about.
 */
export function BlobbyFace({ face, expression, gaze, size }: BlobbyFaceProps) {
  const { ref } = useGaze({ travel: 3, lookAt: gaze });
  return (
    <Blobatar
      ref={ref}
      name={face.seed}
      hue={face.hue}
      traits={face.traits}
      size={size}
      animate="always"
      expression={expression === "idle" ? undefined : EXPRESSIONS[expression]}
    />
  );
}
