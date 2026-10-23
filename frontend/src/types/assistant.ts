/** The organization's AI Architect, as the widget and its settings read it (#2063). */

export type AssistantStatus = "ready" | "needs_model" | "disabled" | "unavailable";

export interface AssistantState {
  status: AssistantStatus;
  agent_id: string | null;
  /** Its handle, which its default face is drawn from. */
  slug: string | null;
  name: string;
  /** Still the name it was installed with - shown as the console's own, translated. */
  named_by_default: boolean;
  greeting: string | null;
  avatar_url: string | null;
  avatar_color: number | null;
  /** Still wears the mark it shipped with, which the console draws in the theme's colours. */
  wears_mark: boolean;
  /** `agents:run`, as for any agent. Without it there is no assistant at all. */
  can_use: boolean;
  can_configure: boolean;
}

/** What the organization decides about it; the agent itself is edited in the Builder. */
export interface AssistantUpdate {
  enabled?: boolean;
  greeting?: string | null;
}

/** What the widget's bubble may raise, read through each page's own scope. */
export interface AssistantSignals {
  pending_approvals: number;
  has_agents: boolean;
  failed_run_id: string | null;
}
