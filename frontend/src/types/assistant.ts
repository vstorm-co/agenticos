/** The organization's AI Architect, as the widget and its settings read it (#2063). */

export type AssistantStatus = "ready" | "needs_model" | "disabled" | "unavailable";

export interface AssistantState {
  status: AssistantStatus;
  agent_id: string | null;
  /** Its handle, which its default face is drawn from. */
  slug: string | null;
  name: string;
  greeting: string | null;
  avatar_url: string | null;
  avatar_color: number | null;
  model_profile_id: string | null;
  collection_ids: string[];
  /** `agents:run`, as for any agent. Without it there is no assistant at all. */
  can_use: boolean;
  can_configure: boolean;
}

export interface AssistantUpdate {
  enabled?: boolean;
  name?: string;
  greeting?: string | null;
  model_profile_id?: string | null;
  collection_ids?: string[];
}
