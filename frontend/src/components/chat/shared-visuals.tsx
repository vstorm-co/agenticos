"use client";

import { useMemo } from "react";

import type { ToolCall } from "@/types";
import { TurnVisuals } from "./visual-panel";

/** A drawing in a thread shared by link, as the server rebuilt it. */
export interface SharedVisual {
  id: string;
  title: string;
  kind: "svg" | "html" | "mermaid";
  content: string;
}

/**
 * A shared turn's drawings, in the panel the chat draws them in.
 *
 * The server sends each one finished - revisions applied, pictures inlined - and
 * never the call that made it, so here it is simply a drawing: no saving, no
 * asking the agent, nothing that needs the reader to be signed in.
 */
export function SharedVisuals({ visuals }: { visuals: readonly SharedVisual[] }) {
  const calls = useMemo<ToolCall[]>(
    () =>
      visuals.map((visual) => ({
        id: visual.id,
        name: "draw",
        args: { title: visual.title, kind: visual.kind, content: visual.content },
        status: "completed",
      })),
    [visuals],
  );
  return <TurnVisuals calls={calls} />;
}
