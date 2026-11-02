/**
 * A skill's versions, its forks, and the agents bound to them.
 *
 * Versions never change once saved, and each line - main or one fork - numbers its
 * own from 1. An agent follows main's latest version, stays pinned on an older
 * main version, or uses a fork: a named line started from one main version.
 */

export type SkillVersionSource =
  "backfill" | "created" | "edit" | "files" | "library" | "workspace" | "improve" | "restore";

export interface SkillVersionRef {
  id: string;
  number: number;
}

export interface SkillVersionSummary {
  id: string;
  skill_id: string;
  /** Null on the main line. */
  fork_id: string | null;
  number: number;
  source: SkillVersionSource;
  restored_from: { id: string; number: number; fork_id: string | null } | null;
  proposal_id: string | null;
  created_by: { id: string; name: string } | null;
  created_at: string;
}

export interface SkillVersionRead extends SkillVersionSummary {
  description: string;
  content: string;
}

export interface SkillVersionList {
  items: SkillVersionSummary[];
  total: number;
}

export interface SkillFork {
  id: string;
  skill_id: string;
  name: string;
  /** The main version it started from. */
  base: SkillVersionRef;
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
  version: SkillVersionRef & { fork_id: string | null };
  fork: { id: string; name: string; base_number: number; changes: number } | null;
  behind_main: number;
}

export interface SkillAgentUsage {
  agent: {
    id: string;
    name: string;
    slug: string;
    has_avatar?: boolean;
    avatar_color?: string | null;
  };
  /** Set when only one of the agent's specialists binds the skill. */
  via_specialist: string | null;
  /** The default environment's binding; null when the agent was never published. */
  published: SkillBinding | null;
  agent_version: number | null;
  /** Only the environments whose binding differs from `published`. */
  environments: { id: string; name: string; agent_version: number; binding: SkillBinding }[];
  /** Only when the draft's binding differs from `published`. */
  draft: SkillBinding | null;
  /** Whether the caller may change this agent's binding. */
  can_change?: boolean;
}

export interface SkillAgentList {
  main_latest: SkillVersionRef;
  items: SkillAgentUsage[];
  /** Agents using the skill that the caller may not see, counted rather than named. */
  hidden: number;
}
