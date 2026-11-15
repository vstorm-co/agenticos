/**
 * Catching a fork up with main, and moving a fork to main: the three-way merge such a
 * session works on, and who main has left behind.
 */

import type { SkillVersionRef } from "@/types/skill-versions";

/** Which way a merge goes: main into a fork, or a fork into main. */
export type MergeKind = "catch_up" | "to_main";

/** Which side a text or a file comes from, or that the two sides disagree. */
export type MergeState = "same" | "fork" | "main" | "both" | "conflict";

/** One text of the merge: the description, or a part of the instructions. */
export interface MergeText {
  state: MergeState;
  base: string;
  fork: string;
  main: string;
  /** What the merge says; null for a conflict nobody has settled yet. */
  result: string | null;
  /** The assistant's text for a conflict, kept beside a person's rewrite of it. */
  proposed: string | null;
  edited: boolean;
}

export interface MergeFileSide {
  description: string | null;
  size_bytes: number;
}

/** One file of the merge; a side is null where the file is absent. */
export interface MergeFile {
  name: string;
  state: MergeState;
  base: MergeFileSide | null;
  fork: MergeFileSide | null;
  main: MergeFileSide | null;
  /** The side the merge keeps; null for a conflict waiting for a person. */
  take: "fork" | "main" | null;
}

export interface SkillMerge {
  id: string;
  run_id: string;
  skill_id: string;
  fork_id: string;
  kind: MergeKind;
  /** The main version the fork is based on. */
  base: SkillVersionRef;
  /** The fork's newest version. */
  fork: SkillVersionRef;
  /** Main's newest version. */
  main: SkillVersionRef;
  description: MergeText;
  parts: MergeText[];
  files: MergeFile[];
  conflicts: number;
  /** Texts and files still waiting for a person; the check waits for none. */
  unresolved: number;
  updated_at: string | null;
}

/** What a catch-up or a move to main would merge, and what it costs before Changes. */
export interface SkillMergeEstimate {
  line: { fork_id: string | null; name: string };
  source_fork: { fork_id: string | null; name: string } | null;
  base_version: SkillVersionRef;
  conflicts: number;
  total_usd: string;
  agents: number;
  hidden_agents: number;
  affordable: boolean;
}

interface BehindMainFacts {
  skill: { id: string; name: string };
  /** Set when it is one of the agent's specialists that is pinned. */
  via_specialist: string | null;
  agents: number;
  /** The main version it is on: the pinned one, or the one the fork is based on. */
  version: SkillVersionRef;
  main_latest: SkillVersionRef;
  behind_main: number;
  /** Whether the caller may bring it along from here. */
  can_act: boolean;
}

/** A pinned agent or a fork that main has moved past. */
export type BehindMain = BehindMainFacts &
  (
    | { kind: "pinned"; agent: { id: string; name: string; slug: string }; fork: null }
    | {
        kind: "fork";
        agent: null;
        fork: { id: string; name: string; base_number: number; changes: number };
      }
  );

export interface BehindMainList {
  items: BehindMain[];
  total: number;
  /** Pinned agents behind main the caller may not see. */
  hidden: number;
}

/** What returning a fork's agents to main did, agent by agent. */
export interface ReturnedToMain {
  agents: {
    agent: { id: string; name: string };
    published: boolean;
    agent_version: number | null;
    /** Why it stayed on the fork. */
    refused: string | null;
  }[];
  hidden: number;
  /** Agents still reading the fork; a move waiting in a draft leaves it read. */
  remaining: number;
  archived: boolean;
}
