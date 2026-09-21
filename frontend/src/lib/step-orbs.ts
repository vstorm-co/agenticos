import type { OrbState } from "thinking-orbs";

import type { StepKind } from "@/lib/tool-catalog";

/**
 * What a step's orb is doing while the step is.
 *
 * Beside `step-icons.ts` and keyed the same way, for the reason that file gives:
 * two tables answering "what kind of tool is this" drift the first time a kind
 * is added to one of them. The icon says what the tool *is* and never moves; the
 * orb says the call is still in flight, and it is the only thing in a run of
 * steps that does.
 *
 * The mapping is by what the work looks like rather than by name. Reading,
 * listing and searching are all a scan, so they share the sweeping meridian.
 * Writing and editing braid, because a file being rewritten is strands going
 * back together. A delegation wires up a constellation, which is what handing
 * work to another agent is. `shaping` is for the two that produce a picture.
 * Nothing uses `listening`: that one belongs to the microphone, where a person
 * is actually being heard.
 */
export const STEP_ORBS: Record<StepKind, OrbState> = {
  write: "weaving",
  edit: "weaving",
  read: "searching",
  list: "searching",
  search: "searching",
  shell: "solving",
  chart: "shaping",
  image: "shaping",
  knowledge: "searching",
  web: "connecting",
  skill: "composing",
  code: "solving",
  delegate: "connecting",
  mcp: "connecting",
  tool: "working",
};
