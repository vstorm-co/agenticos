/**
 * A skill's versions, its forks, and the agents bound to them.
 *
 * Versions never change once saved, and each line - main or one fork - numbers its
 * own from 1. An agent follows main's latest version, stays pinned on an older
 * main version, or uses a fork: a named line started from one main version.
 */

import type { AgentCheckState } from "./skill-checks";

export type SkillVersionSource =
  | "backfill"
  | "created"
  | "edit"
  | "resources"
  | "library"
  | "workspace"
  | "improve"
  | "restore"
  /** A fork took main's changes in. */
  | "catch_up"
  /** Main took a fork's changes in. */
  | "from_fork";

export interface SkillVersionRef {
  id: string;
  number: number;
}

export interface SkillLineVersionRef extends SkillVersionRef {
  /** Null on the main line. */
  fork_id: string | null;
}

export interface SkillVersionSummary {
  id: string;
  skill_id: string;
  /** Null on the main line. */
  fork_id: string | null;
  number: number;
  source: SkillVersionSource;
  /** What this version changed from: the line's previous version, or a fork's base. */
  previous: SkillLineVersionRef | null;
  restored_from: SkillLineVersionRef | null;
  proposal_id: string | null;
  created_by: { id: string; name: string } | null;
  created_at: string;
  /** Agents whose served versions resolve to it. */
  agents: number;
}

export interface SkillVersionResource {
  name: string;
  description: string | null;
  size_bytes: number;
  /** The SHA-256 of the file's content: equal digests, same content. */
  digest: string;
}

export interface SkillVersionRead extends SkillVersionSummary {
  description: string;
  content: string;
  resources: SkillVersionResource[];
}

export interface SkillVersionList {
  items: SkillVersionSummary[];
  total: number;
}

export interface SkillFork {
  id: string;
  skill_id: string;
  name: string;
  /** The main version it is based on now: where it started, or the one it last caught up with. */
  base: SkillVersionRef;
  /** The main version it started from, which catching up never moves. */
  started_from: SkillVersionRef;
  /** Null until the fork saves a version of its own; it serves its base until then. */
  latest: SkillVersionRef | null;
  changes: number;
  behind_main: number;
  agents: number;
  archive_candidate: boolean;
  archived_at: string | null;
  created_at: string;
}

export interface SkillForkList {
  items: SkillFork[];
  total: number;
}

export type SkillBindingState = "main" | "pinned" | "fork";

export interface SkillBinding {
  state: SkillBindingState;
  /** The concrete version the binding resolves to now. */
  version: SkillLineVersionRef;
  fork: { id: string; name: string; base_number: number; changes: number } | null;
  behind_main: number;
}

export interface SkillAgentUsage {
  agent: {
    id: string;
    name: string;
    slug: string;
    has_avatar?: boolean;
    avatar_color?: number | null;
  };
  /** Set when only one of the agent's specialists binds the skill. */
  via_specialist: string | null;
  /** Bound only in the draft, so it counts on no line; `binding` is the draft's. */
  draft_only: boolean;
  /** The default environment's binding, or the draft's when `draft_only`. */
  binding: SkillBinding;
  agent_version: number | null;
  /** Only the environments whose binding differs from `binding`. */
  environments: { id: string; name: string; agent_version: number; binding: SkillBinding }[];
  draft_differs: boolean;
  /** Whether the caller may change this agent's binding, in its draft at least. */
  can_change: boolean;
  /** Whether the change also goes live, as a new published version of the agent. */
  can_publish: boolean;
  /** The newest check of the version it serves now, as it found this agent; null if never checked. */
  checked?: AgentCheckRef | null;
  /** Every version a check made after measuring it on this agent, newest check first. */
  checked_versions?: AgentCheckRef[];
  /** The skill versions this agent's own answers used; empty without `runs:view`. */
  answered_with?: string[];
}

/** What a check found on one agent, for the version that check made. */
export interface AgentCheckRef {
  check_id: string;
  version_id: string;
  state: AgentCheckState;
  sample: "own_questions" | "skill_set_only" | "own_not_asked" | null;
  at: string;
}

export interface SkillAgentList {
  main_latest: SkillVersionRef;
  items: SkillAgentUsage[];
  /** Agents using the skill that the caller may not see, counted rather than named. */
  hidden: number;
}

/** One agent's use of a skill over the window. */
export interface SkillUsageAgent {
  agent_id: string;
  agent_name: string;
  /** Runs that opened the skill or read one of its files. */
  loads: number;
  resource_reads: number;
  workspace_reads: number;
  last_loaded_at: string | null;
  /** The handle the agent's generated face is drawn from. */
  slug: string;
  has_avatar: boolean;
  avatar_color: number | null;
  /** Loads on every UTC day from `since` to today, oldest first, zeros included. */
  daily: { date: string; loads: number }[];
}

/** How often a skill was used, by agent, leaving out eval and test-panel runs. */
export interface SkillUsage {
  days: number;
  since: string;
  /** The sum of `loads` over the agents listed. */
  loads: number;
  agents: SkillUsageAgent[];
  /** Agents that used the skill and the caller cannot see. */
  hidden_agents: number;
  hidden_loads: number;
}
