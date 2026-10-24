/** What the console hears when a resource changes somewhere else (#2061). */

export type ChangeResource =
  | "agent"
  | "skill"
  | "context"
  | "knowledge_base"
  | "artifact"
  | "member"
  | "invitation"
  | "group"
  | "organization"
  | "trigger"
  | "channel"
  | "notification"
  | "secret"
  | "mcp_connection"
  | "run"
  | "eval_suite"
  | "eval_run"
  | "dataset"
  | "knowledge_gap";

export type ChangeAction = "created" | "updated" | "deleted";

/** A console session, an organization API key, an MCP client signed in over
 *  OAuth, or the in-app Architect. */
export type ChangeSurface = "console" | "api_key" | "mcp" | "assistant";

interface ChangeEventBase {
  organization_id: string;
  resource: ChangeResource;
  /** The changed row; null when the write did not name one. */
  id: string | null;
  action: ChangeAction;
  /** The console tab that made the change, when one did (`X-Console-Tab`). */
  origin_tab: string | null;
}

/** A change somebody made: a write through the console, a key, MCP or the Architect. */
export interface MadeChange extends ChangeEventBase {
  surface: ChangeSurface;
  actor_user_id: string;
  actor_name: string;
}

/**
 * A change a run made rather than a request: a run moving through its states -
 * started, parked, finished - an eval suite's result settling, or a dataset the
 * case generator finished drafting into.
 */
export interface RunChange extends ChangeEventBase {
  resource: "run" | "eval_suite" | "eval_run" | "dataset";
  surface: "run";
  /** The member the run acts as, when it acts as one. */
  actor_user_id: string | null;
  actor_name: null;
}

/** Work the platform does on its own schedule, such as a grouping pass placing questions. */
export interface SystemChange extends ChangeEventBase {
  resource: "knowledge_gap";
  surface: "system";
  actor_user_id: null;
  actor_name: null;
}

export type ChangeEvent = MadeChange | RunChange | SystemChange;
