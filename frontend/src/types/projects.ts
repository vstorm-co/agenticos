import type { Visibility } from "./sharing";

/**
 * A project: instructions and files in one container, shared by every chat in it.
 *
 * Its chats, files and instructions are everybody's the project is shared with:
 * `chat_count` counts every chat in it, whoever started it.
 */
export interface Project {
  id: string;
  name: string;
  description: string | null;
  instructions: string;
  default_agent_id: string | null;
  /** Null when the caller may not see the default agent, or there is none. */
  default_agent_name: string | null;
  owner_user_id: string | null;
  visibility: Visibility;
  /** `service` - a container with a shell - or `state`, files the platform stores. */
  backend: "service" | "state";
  runtime: string | null;
  chat_count: number;
  last_active_at: string | null;
  shared_groups: string[];
  /** May chat in it and add files. */
  can_use: boolean;
  /** May change, share or delete it. */
  can_edit: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface ProjectList {
  items: Project[];
  total: number;
}

export interface ProjectCreate {
  name: string;
  description?: string | null;
  instructions?: string;
  default_agent_id?: string | null;
  visibility?: Visibility;
  group_ids?: string[];
  user_ids?: string[];
}

export type ProjectUpdate = Partial<
  Pick<Project, "name" | "description" | "instructions" | "default_agent_id">
>;
